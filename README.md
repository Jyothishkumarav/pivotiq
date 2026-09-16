# PivotIQ

Cross-platform (iOS / Android / Web) stock watchlist, support-level analysis and paper-trading platform, built from a single React Native codebase with a Python (FastAPI) backend.

Implements the requirements from `stock-watchlist-platform-spec.md`.

## What's in this MVP

| Area | Status |
|---|---|
| Google Sign-In + dev login | ✅ |
| Stock search, quote, fundamentals | ✅ (mocked provider, 20 NSE symbols) |
| Support/resistance levels (Classic, Fibonacci, Camarilla, Woodie pivots + swing-low zones) | ✅ |
| Watchlists (multi, CRUD, proximity-to-support sort, reorder) | ✅ |
| Alerts — creation & listing UI | ✅ |
| Alerts — evaluation worker & push delivery | ⏸️ deferred (per scope) |
| Paper trading (intraday + delivery, positions, portfolio summary) | ✅ |
| Docker deployment (backend + web frontend, MongoDB, Redis) | ✅ |

## Repo layout

```
PivotIQ/
├── backend/          FastAPI API (Python, MongoDB via Motor)
├── frontend/          Expo React Native app (iOS/Android/Web)
├── docker-compose.yml
└── .env.example
```

## Quick start (Docker)

```powershell
# from the repo root
copy .env.example .env
docker compose up --build
```

Then:

- API:        http://localhost:4000 (docs at /docs)
- Web app:    http://localhost:8081
- MongoDB:    mongodb://localhost:27017
- Redis:      redis://localhost:6379

## Quick start (local dev, no Docker)

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 4000
```

Requires a local MongoDB instance (or point `MONGO_URI` at Atlas).

### Frontend

```powershell
cd frontend
npm install
npm run web        # web
npm run ios        # ios simulator (macOS)
npm run android    # android emulator
```

## Auth

Google Sign-In is wired server-side (ID token verification via `google-auth`) but requires an OAuth client ID. Set `GOOGLE_CLIENT_ID` in `.env` to enable it. In dev, the login screen exposes a **"Continue as demo user"** button that hits `/auth/dev-login` and returns a valid JWT — use this to explore the app end-to-end without OAuth setup.

## Architecture notes

- **Backend**: FastAPI, modular by domain (`auth`, `stocks`, `watchlists`, `alerts`, `paper-trading`), async MongoDB access via Motor. The market-data provider sits behind a single swappable interface (`app/services/market_data.py`) — today backed by a static mock dataset, per the spec's guidance to keep the real vendor swappable without touching other modules.
- **Frontend**: Expo + Expo Router (file-based routing), React Query for server state, Zustand for auth state, a small typed design-token system for a consistent, professional dark UI across all three platforms.
- **Deployment**: backend and frontend are independent Docker images; frontend is exported to static web output and served via nginx. Mobile builds (iOS/Android) run from the same codebase via Expo/EAS outside of Docker.

## Coding standards

- Backend: Python 3.12, type-hinted throughout, Pydantic models for all request/response schemas, one router per domain, business logic kept in `services/`.
- Frontend: TypeScript strict mode, feature-first `src/` folders, a typed API client with automatic access-token refresh, reusable UI primitives (`Button`, `Card`, `Input`, `Badge`, `Text`, `Screen`) instead of ad-hoc styling.

## Deferred (not in this scope)

- Alert-evaluation background worker + push notification delivery (FCM / Web Push) — alert **creation and listing** is implemented; triggering/sending is out of scope per request.
- Candlestick charting with S/R overlay.
- Real-time WebSocket price streaming (uses 30s polling instead, per spec).
- EOD intraday square-off background job.

See `stock-watchlist-platform-spec.md` for the full product spec.
