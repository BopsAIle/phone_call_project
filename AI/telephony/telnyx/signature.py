"""Verify the Ed25519 signature Telnyx puts on every webhook.

The webhook URL is public, so an unsigned handler lets anyone make this
service answer calls and start streams on our Telnyx account.
"""

from __future__ import annotations

import base64
import logging
import time

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "telnyx-signature-ed25519"
TIMESTAMP_HEADER = "telnyx-timestamp"


class SignatureError(ValueError):
    """Webhook did not come from Telnyx, or came too long ago."""


def _verify_key(public_key_b64: str):
    try:
        from nacl.signing import VerifyKey
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SignatureError("pynacl is not installed; cannot verify Telnyx webhooks") from exc
    try:
        return VerifyKey(base64.b64decode(public_key_b64))
    except Exception as exc:
        raise SignatureError("TELNYX_PUBLIC_KEY is not a valid base64 Ed25519 key") from exc


def verify_webhook(
    *,
    body: bytes,
    signature_b64: str | None,
    timestamp: str | None,
    public_key_b64: str,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> None:
    """Raise SignatureError unless `body` carries a fresh, valid Telnyx signature."""
    if not public_key_b64:
        raise SignatureError("TELNYX_PUBLIC_KEY is empty")
    if not signature_b64 or not timestamp:
        raise SignatureError("Missing Telnyx signature headers")
    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        raise SignatureError("Malformed telnyx-timestamp")
    current = time.time() if now is None else now
    if tolerance_seconds > 0 and abs(current - sent_at) > tolerance_seconds:
        raise SignatureError("Telnyx webhook timestamp outside tolerance (replay?)")
    signed = f"{timestamp}|".encode() + body
    try:
        _verify_key(public_key_b64).verify(signed, base64.b64decode(signature_b64))
    except SignatureError:
        raise
    except Exception as exc:
        raise SignatureError("Telnyx webhook signature mismatch") from exc
