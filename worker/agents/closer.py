"""Closer agent — the Deal-Room money action (Stripe).

On the call, after a human approves the close, the Closer creates a hosted
Stripe Checkout link (a deposit to confirm the meeting / a one-off charge),
posts it in the chat, and later checks payment status (the Vercel webhook
flips the DynamoDB record to paid; this is the polling fallback).

Test mode only for the hackathon (sk_test_…). This is the "Best use of Stripe"
path: a real, polished money flow the agent triggers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import stripe

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL", "https://dialogbrain.com/?paid=1")
CANCEL_URL = os.environ.get("STRIPE_CANCEL_URL", "https://dialogbrain.com/?canceled=1")


@dataclass
class Checkout:
    id: str
    url: str


class Closer:
    def create_checkout(self, amount_cents: int, description: str, *, currency: str = "usd") -> Checkout:
        sess = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": description},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            success_url=SUCCESS_URL,
            cancel_url=CANCEL_URL,
        )
        return Checkout(id=sess.id, url=sess.url)

    def status(self, session_id: str) -> str:
        """Returns 'paid' | 'unpaid' | 'no_payment_required'."""
        return stripe.checkout.Session.retrieve(session_id).payment_status
