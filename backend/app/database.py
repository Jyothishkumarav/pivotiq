from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(get_settings().mongo_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        client = get_client()
        try:
            _db = client.get_default_database()
        except Exception:
            _db = client[get_settings().mongo_db_name]
    return _db


async def ensure_indexes() -> None:
    db = get_db()
    await db.users.create_index("googleId", unique=True, sparse=True)
    await db.users.create_index("email", unique=True)
    await db.watchlists.create_index("userId")
    await db.alerts.create_index([("userId", 1), ("symbol", 1), ("isActive", 1)])
    await db.paper_trades.create_index([("userId", 1), ("symbol", 1)])
    await db.paper_trades.create_index([("userId", 1), ("executedAt", -1)])
    await db.stock_symbols.create_index("symbol", unique=True)
    await db.stock_symbols.create_index("exchange")
    await db.stock_fundamentals.create_index("symbol", unique=True)
    await db.stock_details.create_index("symbol", unique=True)
    await db.stock_details.create_index("updatedAt")
    await db.fyers_credentials.create_index("userId", unique=True)
    try:
        await db.intraday_triggers.drop_index("symbol_1_date_1")
    except Exception:
        pass
    await db.intraday_triggers.create_index([("symbol", 1), ("date", 1), ("strategy", 1)], unique=True)


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
