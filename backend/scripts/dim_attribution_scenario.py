"""维度归属冲突场景演示：冲突前后分别请求省、市两档立方体结果。

运行：python -m scripts.dim_attribution_scenario
（在 backend 目录下执行；脚本只依赖标准库与本项目 service 层）

场景：
  1. 地区维度 DIM-REGION 同时登记旧表 legacy_dim_region（省/市两级）
     与新表 province_dim_region（仅省级）；
  2. 冲突前（09-14）：新登记未生效，省/市都只能读旧来源；
  3. 冲突日（09-15）：两登记同日有效，但新登记未确认 -> 只读，
     市级对账仍可读旧来源出市级数，新来源取不到市级粒度；
  4. 确认新归属后（09-16）：省档优先采纳新来源（只出它实际覆盖的省级粒度，
     城市键全部计入未覆盖），市档仍只能回旧来源。
"""
from __future__ import annotations

from app.services.cube_dimension_query import aggregate_by_validated_attribution
from app.services.dim_attribution import attribution_registry, reset_attribution_registry
from app.dim_attribution_fixtures import (
    AFTER_CONFLICT_DATE,
    BEFORE_CONFLICT_DATE,
    CONFLICT_DATE,
)

DIM = "DIM-REGION"


def _line(symbol: str, text: str) -> None:
    print(f"{symbol} {text}")


def show_dataset(biz_date: str) -> None:
    ds = attribution_registry.validate(biz_date)
    _line("📋", f"业务日 {biz_date} 维度归属数据集（来源 + 业务键 + 允许层级 一起确认）")
    for r in ds["records"]:
        if r["维度编号"] != DIM:
            continue
        print(
            f"   - {r['归属ID']:<40} 状态={r['status']:<9} "
            f"允许层级={r['允许层级']} 实际覆盖={r['来源实际覆盖层级']}"
        )
        for reason in r["reasons"]:
            print(f"       ↳ {reason}")
    if ds["conflicts"]:
        for c in ds["conflicts"]:
            _line("⚠️ ", f"归属冲突：{c['维度编号']} 同日有效归属 {c['冲突归属']}")
    else:
        _line("✅", "该业务日无归属冲突")


def show_aggregate(level: str, biz_date: str, source: str | None = None) -> None:
    res = aggregate_by_validated_attribution(DIM, level, biz_date, source)
    label = f"{level} 档" + (f"（显式指定来源 {source}）" if source else "（默认选源）")
    if not res["ok"]:
        _line("🚫", f"{label} 不出数：{res['message']}")
        print(f"       层级可用性：{res['level_availability']}")
        return
    _line("🧊", f"{label} 采纳来源={res['采纳来源']} 实际粒度={res['实际粒度']}")
    for g in res["groups"]:
        print(
            f"       分组 {g['分组名称']}({g['分组键']}) "
            f"gmv={g['gmv']:.2f} 订单数={g['订单数']} 明细={g['fact_order_ids']}"
        )
    t = res["totals"]
    print(
        f"       合计：已聚合 {t['已聚合金额']:.2f}/{t['已聚合订单数']} 笔，"
        f"未覆盖 {t['未覆盖金额']:.2f}/{t['未覆盖订单数']} 笔"
    )
    for f in res["unmapped_facts"]:
        print(f"       ↳ 未覆盖 {f['order_id']} 金额 {f['amount']:.2f}：{f['reason']}")


def main() -> None:
    reset_attribution_registry()

    for biz_date in (BEFORE_CONFLICT_DATE, CONFLICT_DATE):
        print("=" * 88)
        show_dataset(biz_date)
        show_aggregate("province", biz_date)
        show_aggregate("city", biz_date)
        show_aggregate("city", biz_date, source="province_dim_region")

    print("=" * 88)
    _line("🔧", "确认新来源归属 REG-REGION-PROVINCE（来源、业务键、允许层级一并确认）")
    entry, message = attribution_registry.confirm("REG-REGION-PROVINCE")
    print(f"   {message}：{entry['来源']} 允许层级 {entry['允许层级']}")

    print("=" * 88)
    show_dataset(AFTER_CONFLICT_DATE)
    show_aggregate("province", AFTER_CONFLICT_DATE)
    show_aggregate("city", AFTER_CONFLICT_DATE)
    show_aggregate("province", AFTER_CONFLICT_DATE, source="legacy_dim_region")

    print("=" * 88)
    _line("🔍", "逐笔金额落点核对（冲突后省档，新来源）")
    res = aggregate_by_validated_attribution(DIM, "province", AFTER_CONFLICT_DATE)
    for a in res["fact_assignments"]:
        where = a["分组名称"] if a["是否计入"] else "未覆盖（新来源无此键映射）"
        print(f"   {a['order_id']} 金额 {a['amount']:.2f} 键={a['region_code']} -> {where}")


if __name__ == "__main__":
    main()
