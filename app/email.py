"""Outgoing email (magic links, invitations) through Resend. Without RESEND_API_KEY the message
is written to the log instead, which is how development and tests read the link."""

import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)
RESEND_URL = "https://api.resend.com/emails"


class EmailError(RuntimeError):
    pass


def send(to: str, subject: str, text: str, html: str) -> None:
    s = get_settings()
    if not s.resend_api_key:
        log.warning("email (not sent: no RESEND_API_KEY) to=%s subject=%r\n%s", to, subject, text)
        return
    try:
        r = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            json={"from": s.email_from, "to": [to], "subject": subject, "text": text, "html": html},
            timeout=15,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise EmailError(f"Couldn't send the email: {e}") from e
