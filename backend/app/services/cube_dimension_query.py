"""立方体维度取数服务：只按已校验的维度归属聚合事实数据。

与旧 ``pipeline_orchestrator.run_cube_pipeline`` 的硬编码 ``dim_field_map`` 不同，
本服务的每一次取数都必须先经过维度归属校验：

1. 从维度归属数据集里挑选 ACTIVE 且覆盖请求层级的归属；
   READ_ONLY / INVALID 归属永远不会被用于聚合。
2. 归属身份是 (来源, 业务键)，不同来源的同名维度不会被当成同一归属。
3. 来源没有覆盖的层级不出数，只回覆盖说明；事实键无法映射时计入未覆盖明细，
   绝不静默丢弃。
4. 结果附上实际使用的来源、粒度、每笔金额所在分组，供分析端核对省、市小计。
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from app.dim_attribution_fixtures import (
    DIMENSION_SOURCES,
    REGION_ORDER_FACTS,
)
from app.services.dim_attribution import ACTIVE, attribution_registry


def _eligible_attributions(dataset: dict[str, Any], dim_code: str, level: str) -> list[dict[str, Any]]:
    """从归属数据集里挑出可用于该层级聚合的 ACTIVE 归属。"""
    out = []
    for rec in dataset["records"]:
        if rec["维度编号"] != dim_code:
            continue
        if rec["status"] != ACTIVE:
            continue
        if level not in rec["允许层级"]:
            continue
        if level not in rec["来源实际覆盖层级"]:
            continue
        out.append(rec)
    return out


def _select_attribution(candidates: list[dict[str, Any]], preferred_source: str | None) -> dict[str, Any]:
    """多个有效归属时的选择策略：优先显式指定来源，其次覆盖层级更窄（更专用）的来源。"""
    if preferred_source is not None:
        for rec in candidates:
            if rec["来源"] == preferred_source:
                return rec
        raise KeyError(preferred_source)
    # 覆盖层级数量越少 = 越专用，优先采用；并列时按来源名稳定排序
    return sorted(candidates, key=lambda r: (len(r["来源实际覆盖层级"]), r["来源"]))[0]


def _build_lookup(source: str, key_field: str, level: str) -> dict[str, dict[str, Any]]:
    """按归属指定的来源与业务键构建维度查找表（立方体不再持有任何自有映射）。

    - 省级：来源里任意层级的行都可上卷到其 ``province_code``（城市行也带省码）；
    - 市级：只有 ``level == 'city'`` 的行能命中，省级键不会被强行下钻。
    """
    table = DIMENSION_SOURCES[source]
    lookup: dict[str, dict[str, Any]] = {}
    for row in table:
        if level == "city" and row.get("level") != "city":
            continue
        lookup[str(row[key_field])] = dict(row)
    return lookup


def aggregate_by_validated_attribution(
    dim_code: str,
    level: str,
    biz_date: str,
    preferred_source: str | None = None,
) -> dict[str, Any]:
    """按本次有效归属聚合地区事实数据。

    返回结构包含：采纳的来源与粒度、分组小计、每笔事实的落点（含未覆盖原因），
    以及省/市小计各自可用层级的核对信息。
    """
    dataset = attribution_registry.validate(biz_date)

    # 先把该维度在业务日的全部归属状态整理出来，便于分析端核对
    dim_records = [
        {
            "归属ID": r["归属ID"],
            "来源": r["来源"],
            "业务键": r["业务键"],
            "允许层级": r["允许层级"],
            "status": r["status"],
            "来源实际覆盖层级": r["来源实际覆盖层级"],
            "has_conflict": r["has_conflict"],
            "reasons": r["reasons"],
            "coverage_note": r["coverage_note"],
        }
        for r in dataset["records"]
        if r["维度编号"] == dim_code
    ]

    candidates = _eligible_attributions(dataset, dim_code, level)
    level_availability = {
        lvl: sorted({r["来源"] for r in _eligible_attributions(dataset, dim_code, lvl)})
        for lvl in ("province", "city")
    }

    if not candidates:
        # 未声明/未覆盖层级：不出数，只给覆盖说明
        return {
            "ok": False,
            "业务日": biz_date,
            "维度编号": dim_code,
            "请求层级": level,
            "采纳来源": None,
            "message": f"业务日 {biz_date} 没有已确认且覆盖层级 {level} 的有效归属，该层级不出数",
            "attribution_records": dim_records,
            "level_availability": level_availability,
            "conflicts": dataset["conflicts"],
            "groups": [],
            "fact_assignments": [],
            "unmapped_facts": [],
        }

    try:
        chosen = _select_attribution(candidates, preferred_source)
    except KeyError:
        available = [r["来源"] for r in candidates]
        return {
            "ok": False,
            "业务日": biz_date,
            "维度编号": dim_code,
            "请求层级": level,
            "采纳来源": None,
            "message": f"指定来源 {preferred_source} 未确认或不覆盖层级 {level}，当前可用来源：{available}",
            "attribution_records": dim_records,
            "level_availability": level_availability,
            "conflicts": dataset["conflicts"],
            "groups": [],
            "fact_assignments": [],
            "unmapped_facts": [],
        }

    source = chosen["来源"]
    key_field = chosen["业务键"]
    lookup = _build_lookup(source, key_field, level)
    facts = [f for f in REGION_ORDER_FACTS if f["business_date"] == biz_date]

    # 分组聚合 + 逐笔落点
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    assignments: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []

    for fact in facts:
        key = str(fact["region_code"])
        dim_row = lookup.get(key)
        if dim_row is None:
            reason = (
                f"来源 {source} 在层级 {level} 上不存在业务键 {key} 的映射"
                f"（该来源实际覆盖层级：{chosen['来源实际覆盖层级']}）"
            )
            unmapped.append({
                "order_id": fact["order_id"],
                "region_code": key,
                "amount": fact["amount"],
                "reason": reason,
            })
            assignments.append({
                "order_id": fact["order_id"],
                "amount": fact["amount"],
                "region_code": key,
                "采纳来源": source,
                "层级": level,
                "分组": None,
                "是否计入": False,
                "原因": reason,
            })
            continue

        group_key = dim_row.get("province_code", key) if level == "province" else key
        group_name = dim_row.get("province_name") if level == "province" else dim_row.get("region_name")
        if group_key not in groups:
            groups[group_key] = {
                "分组键": group_key,
                "分组名称": group_name,
                "层级": level,
                "采纳来源": source,
                "业务键": key_field,
                "订单数": 0,
                "gmv": 0.0,
                "fact_order_ids": [],
            }
        groups[group_key]["订单数"] += 1
        groups[group_key]["gmv"] = round(groups[group_key]["gmv"] + fact["amount"], 2)
        groups[group_key]["fact_order_ids"].append(fact["order_id"])
        assignments.append({
            "order_id": fact["order_id"],
            "amount": fact["amount"],
            "region_code": key,
            "采纳来源": source,
            "层级": level,
            "分组": group_key,
            "分组名称": group_name,
            "是否计入": True,
            "原因": "命中已校验归属的维度映射",
        })

    group_list = list(groups.values())
    mapped_gmv = round(sum(g["gmv"] for g in group_list), 2)
    unmapped_gmv = round(sum(f["amount"] for f in unmapped), 2)

    return {
        "ok": True,
        "业务日": biz_date,
        "维度编号": dim_code,
        "请求层级": level,
        "采纳来源": source,
        "采纳归属ID": chosen["归属ID"],
        "业务键": key_field,
        "实际粒度": level,
        "attribution_records": dim_records,
        "level_availability": level_availability,
        "conflicts": dataset["conflicts"],
        "groups": group_list,
        "fact_assignments": assignments,
        "unmapped_facts": unmapped,
        "totals": {
            "事实总金额": round(mapped_gmv + unmapped_gmv, 2),
            "已聚合金额": mapped_gmv,
            "未覆盖金额": unmapped_gmv,
            "已聚合订单数": sum(g["订单数"] for g in group_list),
            "未覆盖订单数": len(unmapped),
        },
        "coverage_note": chosen["coverage_note"],
    }
