from fastapi import APIRouter

from backend.tools.business_info import get_business_info

router = APIRouter(tags=["business"])


@router.get("/business-info")
async def business_info_endpoint():
    return get_business_info()
