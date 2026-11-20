"""维度归属校验服务：计算前校验维度归属，生成维度归属数据集。

核心规则（对应需求）：

1. 归属身份由「来源 + 业务键」共同确认；不同来源的同名维度是不同归属，
   校验与聚合都不允许合并。
2. 来源、业务键、允许的层级必须一起确认：
   - 来源表不存在 / 业务键字段缺失 / 声明层级未被来源实际覆盖 → INVALID；
   - 登记未确认或尚未到生效日 → READ_ONLY，只读，不能驱动任何聚合；
   - 校验通过且在业务日生效 → ACTIVE，立方体只能按 ACTIVE 归属取数。
3. 同一维度在同一业务日出现多条 ACTIVE 归属 → 标记归属冲突，
   数据集保留全部记录，由立方体按层级覆盖情况选择，而不是静默覆盖。
4. 未声明的层级不出数，只能返回来源的覆盖说明。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.dim_attribution_fixtures import (
    DIMENSION_SOURCES,
    DIM_REGISTRATIONS,
)

# 归属记录校验状态
ACTIVE = "ACTIVE"          # 已确认、已生效、层级覆盖完整，可驱动聚合
READ_ONLY = "READ_ONLY"    # 未确认/未生效：只读，不能用于聚合
INVALID = "INVALID"        # 来源缺失或层级与实际覆盖不符：登记需修正

CONFIRMED = "confirmed"
PENDING = "pending"


def _source_covered_levels(source: str) -> set[str]:
    """读取来源表实际覆盖的层级（取维度表 level 列的去重值）。"""
    table = DIMENSION_SOURCES.get(source)
    if not table:
        return set()
    return {str(row.get("level")) for row in table if row.get("level")}


def _source_key_available(source: str, key_field: str) -> bool:
    table = DIMENSION_SOURCES.get(source)
    if not table:
        return False
    return all(key_field in row for row in table)


class AttributionRegistry:
    """维度登记表的可变状态与校验入口（测试可 reset 隔离）。"""

    def __init__(self) -> None:
        self._registrations: list[dict[str, Any]] = deepcopy(DIM_REGISTRATIONS)

    def reset(self) -> None:
        self._registrations = deepcopy(DIM_REGISTRATIONS)

    def list_registrations(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._registrations]

    def find_registration(self, reg_id: str) -> dict[str, Any] | None:
        for row in self._registrations:
            if row.get("登记编号") == reg_id:
                return row
        return None

    def confirm(self, reg_id: str) -> tuple[dict[str, Any] | None, str]:
        """确认一条归属登记；已确认/不存在的登记给出明确拒绝原因。"""
        row = self.find_registration(reg_id)
        if row is None:
            return None, f"登记 {reg_id} 不存在"
        if row["确认状态"] == CONFIRMED:
            return row, "该归属已确认，无需重复操作"
        row["确认状态"] = CONFIRMED
        return dict(row), "归属已确认，下一次校验将纳入 ACTIVE 归属"

    # ------------------------------------------------------------------
    # 核心：按业务日生成维度归属数据集
    # ------------------------------------------------------------------
    def validate(self, biz_date: str) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for reg in self._registrations:
            record = self._validate_one(reg, biz_date)
            records.append(record)

        # 冲突识别：同一维度同一业务日存在多条 ACTIVE 归属
        active_by_dim: dict[str, list[dict[str, Any]]] = {}
        for rec in records:
            if rec["status"] == ACTIVE:
                active_by_dim.setdefault(rec["维度编号"], []).append(rec)

        conflicts: list[dict[str, Any]] = []
        for dim_code, group in active_by_dim.items():
            if len(group) > 1:
                ids = [r["归属ID"] for r in group]
                for rec in group:
                    rec["has_conflict"] = True
                    rec["conflicts_with"] = [i for i in ids if i != rec["归属ID"]]
                conflicts.append({
                    "维度编号": dim_code,
                    "维度名称": group[0]["维度名称"],
                    "业务日": biz_date,
                    "冲突归属": ids,
                    "说明": "同一业务日存在多条已确认归属，立方体须按请求层级选择实际覆盖的来源",
                })

        return {
            "业务日": biz_date,
            "records": records,
            "conflicts": conflicts,
            "summary": {
                "登记总数": len(records),
                "active": sum(1 for r in records if r["status"] == ACTIVE),
                "read_only": sum(1 for r in records if r["status"] == READ_ONLY),
                "invalid": sum(1 for r in records if r["status"] == INVALID),
                "冲突维度数": len(conflicts),
            },
        }

    def _validate_one(self, reg: dict[str, Any], biz_date: str) -> dict[str, Any]:
        source = str(reg["来源"])
        key_field = str(reg["业务键"])
        allowed_levels = list(reg["允许层级"])
        # 归属身份：来源 + 业务键，与维度名解耦
        attribution_id = f"{source}#{key_field}"

        record: dict[str, Any] = {
            "登记编号": reg["登记编号"],
            "维度编号": reg["维度编号"],
            "维度名称": reg["维度名称"],
            "来源": source,
            "业务键": key_field,
            "允许层级": allowed_levels,
            "生效日期": reg["生效日期"],
            "失效日期": reg["失效日期"],
            "确认状态": reg["确认状态"],
            "归属ID": attribution_id,
            "来源实际覆盖层级": sorted(_source_covered_levels(source)),
            "has_conflict": False,
            "conflicts_with": [],
            "reasons": [],
            "coverage_note": "",
        }

        # 规则 1：来源表必须存在，业务键字段必须可用
        if source not in DIMENSION_SOURCES:
            record["status"] = INVALID
            record["reasons"].append(f"来源表 {source} 在维度来源仓库中不存在")
            record["coverage_note"] = f"来源 {source} 不可用，无覆盖说明可提供"
            return record
        if not _source_key_available(source, key_field):
            record["status"] = INVALID
            record["reasons"].append(f"来源表 {source} 缺少业务键字段 {key_field}")
            return record

        covered = _source_covered_levels(source)
        # 规则 2：声明的每个层级都必须被来源实际覆盖，否则登记与映射不一致
        uncovered = [lvl for lvl in allowed_levels if lvl not in covered]
        if uncovered:
            record["status"] = INVALID
            record["reasons"].append(
                f"声明层级 {uncovered} 未被来源 {source} 覆盖，实际覆盖：{sorted(covered)}"
            )
            record["coverage_note"] = (
                f"来源 {source} 仅覆盖 {sorted(covered)}，未声明/未覆盖层级只能查看本说明"
            )
            return record

        record["coverage_note"] = (
            f"来源 {source} 可在层级 {sorted(covered)} 上按业务键 {key_field} 取数"
        )

        # 规则 3：生效窗口
        in_window = reg["生效日期"] <= biz_date and (
            reg["失效日期"] is None or reg["失效日期"] > biz_date
        )
        if not in_window:
            record["status"] = READ_ONLY
            record["reasons"].append(f"登记在业务日 {biz_date} 尚未进入生效窗口")
            return record

        # 规则 4：必须确认归属（来源、业务键、允许层级一起确认）
        if reg["确认状态"] != CONFIRMED:
            record["status"] = READ_ONLY
            record["reasons"].append("归属未经确认，记录只读，不能用于任何来源的聚合")
            return record

        record["status"] = ACTIVE
        record["reasons"].append("来源、业务键与允许层级校验通过，业务日内有效")
        return record


# 单例状态，路由层与立方体查询共用同一份登记数据
attribution_registry = AttributionRegistry()


def reset_attribution_registry() -> None:
    """重置登记状态，供测试隔离。"""
    attribution_registry.reset()
