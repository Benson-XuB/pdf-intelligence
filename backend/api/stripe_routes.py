"""Stripe integration: Webhooks and Billing Portal."""

from __future__ import annotations

import json
import logging

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.auth.database import (
    cancel_subscription,
    get_user_by_stripe_customer,
    log_usage,
    update_user_tier,
)
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stripe", tags=["stripe"])


def _stripe_configured() -> bool:
    return bool(settings.stripe_secret_key)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events.

    Configure in Stripe Dashboard → Webhooks → Add endpoint:
    https://your-domain.com/api/stripe/webhook

    Events handled:
    - checkout.session.completed → apply tier upgrade
    - customer.subscription.deleted → downgrade to free
    """
    if not _stripe_configured():
        return JSONResponse({"error": "Stripe not configured"}, status_code=400)

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    stripe.api_key = settings.stripe_secret_key

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    except stripe.error.SignatureVerificationError:
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    event_type = event["type"]
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        user_id = int(metadata.get("user_id", 0))
        tier = metadata.get("tier", "pro")
        subscription_id = session.get("subscription", "")

        if user_id and subscription_id:
            update_user_tier(user_id, tier, stripe_subscription_id=subscription_id)
            log_usage(user_id, f"stripe_upgrade_to_{tier}")
            logger.info("User %d upgraded to %s (sub %s)", user_id, tier, subscription_id)

    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer", "")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            cancel_subscription(user["id"])
            log_usage(user["id"], "subscription_cancelled")
            logger.info("User %d subscription cancelled", user["id"])

    return {"status": "ok"}


@router.post("/portal")
async def create_portal_session(request: Request):
    """Create a Stripe Billing Portal session to manage subscription/billing."""
    if not _stripe_configured():
        raise HTTPException(400, "Stripe not configured. Set STRIPE_SECRET_KEY in .env")

    user = request.state.user
    if not user:
        raise HTTPException(401, "Not authenticated")

    customer_id = user.get("stripe_customer_id", "")
    if not customer_id:
        raise HTTPException(400, "No Stripe customer. Purchase a plan first via Upgrade.")

    stripe.api_key = settings.stripe_secret_key

    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme or "https")
    host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", "localhost"))
    base = f"{scheme}://{host}"

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base}/ui/index.html",
    )

    return {"url": session.url}
