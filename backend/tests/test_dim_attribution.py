"""维度归属校验与立方体按校验结果取数的规则测试。"""
from __future__ import annotations

import pytest

from app.services.cube_dimension_query import aggregate_by_validated_attribution
from app.services.dim_attribution import (
    ACTIVE,
    INVALID,
    READ_ONLY,
    attribution_registry,
    reset_attribution_registry,
)

DIM = "DIM-REGION"
LEGACY = "legacy_dim_region"
NEW = "province_dim_region"
BEFORE = "2026-09-14"
CONFLICT = "2026-09-15"
AFTER = "2026-09-16"


@pytest.fixture(autouse=True)
def fresh_registry():
    reset_attribution_registry()
    yield
    reset_attribution_registry()


def _record(dataset: dict, reg_id: str) -> dict:
    return next(r for r in dataset["records"] if r["登记编号"] == reg_id)


class TestAttributionValidation:
    """校验规则：来源、业务键、允许层级一起确认。"""

    def test_before_conflict_only_legacy_is_active(self):
        ds = attribution_registry.validate(BEFORE)
        legacy = _record(ds, "REG-REGION-LEGACY")
        new = _record(ds, "REG-REGION-PROVINCE")
        assert legacy["status"] == ACTIVE
        # 新来源尚未到生效日
        assert new["status"] == READ_ONLY
        assert ds["conflicts"] == []

    def test_conflict_day_new_source_is_read_only(self):
        ds = attribution_registry.validate(CONFLICT)
        new = _record(ds, "REG-REGION-PROVINCE")
        legacy = _record(ds, "REG-REGION-LEGACY")
        assert new["status"] == READ_ONLY
        assert any("未经确认" in reason for reason in new["reasons"])
        # 只有一条 ACTIVE，不构成冲突
        assert legacy["status"] == ACTIVE
        assert ds["conflicts"] == []

    def test_after_confirm_two_active_attributions_conflict(self):
        attribution_registry.confirm("REG-REGION-PROVINCE")
        ds = attribution_registry.validate(AFTER)
        legacy = _record(ds, "REG-REGION-LEGACY")
        new = _record(ds, "REG-REGION-PROVINCE")
        assert legacy["status"] == ACTIVE and new["status"] == ACTIVE
        assert len(ds["conflicts"]) == 1
        assert set(ds["conflicts"][0]["冲突归属"]) == {
            f"{LEGACY}#region_code",
            f"{NEW}#region_code",
        }
        assert legacy["has_conflict"] and new["has_conflict"]

    def test_missing_source_table_is_invalid(self):
        ds = attribution_registry.validate(AFTER)
        stale = _record(ds, "REG-CHANNEL-STALE")
        assert stale["status"] == INVALID
        assert any("不存在" in r for r in stale["reasons"])

    def test_undeclared_level_coverage_mismatch_is_invalid(self):
        ds = attribution_registry.validate(AFTER)
        bad = _record(ds, "REG-CHANNEL-LEVEL-MISMATCH")
        assert bad["status"] == INVALID
        assert any("未被来源" in r for r in bad["reasons"])
        # 未声明层级只能看覆盖说明
        assert "仅覆盖" in bad["coverage_note"]

    def test_attribution_identity_keeps_same_named_dimensions_apart(self):
        """不同来源的同名维度不是同一归属：归属ID 必须不同且各自独立校验。"""
        ds = attribution_registry.validate(AFTER)
        region_ids = {r["归属ID"] for r in ds["records"] if r["维度编号"] == DIM}
        assert region_ids == {f"{LEGACY}#region_code", f"{NEW}#region_code"}
        channel_ids = {r["归属ID"] for r in ds["records"] if r["维度编号"] == "DIM-CHANNEL"}
        assert f"{LEGACY}#region_code" not in channel_ids


class TestReadOnlyIsolation:
    """未经确认的归属记录只读，不能用于另一个来源的聚合。"""

    def test_read_only_attribution_never_drives_aggregation(self):
        # 冲突日显式请求新来源：它还是 READ_ONLY，必须被拒绝
        result = aggregate_by_validated_attribution(DIM, "province", CONFLICT, preferred_source=NEW)
        assert result["ok"] is False
        assert result["采纳来源"] is None
        assert result["groups"] == []
        rec = next(r for r in result["attribution_records"] if r["来源"] == NEW)
        assert rec["status"] == READ_ONLY

    def test_read_only_record_remains_visible_with_reasons(self):
        ds = attribution_registry.validate(CONFLICT)
        new = _record(ds, "REG-REGION-PROVINCE")
        assert new["status"] == READ_ONLY
        assert new["reasons"]  # 只读原因可追溯


