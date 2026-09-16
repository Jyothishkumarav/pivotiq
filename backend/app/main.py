from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_client, ensure_indexes
from app.routers import alerts, auth, stocks, trading, watchlists
from app.routers import fyers as fyers_router
from app.routers import settings as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    yield
    await close_client()


app = FastAPI(title="PivotIQ API", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(watchlists.router)
app.include_router(alerts.router)
app.include_router(trading.router)
app.include_router(settings_router.router)
app.include_router(fyers_router.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
