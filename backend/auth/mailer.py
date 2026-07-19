"""SendGrid magic-link email sender."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from backend.config import settings

logger = logging.getLogger(__name__)

_FROM_EMAIL = "noreply@pdfintelligence.io"
_FROM_NAME = "PDF Intelligence"
_BASE_URL = settings.base_url.rstrip("/")


def send_magic_link(to_email: str, token: str, display_name: str = "") -> bool:
    """Send a magic-link verification email via SendGrid.

    Returns True on success, False on failure (logged).
    """
    if not settings.sendgrid_api_key:
        logger.warning("SendGrid not configured — skipping magic link for %s", to_email)
        return False

    verify_url = f"{_BASE_URL}/api/auth/verify?{urlencode({'token': token})}"
    greet = f"Hi{(' ' + display_name) if display_name else ''},"

    html = f"""<!DOCTYPE html>
<html><body style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:2rem;">
  <h2 style="color:#1a1a2e;">PDF Intelligence</h2>
  <p>{greet}</p>
  <p>Click the button below to sign in. This link expires in <strong>15 minutes</strong> and can only be used once.</p>
  <p style="margin:2rem 0;">
    <a href="{verify_url}" style="background:#2dd4a8;color:#0d1117;padding:0.75rem 1.5rem;border-radius:6px;text-decoration:none;font-weight:600;">Sign in to PDF Intelligence</a>
  </p>
  <p style="color:#6b7280;font-size:0.85rem;">
    If you didn't request this, you can safely ignore this email.<br>
    Link: <code style="word-break:break-all;">{verify_url}</code>
  </p>
</body></html>"""

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        message = Mail(
            from_email=(_FROM_EMAIL, _FROM_NAME),
            to_emails=to_email,
            subject="Sign in to PDF Intelligence",
            html_content=html,
        )
        response = sg.send(message)
        ok = 200 <= response.status_code < 300
        if ok:
            logger.info("Magic link sent to %s", to_email)
        else:
            logger.error("SendGrid returned %s: %s", response.status_code, response.body)
        return ok
    except Exception as exc:
        logger.exception("SendGrid send failed for %s", to_email)
        return False
