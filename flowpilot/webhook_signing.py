"""Webhook signature verification for various providers."""

import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)


class WebhookVerifier:
    """Verifies incoming webhook signatures from various providers."""

    @staticmethod
    def verify_github(payload_body: bytes, signature_header: str, secret: str) -> bool:
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    @staticmethod
    def verify_slack(payload_body: bytes, timestamp: str, signature: str, signing_secret: str) -> bool:
        if not timestamp or not signature:
            return False
        if abs(time.time() - float(timestamp)) > 300:
            logger.warning("Slack webhook timestamp too old (>5 min)")
            return False
        base = f"v0:{timestamp}:{payload_body.decode()}"
        expected = "v0=" + hmac.new(
            signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def verify_stripe(payload_body: bytes, signature_header: str, secret: str) -> bool:
        if not signature_header:
            return False
        parts = {}
        for item in signature_header.split(","):
            key, _, value = item.partition("=")
            parts[key.strip()] = value.strip()
        timestamp = parts.get("t")
        v1_sig = parts.get("v1")
        if not timestamp or not v1_sig:
            return False
        if abs(time.time() - float(timestamp)) > 300:
            logger.warning("Stripe webhook timestamp too old (>5 min)")
            return False
        signed_payload = f"{timestamp}.{payload_body.decode()}"
        expected = hmac.new(
            secret.encode(), signed_payload.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, v1_sig)

    @staticmethod
    def verify_generic_hmac(payload_body: bytes, signature: str, secret: str, algorithm: str = "sha256") -> bool:
        if not signature:
            return False
        hash_func = getattr(hashlib, algorithm, None)
        if not hash_func:
            logger.error(f"Unsupported hash algorithm: {algorithm}")
            return False
        expected = hmac.new(secret.encode(), payload_body, hash_func).hexdigest()
        clean_sig = signature
        prefix = f"{algorithm}="
        if clean_sig.startswith(prefix):
            clean_sig = clean_sig[len(prefix):]
        return hmac.compare_digest(expected, clean_sig)

    @classmethod
    def verify(cls, provider: str, payload_body: bytes, headers: dict, secret: str) -> bool:
        provider = provider.lower()
        try:
            if provider == "github":
                return cls.verify_github(payload_body, headers.get("X-Hub-Signature-256", ""), secret)
            elif provider == "slack":
                return cls.verify_slack(
                    payload_body,
                    headers.get("X-Slack-Request-Timestamp", ""),
                    headers.get("X-Slack-Signature", ""),
                    secret,
                )
            elif provider == "stripe":
                return cls.verify_stripe(payload_body, headers.get("Stripe-Signature", ""), secret)
            else:
                sig = headers.get("X-Signature", headers.get("X-Hub-Signature-256", ""))
                return cls.verify_generic_hmac(payload_body, sig, secret)
        except Exception as e:
            logger.error(f"Webhook verification failed for {provider}: {e}")
            return False
