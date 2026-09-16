"""Email channel.

Sends via SMTP when `smtp_host`/`smtp_username` are configured; otherwise runs
in simulated mode (logs the outgoing email and reports success) so the
pipeline is fully exercisable before real SMTP credentials exist.
"""

import logging
import smtplib
import uuid
from email.message import EmailMessage

from app.channels.base import NotificationSender, SendResult
from app.models.notification import Recipient

logger = logging.getLogger(__name__)


class EmailSender(NotificationSender):
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        from_address: str,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_username = smtp_username
        self._smtp_password = smtp_password
        self._from_address = from_address or smtp_username

    def send(self, recipient: Recipient, title: str, data: str, reference: str) -> SendResult:
        if not recipient.email:
            return SendResult(success=False, error="recipient.email is required for the email channel")

        if not self._smtp_host:
            logger.info("[email:simulated] to=%s subject=%s ref=%s body=%s", recipient.email, title, reference, data)
            return SendResult(success=True, provider_message_id=f"simulated-{uuid.uuid4()}")

        message = EmailMessage()
        message["Subject"] = title
        message["From"] = self._from_address
        message["To"] = recipient.email
        message.set_content(f"{data}\n\nref: {reference}")

        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if self._smtp_username:
                    smtp.login(self._smtp_username, self._smtp_password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.exception("email send failed for ref=%s", reference)
            return SendResult(success=False, error=str(exc))

        return SendResult(success=True, provider_message_id=str(uuid.uuid4()))
