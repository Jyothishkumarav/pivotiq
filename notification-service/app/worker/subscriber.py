"""Subscriber: a single dispatcher thread pulls messages off the queue and
hands each one to a worker thread from a bounded `ThreadPoolExecutor` — the
"assign a thread from a thread pool to process the message" requirement.

Using a blocking `consume(timeout=...)` poll (rather than a tight loop) keeps
CPU usage near zero while idle and lets `stop()` take effect within one
timeout window.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app.queue.base import MessageQueue
from app.worker.processor import NotificationProcessor

logger = logging.getLogger(__name__)

_POLL_TIMEOUT_SECONDS = 1.0


class NotificationSubscriber:
    def __init__(self, message_queue: MessageQueue, processor: NotificationProcessor, max_workers: int) -> None:
        self._queue = message_queue
        self._processor = processor
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="notif-worker")
        self._dispatcher_thread = threading.Thread(target=self._run, name="notif-subscriber", daemon=True)
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._dispatcher_thread.start()
        logger.info("notification subscriber started")

    def stop(self) -> None:
        self._stop_event.set()
        self._dispatcher_thread.join(timeout=_POLL_TIMEOUT_SECONDS * 2)
        self._executor.shutdown(wait=True)
        logger.info("notification subscriber stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            message = self._queue.consume(timeout=_POLL_TIMEOUT_SECONDS)
            if message is None:
                continue
            self._executor.submit(self._process_safely, message)

    def _process_safely(self, message: dict) -> None:
        try:
            self._processor.process(message)
        except Exception:  # noqa: BLE001 - a bad message must never kill a pool thread silently
            logger.exception("unhandled error processing message notf_req_id=%s", message.get("notf_req_id"))
