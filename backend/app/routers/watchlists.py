from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.dependencies import get_current_user, with_fyers_context
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistItemIn,
    WatchlistItemOut,
    WatchlistOut,
    WatchlistRename,
    WatchlistReorder,
)
from app.services import market_data, support_levels

router = APIRouter(prefix="/watchlists", tags=["watchlists"], dependencies=[Depends(with_fyers_context)])


def _enrich_item(raw_item: dict) -> WatchlistItemOut:
    symbol = raw_item["symbol"]
    quote = market_data.get_quote(symbol)
    if quote is None:
        return WatchlistItemOut(symbol=symbol, exchange=raw_item["exchange"], addedAt=raw_item["addedAt"])

    nearest = support_levels.nearest_support_below(symbol, quote.ltp)
    below_all = nearest is None
    distance = None
    if nearest is not None and quote.ltp > 0:
        distance = round(((quote.ltp - nearest) / quote.ltp) * 100, 2)

    return WatchlistItemOut(
        symbol=symbol,
        exchange=raw_item["exchange"],
        addedAt=raw_item["addedAt"],
        ltp=quote.ltp,
        changePercent=quote.changePercent,
        nearestSupport=nearest,
        distanceToSupportPercent=distance,
        belowAllSupports=below_all,
    )


def _sort_items(items: list[WatchlistItemOut], preference: str) -> list[WatchlistItemOut]:
    if preference == "alphabetical":
        return sorted(items, key=lambda i: i.symbol)
    if preference == "dayChange":
        return sorted(items, key=lambda i: (i.changePercent is None, -(i.changePercent or 0)))
    # default: proximity to support, ascending distance; unresolved/below-all sort last
    with_support = [i for i in items if not i.belowAllSupports]
    without_support = [i for i in items if i.belowAllSupports]
    with_support.sort(key=lambda i: i.distanceToSupportPercent if i.distanceToSupportPercent is not None else float("inf"))
    return with_support + without_support


def _to_out(doc: dict, sorted_items: list[WatchlistItemOut]) -> WatchlistOut:
    return WatchlistOut(
        id=str(doc["_id"]),
        userId=str(doc["userId"]),
        name=doc["name"],
        sortPreference=doc.get("sortPreference", "proximity"),
        createdAt=doc["createdAt"],
        updatedAt=doc["updatedAt"],
        items=sorted_items,
    )


