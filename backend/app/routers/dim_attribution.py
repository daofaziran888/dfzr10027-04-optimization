"""维度归属接口：按业务日输出维度归属数据集，并支持归属确认。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas import ActionResult
from app.services.dim_attribution import attribution_registry

router = APIRouter(prefix="/api/dim_attribution", tags=["维度归属"])


@router.get("/dataset")
def get_attribution_dataset(biz_date: str = Query(..., description="业务日，格式 YYYY-MM-DD")) -> dict[str, Any]:
    """计算前校验：返回该业务日的维度归属数据集（ACTIVE/READ_ONLY/INVALID 与冲突）。"""
    return attribution_registry.validate(biz_date)


@router.get("/registrations")
def list_registrations() -> dict[str, Any]:
    """返回当前维度登记台账（含确认状态）。"""
    return {"items": attribution_registry.list_registrations()}


@router.post("/{reg_id}/confirm")
def confirm_registration(reg_id: str) -> ActionResult:
    """确认一条归属登记；确认后下一次校验才可能成为 ACTIVE 归属。"""
    entry, message = attribution_registry.confirm(reg_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
