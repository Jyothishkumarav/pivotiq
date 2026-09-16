"""Persistence abstraction for notification records/status.

Swappable behind this interface for a real database later (Mongo/Postgres);
today's `InMemoryNotificationStore` is enough for a single-process deployment.
"""

from abc import ABC, abstractmethod

from app.models.notification import (
    ChannelResult,
    NotificationChannel,
    NotificationRecord,
    OverallStatus,
)


class NotificationStore(ABC):
    @abstractmethod
    def create(self, record: NotificationRecord) -> None: ...

    @abstractmethod
    def get(self, notf_req_id: str) -> NotificationRecord | None: ...

    @abstractmethod
    def update_overall_status(self, notf_req_id: str, status: OverallStatus) -> None: ...

    @abstractmethod
    def update_channel_result(self, notf_req_id: str, result: ChannelResult) -> None: ...

    @abstractmethod
    def recompute_overall_status(self, notf_req_id: str) -> OverallStatus | None:
        """Derive and persist the overall status from the current per-channel results."""
