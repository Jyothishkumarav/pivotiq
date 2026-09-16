from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.alert import AlertCreate, AlertOut, AlertUpdate
from app.services import market_data, support_levels

router = APIRouter(prefix="/alerts", tags=["alerts"], dependencies=[Depends(get_current_user)])


def _find_level_value(symbol: str, method: str, level_key: str) -> float:
    """Resolve a specific level's current value (e.g. classic/s1, swingLow/zone-0)."""
    levels = support_levels.compute_support_levels(symbol)
    if levels is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")

    if method == "swingLow":
        try:
            idx = int(level_key.removeprefix("zone-"))
            return levels.swingLowZones[idx].level
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid swing-low zone key") from exc

    pivot_set = next((p for p in levels.pivotMethods if p.method == method), None)
    if pivot_set is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown method")
    value = getattr(pivot_set, level_key, None)
    if value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown level key for this method")
    return value


def _to_out(doc: dict, current_price: float | None = None) -> AlertOut:
    distance = None
    if current_price is not None and current_price > 0:
        distance = round(((current_price - doc["levelValueAtCreation"]) / current_price) * 100, 2)
    return AlertOut(
        id=str(doc["_id"]),
        userId=str(doc["userId"]),
        symbol=doc["symbol"],
        method=doc["method"],
        levelKey=doc["levelKey"],
        levelValueAtCreation=doc["levelValueAtCreation"],
        thresholdType=doc["thresholdType"],
        thresholdValue=doc["thresholdValue"],
        channels=doc["channels"],
        isActive=doc["isActive"],
        lastTriggeredAt=doc.get("lastTriggeredAt"),
        createdAt=doc["createdAt"],
        currentPrice=current_price,
        currentDistancePercent=distance,
    )


@router.get("", response_model=list[AlertOut])
async def list_alerts(current_user: dict = Depends(get_current_user)) -> list[AlertOut]:
    db = get_db()
    cursor = db.alerts.find({"userId": current_user["_id"]}).sort("createdAt", -1)
    result = []
    async for doc in cursor:
        quote = market_data.get_quote(doc["symbol"])
        result.append(_to_out(doc, quote.ltp if quote else None))
    return result


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(payload: AlertCreate, current_user: dict = Depends(get_current_user)) -> AlertOut:
    if not market_data.symbol_exists(payload.symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")

    level_value = _find_level_value(payload.symbol, payload.method, payload.levelKey)

    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "userId": current_user["_id"],
        "symbol": payload.symbol.upper(),
        "method": payload.method,
        "levelKey": payload.levelKey,
        "levelValueAtCreation": level_value,
        "thresholdType": payload.thresholdType,
        "thresholdValue": payload.thresholdValue,
        "channels": payload.channels,
        "isActive": True,
        "lastTriggeredAt": None,
        "createdAt": now,
    }
    result = await db.alerts.insert_one(doc)
    doc["_id"] = result.inserted_id
    quote = market_data.get_quote(payload.symbol)
    return _to_out(doc, quote.ltp if quote else None)


async def _get_owned_alert(alert_id: str, user_id: ObjectId) -> dict:
    db = get_db()
    try:
        oid = ObjectId(alert_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid alert id") from exc
    doc = await db.alerts.find_one({"_id": oid, "userId": user_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return doc


@router.put("/{alert_id}", response_model=AlertOut)
async def update_alert(alert_id: str, payload: AlertUpdate, current_user: dict = Depends(get_current_user)) -> AlertOut:
    db = get_db()
    doc = await _get_owned_alert(alert_id, current_user["_id"])
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if updates:
        await db.alerts.update_one({"_id": doc["_id"]}, {"$set": updates})
        doc.update(updates)
    quote = market_data.get_quote(doc["symbol"])
    return _to_out(doc, quote.ltp if quote else None)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert_id: str, current_user: dict = Depends(get_current_user)) -> None:
    db = get_db()
    doc = await _get_owned_alert(alert_id, current_user["_id"])
    await db.alerts.delete_one({"_id": doc["_id"]})
