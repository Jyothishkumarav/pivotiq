# PivotIQ — Architecture & Flow Documentation

This document describes the full system architecture of PivotIQ: system context,
components, request/data flow, and key sequence diagrams — including the
standalone notification service and its Telegram integration.

---

## 1. System context

```mermaid
flowchart TB
    subgraph Clients
        Mobile[Expo app — iOS / Android]
        Web[Expo web build]
    end

    subgraph PivotIQ["PivotIQ platform"]
        FE[Frontend<br/>Expo Router + React Query + Zustand]
        BE[Backend<br/>FastAPI + Motor/MongoDB]
        NS[Notification Service<br/>FastAPI, standalone]
        DB[(MongoDB)]
    end

    subgraph External["External systems"]
        Fyers[Fyers Broker API<br/>live quotes, holdings, positions]
        Yahoo[Yahoo Finance<br/>mock/EOD market data]
        Google[Google Sign-In]
        Telegram[Telegram Bot API]
        SMTP[SMTP provider]
        Other[Any other external caller]
    end

    Mobile --> FE
    Web --> FE
    FE -->|REST + JWT| BE
    BE --> DB
    BE -->|live quotes / holdings| Fyers
    BE -->|search / fundamentals / EOD candles| Yahoo
    BE -->|ID token verify| Google
    BE -->|POST /api/v1/notifications| NS
    Other -->|POST /api/v1/notifications| NS
    NS -->|sendMessage| Telegram
    NS -.->|SMTP or simulated| SMTP
```

