"""立方体按已校验维度归属取数的接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.services.cube_dimension_query import aggregate_by_validated_attribution

router = APIRouter(prefix="/api/cube_dimension_query", tags=["多维立方体"])


@router.get("/aggregate")
def validated_aggregate(
    dim_code: str = Query("DIM-REGION", description="维度编号"),
    level: str = Query(..., description="请求层级，如 province / city"),
    biz_date: str = Query(..., description="业务日，格式 YYYY-MM-DD"),
    source: str | None = Query(None, description="可选：显式指定采纳的来源"),
) -> dict[str, Any]:
    """立方体只按维度归属数据集中的 ACTIVE 归属取数，并回附来源、粒度与逐笔落点。"""
    return aggregate_by_validated_attribution(dim_code, level, biz_date, source)
