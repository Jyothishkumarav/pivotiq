"""Local, in-process queue implementation (stdlib `queue.Queue`).

Drop-in replacement target for later: a `RabbitMqQueue` or `KafkaQueue` class
implementing the same `MessageQueue` interface, swapped in at composition
time (see `app/main.py`) via a single factory function/config flag.
"""

import queue
from typing import Any

from app.queue.base import MessageQueue


class InMemoryQueue(MessageQueue):
    def __init__(self, max_size: int = 1000) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_size)

    def publish(self, message: dict[str, Any]) -> None:
        self._queue.put(message, block=True)

    def consume(self, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            return self._queue.get(block=True, timeout=timeout)
        except queue.Empty:
            return None

    def size(self) -> int:
        return self._queue.qsize()
