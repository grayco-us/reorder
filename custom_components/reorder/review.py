"""Opaque session-bound review seals; sensitive connection values never leave HA."""
import hashlib
import hmac
import json

from .batch import review_batch


def review_token(engine, entry, batch_id):
    """Bind a review to saved contents and all current connection options."""
    report = review_batch(engine.store.data, batch_id)
    payload = json.dumps({"entry": entry.entry_id, "batch": report,
                          "options": dict(entry.options)}, sort_keys=True, separators=(",", ":"))
    return hmac.new(engine.review_secret, payload.encode(), hashlib.sha256).hexdigest()


def review_matches(engine, entry, batch_id, token):
    try:
        return isinstance(token, str) and hmac.compare_digest(
            review_token(engine, entry, batch_id).encode(), token.encode())
    except (ValueError, KeyError, TypeError):
        return False
