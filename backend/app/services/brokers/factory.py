from __future__ import annotations

from typing import Callable
from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.brokers.base import BaseBroker
from app.services.brokers.fyers_broker import FyersBroker
from app.services.brokers.paper_broker import PaperBroker
from app.services.market_context import get_active_fyers_token


# Registry for extensible broker providers
BROKER_REGISTRY: dict[str, str] = {
    "fyers": "Fyers Securities (API v3)",
    "paper": "PivotIQ Paper Trading (Simulated)",
}


async def get_broker(
    broker_name: str,
    user_id: ObjectId | str,
    db: AsyncIOMotorDatabase,
    access_token: str | None = None,
) -> BaseBroker:
    """Factory to instantiate the appropriate broker client.

    Easily onboard new brokers by adding an implementation of BaseBroker.
    """
    normalized_name = broker_name.strip().lower()

    if normalized_name == "fyers":
        token = access_token or await get_active_fyers_token(user_id)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fyers account is not connected or session expired. Please connect Fyers or select Paper Trading.",
            )
        return FyersBroker(access_token=token)

    if normalized_name == "paper":
        return PaperBroker(user_id=user_id, db=db)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported broker provider '{broker_name}'. Available providers: {list(BROKER_REGISTRY.keys())}",
    )
