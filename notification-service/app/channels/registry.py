"""Maps each `NotificationChannel` to its sender implementation.

The single place to touch when adding/replacing a channel provider.
"""

from app.channels.base import NotificationSender
from app.channels.email_channel import EmailSender
from app.channels.rcs_channel import RcsSender
from app.channels.sms_channel import SmsSender
from app.channels.telegram_channel import TelegramSender
from app.channels.whatsapp_channel import WhatsAppSender
from app.config import Settings
from app.models.notification import NotificationChannel


class ChannelRegistry:
    def __init__(self, settings: Settings) -> None:
        self._senders: dict[NotificationChannel, NotificationSender] = {
            NotificationChannel.telegram: TelegramSender(
                bot_token=settings.telegram_bot_token,
                api_base_url=settings.telegram_api_base_url,
            ),
            NotificationChannel.email: EmailSender(
                smtp_host=settings.smtp_host,
                smtp_port=settings.smtp_port,
                smtp_username=settings.smtp_username,
                smtp_password=settings.smtp_password,
                from_address=settings.smtp_from_address,
            ),
            NotificationChannel.whatsapp: WhatsAppSender(),
            NotificationChannel.normal: SmsSender(),
            NotificationChannel.rcs: RcsSender(),
        }

    def get(self, channel: NotificationChannel) -> NotificationSender:
        return self._senders[channel]