async def _get_owned_watchlist(watchlist_id: str, user_id: ObjectId) -> dict:
    db = get_db()
    try:
        oid = ObjectId(watchlist_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid watchlist id") from exc
    doc = await db.watchlists.find_one({"_id": oid, "userId": user_id})
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found")
    return doc


@router.get("", response_model=list[WatchlistOut])
async def list_watchlists(current_user: dict = Depends(get_current_user)) -> list[WatchlistOut]:
    db = get_db()
    cursor = db.watchlists.find({"userId": current_user["_id"]}).sort("createdAt", 1)
    result = []
    async for doc in cursor:
        enriched = [_enrich_item(i) for i in doc.get("items", [])]
        sorted_items = _sort_items(enriched, doc.get("sortPreference", "proximity"))
        result.append(_to_out(doc, sorted_items))
    return result


@router.post("", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def create_watchlist(payload: WatchlistCreate, current_user: dict = Depends(get_current_user)) -> WatchlistOut:
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "userId": current_user["_id"],
        "name": payload.name,
        "sortPreference": "proximity",
        "items": [],
        "createdAt": now,
        "updatedAt": now,
    }
    result = await db.watchlists.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _to_out(doc, [])


@router.put("/{watchlist_id}", response_model=WatchlistOut)
async def rename_watchlist(watchlist_id: str, payload: WatchlistRename, current_user: dict = Depends(get_current_user)) -> WatchlistOut:
    db = get_db()
    doc = await _get_owned_watchlist(watchlist_id, current_user["_id"])
    now = datetime.now(timezone.utc)
    await db.watchlists.update_one({"_id": doc["_id"]}, {"$set": {"name": payload.name, "updatedAt": now}})
    doc["name"] = payload.name
    doc["updatedAt"] = now
    enriched = [_enrich_item(i) for i in doc.get("items", [])]
    return _to_out(doc, _sort_items(enriched, doc.get("sortPreference", "proximity")))


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(watchlist_id: str, current_user: dict = Depends(get_current_user)) -> None:
    db = get_db()
    doc = await _get_owned_watchlist(watchlist_id, current_user["_id"])
    await db.watchlists.delete_one({"_id": doc["_id"]})


@router.post("/{watchlist_id}/items", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED)
async def add_item(watchlist_id: str, payload: WatchlistItemIn, current_user: dict = Depends(get_current_user)) -> WatchlistOut:
    if not market_data.symbol_exists(payload.symbol):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found")

    db = get_db()
    doc = await _get_owned_watchlist(watchlist_id, current_user["_id"])
    symbol = payload.symbol.upper()
    if any(i["symbol"] == symbol for i in doc.get("items", [])):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Symbol already in watchlist")

    now = datetime.now(timezone.utc)
    new_item = {"symbol": symbol, "exchange": payload.exchange, "addedAt": now}
    await db.watchlists.update_one(
        {"_id": doc["_id"]}, {"$push": {"items": new_item}, "$set": {"updatedAt": now}}
    )
    doc["items"] = doc.get("items", []) + [new_item]
    enriched = [_enrich_item(i) for i in doc["items"]]
    return _to_out(doc, _sort_items(enriched, doc.get("sortPreference", "proximity")))


@router.delete("/{watchlist_id}/items/{symbol}", response_model=WatchlistOut)
async def remove_item(watchlist_id: str, symbol: str, current_user: dict = Depends(get_current_user)) -> WatchlistOut:
    db = get_db()
    doc = await _get_owned_watchlist(watchlist_id, current_user["_id"])
    now = datetime.now(timezone.utc)
    await db.watchlists.update_one(
        {"_id": doc["_id"]}, {"$pull": {"items": {"symbol": symbol.upper()}}, "$set": {"updatedAt": now}}
    )
    doc["items"] = [i for i in doc.get("items", []) if i["symbol"] != symbol.upper()]
    enriched = [_enrich_item(i) for i in doc["items"]]
    return _to_out(doc, _sort_items(enriched, doc.get("sortPreference", "proximity")))


@router.put("/{watchlist_id}/reorder", response_model=WatchlistOut)
async def reorder_items(watchlist_id: str, payload: WatchlistReorder, current_user: dict = Depends(get_current_user)) -> WatchlistOut:
    db = get_db()
    doc = await _get_owned_watchlist(watchlist_id, current_user["_id"])
    by_symbol = {i["symbol"]: i for i in doc.get("items", [])}
    if set(payload.symbols) != set(by_symbol.keys()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Symbol list must match existing items")

    reordered = [by_symbol[s] for s in payload.symbols]
    now = datetime.now(timezone.utc)
    await db.watchlists.update_one(
        {"_id": doc["_id"]}, {"$set": {"items": reordered, "sortPreference": "custom", "updatedAt": now}}
    )
    doc["items"] = reordered
    doc["sortPreference"] = "custom"
    enriched = [_enrich_item(i) for i in reordered]
    return _to_out(doc, _sort_items(enriched, "custom"))


@router.put("/{watchlist_id}/sort-preference", response_model=WatchlistOut)
async def set_sort_preference(watchlist_id: str, preference: str, current_user: dict = Depends(get_current_user)) -> WatchlistOut:
    if preference not in ("proximity", "alphabetical", "dayChange", "custom"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sort preference")

    db = get_db()
    doc = await _get_owned_watchlist(watchlist_id, current_user["_id"])
    now = datetime.now(timezone.utc)
    await db.watchlists.update_one({"_id": doc["_id"]}, {"$set": {"sortPreference": preference, "updatedAt": now}})
    doc["sortPreference"] = preference
    enriched = [_enrich_item(i) for i in doc.get("items", [])]
    return _to_out(doc, _sort_items(enriched, preference))
