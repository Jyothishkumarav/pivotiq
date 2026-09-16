from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.services import market_data

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])


class DataSourceOut(BaseModel):
    mode: Literal["real", "mock"]


class DataSourceIn(BaseModel):
    mode: Literal["real", "mock"]


@router.get("/data-source", response_model=DataSourceOut)
async def get_data_source() -> DataSourceOut:
    return DataSourceOut(mode=market_data.get_mode())


@router.put("/data-source", response_model=DataSourceOut)
async def set_data_source(payload: DataSourceIn) -> DataSourceOut:
    market_data.set_mode(payload.mode)
    return DataSourceOut(mode=market_data.get_mode())