class TestCubeAggregationBeforeConflict:
    """冲突前：省、市两档都走旧来源。"""

    def test_city_level_uses_legacy_with_full_city_mapping(self):
        result = aggregate_by_validated_attribution(DIM, "city", BEFORE)
        assert result["ok"] is True
        assert result["采纳来源"] == LEGACY
        assert result["实际粒度"] == "city"
        # 4 个市级分组，每笔城市键金额都能落到组里
        assert len(result["groups"]) == 4
        assert result["totals"]["已聚合订单数"] == 4
        assert result["totals"]["已聚合金额"] == 2400.0
        # 省级键在市级层级无法映射 -> 未覆盖，不静默丢弃
        assert result["totals"]["未覆盖订单数"] == 2
        assert result["totals"]["未覆盖金额"] == 1300.0

    def test_province_level_before_conflict_uses_legacy(self):
        result = aggregate_by_validated_attribution(DIM, "province", BEFORE)
        assert result["采纳来源"] == LEGACY
        by_group = {g["分组键"]: g["gmv"] for g in result["groups"]}
        # 上海：城市 300+500 + 省级 400；北京：城市 700+900 + 省级 900
        assert by_group == {"prov_shanghai": 1200.0, "prov_beijing": 2500.0}
        assert result["totals"]["未覆盖订单数"] == 0

    def test_every_fact_assignment_is_traceable(self):
        result = aggregate_by_validated_attribution(DIM, "city", BEFORE)
        assert len(result["fact_assignments"]) == 6
        mapped = [a for a in result["fact_assignments"] if a["是否计入"]]
        assert {a["order_id"] for a in mapped} == {"O-1001", "O-1002", "O-1003", "O-1004"}
        for a in mapped:
            assert a["采纳来源"] == LEGACY and a["分组"]


class TestCubeAggregationConflictDay:
    """冲突日：新来源只读 -> 省档仍可由旧来源出数，市档只能读旧来源。"""

    def test_city_reconciliation_still_possible_via_legacy(self):
        result = aggregate_by_validated_attribution(DIM, "city", CONFLICT)
        assert result["采纳来源"] == LEGACY
        assert result["totals"]["已聚合金额"] == 2400.0

    def test_province_default_falls_back_to_legacy_when_new_pending(self):
        result = aggregate_by_validated_attribution(DIM, "province", CONFLICT)
        assert result["采纳来源"] == LEGACY
        assert result["totals"]["已聚合金额"] == 3700.0

    def test_new_source_only_returns_coverage_note_at_city_level(self):
        result = aggregate_by_validated_attribution(DIM, "city", CONFLICT, preferred_source=NEW)
        assert result["ok"] is False
        assert "city" in result["level_availability"]
        assert LEGACY in result["level_availability"]["city"]
        assert NEW not in result["level_availability"]["city"]


class TestCubeAggregationAfterConflict:
    """确认后：省档优先采用只覆盖省份的新来源；市档仍只能回旧来源。"""

    def test_province_adopts_new_source_with_its_real_granularity(self):
        attribution_registry.confirm("REG-REGION-PROVINCE")
        result = aggregate_by_validated_attribution(DIM, "province", AFTER)
        assert result["采纳来源"] == NEW
        assert result["实际粒度"] == "province"
        # 新来源只有省级映射：城市键全部成为未覆盖，只聚合它实际覆盖的粒度
        assert result["totals"]["已聚合金额"] == 1300.0
        assert result["totals"]["未覆盖金额"] == 2400.0
        assert result["totals"]["未覆盖订单数"] == 4
        by_group = {g["分组键"]: g["gmv"] for g in result["groups"]}
        assert by_group == {"prov_shanghai": 400.0, "prov_beijing": 900.0}

    def test_city_level_still_routed_to_legacy_after_confirm(self):
        attribution_registry.confirm("REG-REGION-PROVINCE")
        result = aggregate_by_validated_attribution(DIM, "city", AFTER)
        assert result["采纳来源"] == LEGACY
        assert result["totals"]["已聚合金额"] == 2400.0

    def test_explicit_legacy_source_still_available_for_province(self):
        attribution_registry.confirm("REG-REGION-PROVINCE")
        result = aggregate_by_validated_attribution(DIM, "province", AFTER, preferred_source=LEGACY)
        assert result["采纳来源"] == LEGACY
        assert result["totals"]["已聚合金额"] == 3700.0

    def test_conflict_metadata_is_attached_for_analysis(self):
        attribution_registry.confirm("REG-REGION-PROVINCE")
        result = aggregate_by_validated_attribution(DIM, "province", AFTER)
        assert result["conflicts"]
        sources = {r["来源"]: r["status"] for r in result["attribution_records"]}
        assert sources == {LEGACY: ACTIVE, NEW: ACTIVE}


class TestLevelAvailabilitySummary:
    """分析端据此核对省、市小计各自能使用的层级。"""

    def test_availability_reflects_confirmation_state(self):
        before = aggregate_by_validated_attribution(DIM, "province", BEFORE)
        assert before["level_availability"] == {
            "province": [LEGACY],
            "city": [LEGACY],
        }
        attribution_registry.confirm("REG-REGION-PROVINCE")
        after = aggregate_by_validated_attribution(DIM, "province", AFTER)
        assert set(after["level_availability"]["province"]) == {LEGACY, NEW}
        assert after["level_availability"]["city"] == [LEGACY]
