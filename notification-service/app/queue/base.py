"""Queue abstraction.

Only `publish` / `consume` / `size` are exposed to the rest of the app, so the
backing implementation can move from the current in-process queue to
RabbitMQ, Kafka, SQS, etc. later without changing `NotificationService` or
`NotificationSubscriber`.
"""

from abc import ABC, abstractmethod
from typing import Any


class MessageQueue(ABC):
    @abstractmethod
    def publish(self, message: dict[str, Any]) -> None:
        """Enqueue a message for later processing. Must be safe to call from any thread."""

    @abstractmethod
    def consume(self, timeout: float | None = None) -> dict[str, Any] | None:
        """Block up to `timeout` seconds for the next message, or return None on timeout."""

    @abstractmethod
    def size(self) -> int:
        """Approximate number of messages currently queued."""
