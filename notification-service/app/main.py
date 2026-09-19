"""Notification Hub — a standalone service any external system can call to
send a notification over telegram / normal (SMS) / whatsapp / email / RCS.

Composition root: builds the queue, store, channel registry, service and
background subscriber, and wires them onto `app.state` for the routes to use.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.channels.registry import ChannelRegistry
from app.config import get_settings
from app.logging_config import configure_logging
from app.queue.in_memory_queue import InMemoryQueue
from app.services.notification_service import NotificationService
from app.store.in_memory_store import InMemoryNotificationStore
from app.worker.processor import NotificationProcessor
from app.worker.subscriber import NotificationSubscriber

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    message_queue = InMemoryQueue(max_size=settings.queue_max_size)
    store = InMemoryNotificationStore()
    registry = ChannelRegistry(settings)
    processor = NotificationProcessor(store=store, registry=registry)
    subscriber = NotificationSubscriber(
        message_queue=message_queue,
        processor=processor,
        max_workers=settings.worker_thread_pool_size,
    )

    app.state.notification_service = NotificationService(message_queue=message_queue, store=store)
    app.state.subscriber = subscriber

    subscriber.start()
    logger.info("notification hub started on port %s", settings.port)
    try:
        yield
    finally:
        subscriber.stop()


app = FastAPI(title="Notification Hub", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