**Key point:** the notification service has **no import dependency** on
`backend/` — it's called purely over HTTP, so any current or future system
(not just PivotIQ's own backend) can send notifications through it.

---

## 2. Repository / deployment layout

```
PivotIQ/
├── backend/                FastAPI API (Python 3.12, Motor/MongoDB)
├── frontend/                Expo React Native app (iOS / Android / Web)
├── notification-service/    Standalone FastAPI notification hub
├── docker-compose.yml       mongo + backend + frontend-web + notification-service
└── .env / .env.example
```

Each of the three services has its **own** `Dockerfile`, `requirements.txt`
(or `package.json`), and `.venv` — they can be built, deployed, and scaled
independently.

---

## 3. Backend component diagram

```mermaid
flowchart TB
    subgraph API["app/routers"]
        AUTH[auth.py — login, dev-login, refresh]
        STOCKS[stocks.py — search, quote, details,<br/>support-levels, intraday-snapshot(s)]
        WL[watchlists.py — CRUD, items]
        ALERTS[alerts.py — create/list alerts]
        TRADE[trading.py — place trade, positions, summary]
        SET[settings.py]
        FYERS_R[fyers.py — connect / status / disconnect]
    end

    subgraph SVC["app/services"]
        MD[market_data.py<br/>Yahoo-backed mock provider]
        SL[support_levels.py<br/>Classic/Fib/Camarilla/Woodie pivots]
        MC[market_context.py<br/>ContextVar-based Fyers token]
        FC[fyers_client.py<br/>Fyers REST wrapper]
        IA[intraday_analysis.py<br/>ORB + VWAP + trade setup]
        TS[trading_service.py<br/>paper-trading engine]
        NC[notification_client.py<br/>fire-and-forget alerts]
    end

    subgraph DATA["app/database + Mongo"]
        DB[(MongoDB<br/>users, watchlists, alerts,<br/>paper_trades, fyers_tokens)]
    end

    subgraph DEP["app/dependencies + security"]
        DEPS[get_current_user<br/>with_fyers_context]
        SEC[security.py — JWT encode/decode]
    end

    AUTH --> SEC
    AUTH --> DB
    STOCKS --> DEPS --> MC
    STOCKS --> MD
    STOCKS --> SL
    STOCKS --> IA --> FC
    STOCKS -->|on triggeredAt| NC -->|HTTP POST| NSExt[notification-service]
    WL --> DB
    ALERTS --> DB
    TRADE --> TS --> DB
    TRADE --> MD
    FYERS_R --> FC
    FYERS_R --> DB
```

### Backend layers
| Layer | Responsibility |
|---|---|
| `routers/` | Thin HTTP layer — request validation, auth dependency wiring, delegates to services |
| `services/` | Business logic: market data, support levels, intraday ORB analysis, paper-trading engine, outbound notification calls |
| `schemas/` | Pydantic request/response models (one per domain) |
| `database.py` | Motor (async MongoDB) client + index setup |
| `security.py` | JWT issue/verify (access + refresh tokens) |
| `dependencies.py` | `get_current_user` (JWT → user doc), `with_fyers_context` (stashes Fyers token in a `ContextVar` for sync market-data code) |

---

## 4. Frontend component diagram

```mermaid
flowchart TB
    subgraph Routes["app/ (Expo Router, file-based)"]
        Login[login.tsx]
        Tabs["(tabs)/ — search, watchlists, portfolio, alerts"]
        WLDetail[watchlist/[id].tsx]
        StockDetail[stock/[symbol].tsx]
        NewAlert[alert/new.tsx]
    end

    subgraph State["State management"]
        RQ[React Query<br/>server state, caching, polling]
        Zustand[authStore.ts<br/>Zustand — JWT/session]
    end

    subgraph API["src/api/ (typed HTTP client)"]
        Client[client.ts<br/>axios + auto token refresh]
        AuthApi[auth.ts]
        StocksApi[stocks.ts]
        WLApi[watchlists.ts]
        AlertsApi[alerts.ts]
        TradingApi[trading.ts]
        FyersApi[fyers.ts]
    end

    subgraph UI["src/components + ui/"]
        Prims[Button, Card, Input, Badge, Text, Screen]
        Domain[StockRow, CandleChart, TradePanel,<br/>SupportLevelCard, FyersLivePanel]
    end

    Routes --> RQ
    Routes --> UI
    RQ --> API
    Zustand --> Client
    API --> Client
    Client -->|Bearer JWT| Backend[(Backend API)]
```

---

## 5. End-to-end sequence — user login → watchlist → live intraday polling → alert

```mermaid
sequenceDiagram
    participant U as User (app)
    participant FE as Frontend
    participant BE as Backend
    participant DB as MongoDB
    participant FY as Fyers API
    participant NS as Notification Service
    participant TG as Telegram

    U->>FE: Open app
    FE->>BE: POST /auth/dev-login (or Google ID token)
    BE->>DB: find/create user
    BE-->>FE: access + refresh JWT
    FE->>Zustand: persist session

    U->>FE: Open Watchlist
    FE->>BE: GET /watchlists/{id}
    BE->>DB: fetch watchlist + items
    BE-->>FE: watchlist payload

    loop every poll interval (frontend timer)
        FE->>BE: POST /stocks/intraday-snapshots {symbols}
        BE->>BE: with_fyers_context → fetch user's Fyers token
        BE->>FY: GET history (5m + 3m candles)
        FY-->>BE: candles
        BE->>BE: intraday_analysis.compute_snapshot()<br/>ORB high/low, VWAP, trend, TradeSetup
        alt setup just triggered (breakout confirmed)
            BE->>NS: POST /api/v1/notifications (fire-and-forget)
            NS-->>BE: 202 Accepted {notf_req_id}
        end
        BE-->>FE: snapshots map {symbol → IntradaySnapshot}
        FE->>U: render Entry/SL/Status/Δ columns
    end

    Note over NS,TG: async, decoupled from the backend's request
    NS->>NS: log + persist record (PENDING) + enqueue
    NS->>NS: subscriber picks up message → thread pool
    NS->>TG: sendMessage (HTML formatted)
    TG-->>NS: message_id
    NS->>NS: update channel status → SENT

    U->>FE: Click stock row
    FE->>FE: window.open(/stock/:symbol, "_blank") [web]
```

---

## 6. Notification Service — component diagram

```mermaid
flowchart TB
    subgraph External["Callers"]
        BE[PivotIQ backend]
        Ext[Any external system]
    end

    subgraph API["app/api"]
        R[routes.py<br/>POST /notifications · GET /notifications/:id]
    end

    subgraph SVC["app/services"]
        NSV[notification_service.py<br/>validate → log → persist → enqueue]
    end

    subgraph STORE["app/store"]
        SB["base.py (interface)"]
        SI["in_memory_store.py<br/>keyed by notf_req_id"]
    end

    subgraph QUEUE["app/queue"]
        QB["base.py (interface)"]
        QI["in_memory_queue.py<br/>swap later: RabbitMQ / Kafka"]
    end

    subgraph WORKER["app/worker"]
        SUB[subscriber.py<br/>1 dispatcher thread]
        POOL[ThreadPoolExecutor]
        PROC[processor.py<br/>sends to every requested channel]
    end

    subgraph CHANNELS["app/channels (Strategy pattern)"]
        REG[registry.py]
        TG[telegram_channel.py — LIVE, HTML parse_mode]
        EM[email_channel.py — live if SMTP set, else simulated]
        SMS[sms_channel.py — simulated]
        WA[whatsapp_channel.py — simulated]
        RCS[rcs_channel.py — simulated]
    end

    BE --> R
    Ext --> R
    R --> NSV
    NSV -->|PENDING record| SI
    NSV -->|publish| QI
    SI -.implements.-> SB
    QI -.implements.-> QB

    QI --> SUB --> POOL --> PROC
    PROC --> REG --> TG & EM & SMS & WA & RCS
    PROC -->|update status per channel| SI
    R -->|GET status| SI
```

---

## 7. Notification Service — sequence (accept → process → deliver → status)

```mermaid
sequenceDiagram
    participant Caller as Caller (backend or external)
    participant API as FastAPI routes
    participant Svc as NotificationService
    participant Store as NotificationStore
    participant Queue as MessageQueue
    participant Sub as Subscriber (thread)
    participant Pool as ThreadPoolExecutor
    participant Proc as Processor
    participant TG as Telegram Bot API

    Caller->>API: POST /api/v1/notifications<br/>{channels, recipient, title, data, reference}
    API->>Svc: handle(request)
    Svc->>Svc: log request
    Svc->>Store: save record (status=PENDING per channel)
    Svc->>Queue: publish(notf_req_id)
    Svc-->>API: notf_req_id, status=ACCEPTED
    API-->>Caller: 202 Accepted {notf_req_id}

    loop background worker loop
        Sub->>Queue: consume()
        Sub->>Pool: submit(process, notf_req_id)
        Pool->>Proc: process(record)
        loop for each requested channel
            Proc->>TG: sendMessage (HTML: bold/code/emoji)
            TG-->>Proc: message_id / error
            Proc->>Store: update channel status (SENT / FAILED)
        end
        Proc->>Store: update overall_status<br/>(SENT / PARTIALLY_SENT / FAILED)
    end

    Caller->>API: GET /api/v1/notifications/{notf_req_id}
    API->>Store: fetch record
    API-->>Caller: overall_status + per-channel breakdown
```

---

## 8. Trade-setup-triggered alert — data model & payload

```mermaid
flowchart LR
    A[intraday_analysis.compute_snapshot] -->|TradeSetup.triggeredAt set| B[notification_client.notify_trade_setup_triggered]
    B --> C{dedup cache<br/>symbol+action+day}
    C -->|already notified today| D[skip]
    C -->|new trigger| E[Build HTML payload]
    E --> F[POST notification-service<br/>/api/v1/notifications]
```

**Payload shape:**
```json
{
  "channels": ["telegram"],
  "recipient": { "telegramChatId": "-1004440440854" },
  "title": "🟢 DATAPATTNS · BUY setup triggered",
  "data": "<b>BULLISH</b> setup on <b>DATAPATTNS</b>\n━━━━━━━━━━━━━━━\n💰 Price: <b>₹4,316.00</b>\n📍 Entry: <code>₹4,300.00</code>\n🛑 Stop-Loss: <code>₹4,250.00</code> (Δ ₹66.00 · 1.55% away)\n🏁 Target: <code>₹4,400.00</code>\n⚖️ Risk:Reward: <b>2.0</b>",
  "reference": "trigger-DATAPATTNS-2026-09-16",
  "metadata": { "source": "pivotiq-backend", "symbol": "DATAPATTNS", "action": "buy" }
}
```

---

## 9. Component & responsibility summary

| Service | Tech | Key modules | Responsibility |
|---|---|---|---|
| **Frontend** | Expo (React Native) + TypeScript | `app/` (routes), `src/api/`, `src/store/`, `src/components/` | Cross-platform UI (iOS/Android/Web), typed API client with auto token refresh, React Query for server state |
| **Backend** | FastAPI + Motor/MongoDB | `routers/`, `services/`, `schemas/` | Auth, market data, watchlists, alerts, paper-trading, Fyers integration, intraday ORB analysis, fires trigger notifications |
| **Notification Service** | FastAPI (standalone) | `api/`, `services/`, `store/`, `queue/`, `worker/`, `channels/` | Accepts any external notification request, queues it, processes via thread pool, delivers over Telegram (live)/Email/SMS/WhatsApp/RCS, tracks per-channel status |

## 10. Design principles applied

- **Separation of concerns**: routers (HTTP) → services (business logic) → data/external clients.
- **Strategy pattern**: notification channels all implement `NotificationSender`; adding a channel means one new file + a registry entry.
- **Interface-first swappability**: `MessageQueue` and `NotificationStore` are abstract interfaces — the in-memory implementations can be replaced by RabbitMQ/Kafka and Postgres/Mongo without touching callers.
- **Fire-and-forget integration**: the backend never blocks a user-facing request on the notification service being up; failures are logged, not raised.
- **Idempotency/dedup**: one trigger notification per symbol per trading day, preventing alert spam from repeated polling.
- **Independent deployability**: three services, three `Dockerfile`s, one `docker-compose.yml`, no cross-service imports.
