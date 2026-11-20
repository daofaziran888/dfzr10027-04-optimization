"""维度归属场景数据集：同一地区维度的旧来源、新来源与事实数据。

设计要点（对应「地区维度旧登记与新来源同业务日冲突」场景）：

- 旧来源 ``legacy_dim_region`` 保留 省/市 两级映射，市级映射只在这里存在；
- 新来源 ``province_dim_region`` 只覆盖省级粒度，无法解析城市键；
- 事实表 ``region_order_facts`` 同时含有市级键（city_*）与省级键（prov_*），
  用于核对每个来源实际能聚合到哪些粒度、每笔金额落在哪个分组。

全部为标准 Python 数据结构，不依赖外部存储，保证克隆即可运行。
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. 维度登记表（dim_registration）
#    一条登记 = 维度 + 来源 + 业务键 + 允许层级 + 生效区间 + 确认状态。
#    归属身份由 (来源, 业务键) 共同决定：不同来源的同名维度不是同一归属。
# ---------------------------------------------------------------------------
DIM_REGISTRATIONS: list[dict] = [
    {
        "登记编号": "REG-REGION-LEGACY",
        "维度编号": "DIM-REGION",
        "维度名称": "地理区域",
        "来源": "legacy_dim_region",
        "业务键": "region_code",
        "允许层级": ["province", "city"],
        "生效日期": "2026-09-01",
        "失效日期": None,
        "确认状态": "confirmed",
        "备注": "旧登记：保留省、市两级映射，市级对账只能读这里",
    },
    {
        "登记编号": "REG-REGION-PROVINCE",
        "维度编号": "DIM-REGION",
        "维度名称": "地理区域",
        "来源": "province_dim_region",
        "业务键": "region_code",
        "允许层级": ["province"],
        "生效日期": "2026-09-15",
        "失效日期": None,
        # 冲突日当天该登记尚未确认 -> 只能只读，不能驱动聚合
        "确认状态": "pending",
        "备注": "新来源：仅覆盖省级粒度，无市级映射",
    },
    {
        "登记编号": "REG-CHANNEL-LEGACY",
        "维度编号": "DIM-CHANNEL",
        "维度名称": "流量渠道",
        "来源": "legacy_dim_channel",
        "业务键": "channel_id",
        "允许层级": ["primary_channel", "sub_channel"],
        "生效日期": "2026-09-01",
        "失效日期": None,
        "确认状态": "confirmed",
        "备注": "渠道维度旧来源（用于验证同名维度跨来源不合并）",
    },
    {
        "登记编号": "REG-CHANNEL-STALE",
        "维度编号": "DIM-CHANNEL",
        "维度名称": "流量渠道",
        "来源": "stale_dim_channel",
        "业务键": "channel_id",
        "允许层级": ["primary_channel", "sub_channel"],
        "生效日期": "2026-09-01",
        "失效日期": None,
        "确认状态": "confirmed",
        "备注": "失效样例：来源表在仓库里不存在，校验必须判 INVALID",
    },
    {
        "登记编号": "REG-CHANNEL-LEVEL-MISMATCH",
        "维度编号": "DIM-CHANNEL",
        "维度名称": "流量渠道",
        "来源": "legacy_dim_channel",
        "业务键": "channel_id",
        # 登记表声称支持二级渠道，但来源表实际只有一级 -> 层级与覆盖不符
        "允许层级": ["primary_channel", "sub_channel", "dream_level"],
        "生效日期": "2026-09-01",
        "失效日期": None,
        "确认状态": "confirmed",
        "备注": "失效样例：声明了来源未覆盖的层级",
    },
]

# ---------------------------------------------------------------------------
# 2. 地区维度旧来源：能查到城市（省/市两级）
# ---------------------------------------------------------------------------
LEGACY_DIM_REGION: list[dict] = [
    {"region_code": "city_sh_huangpu", "level": "city", "province_code": "prov_shanghai",
     "province_name": "上海市", "city_name": "上海市·黄浦", "region_name": "上海市·黄浦"},
    {"region_code": "city_sh_pudong", "level": "city", "province_code": "prov_shanghai",
     "province_name": "上海市", "city_name": "上海市·浦东", "region_name": "上海市·浦东"},
    {"region_code": "city_bj_chaoyang", "level": "city", "province_code": "prov_beijing",
     "province_name": "北京市", "city_name": "北京市·朝阳", "region_name": "北京市·朝阳"},
    {"region_code": "city_bj_haidian", "level": "city", "province_code": "prov_beijing",
     "province_name": "北京市", "city_name": "北京市·海淀", "region_name": "北京市·海淀"},
    {"region_code": "prov_shanghai", "level": "province", "province_code": "prov_shanghai",
     "province_name": "上海市", "city_name": None, "region_name": "上海市"},
    {"region_code": "prov_beijing", "level": "province", "province_code": "prov_beijing",
     "province_name": "北京市", "city_name": None, "region_name": "北京市"},
]

# ---------------------------------------------------------------------------
# 3. 地区维度新来源：只含省份（省级粒度），没有任何市级映射
# ---------------------------------------------------------------------------
PROVINCE_DIM_REGION: list[dict] = [
    {"region_code": "prov_shanghai", "level": "province",
     "province_code": "prov_shanghai", "province_name": "上海市", "region_name": "上海市"},
    {"region_code": "prov_beijing", "level": "province",
     "province_code": "prov_beijing", "province_name": "北京市", "region_name": "北京市"},
]

# ---------------------------------------------------------------------------
# 4. 渠道旧来源（供同名维度跨来源校验使用，仅一级）
# ---------------------------------------------------------------------------
LEGACY_DIM_CHANNEL: list[dict] = [
    {"channel_id": "ch_app", "level": "primary_channel", "channel_name": "App"},
    {"channel_id": "ch_h5", "level": "primary_channel", "channel_name": "H5"},
]

# ---------------------------------------------------------------------------
# 5. 事实表：地区订单（含市级键与省级键两种行，金额可逐笔追踪分组）
#    三个业务日复用同一批事实，便于冲突前后同口径对比。
# ---------------------------------------------------------------------------
REGION_ORDER_FACTS: list[dict] = [
    {"order_id": "O-1001", "business_date": "2026-09-14", "region_code": "city_sh_huangpu", "amount": 300.0},
    {"order_id": "O-1002", "business_date": "2026-09-14", "region_code": "city_sh_pudong", "amount": 500.0},
    {"order_id": "O-1003", "business_date": "2026-09-14", "region_code": "city_bj_chaoyang", "amount": 700.0},
    {"order_id": "O-1004", "business_date": "2026-09-14", "region_code": "city_bj_haidian", "amount": 900.0},
    {"order_id": "O-1005", "business_date": "2026-09-14", "region_code": "prov_shanghai", "amount": 400.0},
    {"order_id": "O-1006", "business_date": "2026-09-14", "region_code": "prov_beijing", "amount": 900.0},
    {"order_id": "O-2001", "business_date": "2026-09-15", "region_code": "city_sh_huangpu", "amount": 300.0},
    {"order_id": "O-2002", "business_date": "2026-09-15", "region_code": "city_sh_pudong", "amount": 500.0},
    {"order_id": "O-2003", "business_date": "2026-09-15", "region_code": "city_bj_chaoyang", "amount": 700.0},
    {"order_id": "O-2004", "business_date": "2026-09-15", "region_code": "city_bj_haidian", "amount": 900.0},
    {"order_id": "O-2005", "business_date": "2026-09-15", "region_code": "prov_shanghai", "amount": 400.0},
    {"order_id": "O-2006", "business_date": "2026-09-15", "region_code": "prov_beijing", "amount": 900.0},
    {"order_id": "O-3001", "business_date": "2026-09-16", "region_code": "city_sh_huangpu", "amount": 300.0},
    {"order_id": "O-3002", "business_date": "2026-09-16", "region_code": "city_sh_pudong", "amount": 500.0},
    {"order_id": "O-3003", "business_date": "2026-09-16", "region_code": "city_bj_chaoyang", "amount": 700.0},
    {"order_id": "O-3004", "business_date": "2026-09-16", "region_code": "city_bj_haidian", "amount": 900.0},
    {"order_id": "O-3005", "business_date": "2026-09-16", "region_code": "prov_shanghai", "amount": 400.0},
    {"order_id": "O-3006", "business_date": "2026-09-16", "region_code": "prov_beijing", "amount": 900.0},
]

# 来源名 -> 维度表（立方体与校验服务统一从这里取映射，禁止再硬编码）
DIMENSION_SOURCES: dict[str, list[dict]] = {
    "legacy_dim_region": LEGACY_DIM_REGION,
    "province_dim_region": PROVINCE_DIM_REGION,
    "legacy_dim_channel": LEGACY_DIM_CHANNEL,
}

# 场景关键业务日
BEFORE_CONFLICT_DATE = "2026-09-14"
CONFLICT_DATE = "2026-09-15"
AFTER_CONFLICT_DATE = "2026-09-16"
