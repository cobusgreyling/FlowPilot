"""Stripe connector — payments, customers, subscriptions, invoices."""

from __future__ import annotations

import logging
import os
from typing import Any

from .base import BaseConnector

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class StripeConnector(BaseConnector):
    """Interact with Stripe for payments and billing."""

    @property
    def name(self) -> str:
        return "stripe"

    def _api(self, method: str, path: str, data: dict = None) -> dict | None:
        api_key = os.environ.get("STRIPE_API_KEY", "")
        if not api_key or not HAS_REQUESTS:
            return None
        resp = _requests.request(
            method, f"https://api.stripe.com/v1/{path}",
            auth=(api_key, ""),
            data=data, timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def list_payments(self, config: dict, context: dict) -> dict:
        limit = config.get("limit", 10)
        result = self._api("GET", f"payment_intents?limit={limit}")
        if result is None:
            return {"status": "simulated", "payments": [
                {"id": "pi_sim_1", "amount": 2999, "currency": "usd", "status": "succeeded"},
                {"id": "pi_sim_2", "amount": 4999, "currency": "usd", "status": "succeeded"},
            ]}
        payments = [
            {"id": p["id"], "amount": p["amount"], "currency": p["currency"], "status": p["status"]}
            for p in result.get("data", [])
        ]
        return {"status": "success", "payments": payments}

    def create_payment_link(self, config: dict, context: dict) -> dict:
        amount = config.get("amount", 0)
        currency = config.get("currency", "usd")
        product_name = config.get("product_name", "Payment")
        # Create a price first, then a payment link
        price_result = self._api("POST", "prices", {
            "unit_amount": amount, "currency": currency,
            "product_data[name]": product_name,
        })
        if price_result is None:
            return {"status": "simulated", "url": "https://buy.stripe.com/test_sim123", "amount": amount, "currency": currency}
        link_result = self._api("POST", "payment_links", {
            "line_items[0][price]": price_result["id"],
            "line_items[0][quantity]": 1,
        })
        return {"status": "success", "url": link_result.get("url", ""), "id": link_result.get("id", "")}

    def get_customer(self, config: dict, context: dict) -> dict:
        customer_id = config.get("customer_id", "")
        email = config.get("email", "")
        if customer_id:
            result = self._api("GET", f"customers/{customer_id}")
        elif email:
            result = self._api("GET", f"customers/search?query=email:'{email}'")
            if result:
                data = result.get("data", [])
                result = data[0] if data else None
        else:
            result = None
        if result is None:
            return {"status": "simulated", "customer": {
                "id": "cus_sim_1", "email": email or "user@example.com", "name": "John Doe",
            }}
        return {"status": "success", "customer": {
            "id": result.get("id"), "email": result.get("email"), "name": result.get("name"),
            "created": result.get("created"),
        }}

    def list_subscriptions(self, config: dict, context: dict) -> dict:
        customer_id = config.get("customer_id", "")
        limit = config.get("limit", 10)
        path = f"subscriptions?limit={limit}"
        if customer_id:
            path += f"&customer={customer_id}"
        result = self._api("GET", path)
        if result is None:
            return {"status": "simulated", "subscriptions": [
                {"id": "sub_sim_1", "status": "active", "plan": "Pro Monthly", "amount": 2999},
            ]}
        subs = [
            {"id": s["id"], "status": s["status"],
             "current_period_end": s.get("current_period_end"),
             "plan_id": s.get("plan", {}).get("id", "")}
            for s in result.get("data", [])
        ]
        return {"status": "success", "subscriptions": subs}

    def create_invoice(self, config: dict, context: dict) -> dict:
        customer_id = config.get("customer_id", "")
        description = config.get("description", "")
        amount = config.get("amount", 0)
        currency = config.get("currency", "usd")
        if not customer_id:
            return {"status": "error", "error": "customer_id required"}
        # Create invoice item then invoice
        item_result = self._api("POST", "invoiceitems", {
            "customer": customer_id, "amount": amount,
            "currency": currency, "description": description,
        })
        if item_result is None:
            return {"status": "simulated", "invoice_id": "inv_sim_123", "customer_id": customer_id, "amount": amount}
        inv_result = self._api("POST", "invoices", {"customer": customer_id, "auto_advance": "true"})
        return {"status": "success", "invoice_id": inv_result.get("id", ""), "url": inv_result.get("hosted_invoice_url", "")}

    def validate_config(self, action: str, config: dict) -> list[str]:
        errors = []
        if action == "create_payment_link" and not config.get("amount"):
            errors.append("'amount' required (in cents)")
        if action == "create_invoice" and not config.get("customer_id"):
            errors.append("'customer_id' required")
        if action == "get_customer" and not config.get("customer_id") and not config.get("email"):
            errors.append("'customer_id' or 'email' required")
        return errors
