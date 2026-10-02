"""Signed tokens for practice sets, so a chat reopened from the browser's
history can still check answers.

Answers are released only for questions the server served. The session
tables that record that are wiped on every deploy, so instead each set
carries a token: its question ids, signed with a server-side key. /api/check
accepts a question whose id is inside a valid token. A token can't be forged
or widened to other ids without the key, and holds nothing secret itself.

The key is SET_TOKEN_SECRET if set (`fly secrets set SET_TOKEN_SECRET=...`).
Otherwise it is derived from FIREWORKS_API_KEY, which is stable across
deploys; failing both, a random per-process key, so tokens then last only
until the next restart.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets

_secret = os.getenv("SET_TOKEN_SECRET")
if _secret:
    KEY = _secret.encode()
elif os.getenv("FIREWORKS_API_KEY"):
    KEY = hashlib.sha256(b"regents-set-token:" + os.getenv("FIREWORKS_API_KEY").encode()).digest()
else:
    KEY = secrets.token_bytes(32)

MAX_IDS = 50


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(payload):
    return _b64(hmac.new(KEY, payload.encode(), hashlib.sha256).digest()[:18])


def sign(question_ids):
    payload = _b64(json.dumps(sorted({int(i) for i in question_ids})[:MAX_IDS], separators=(",", ":")).encode())
    return f"{payload}.{_sig(payload)}"


def verify(token):
    """The set of question ids in a valid token, else an empty set."""
    if not isinstance(token, str) or len(token) > 1000 or token.count(".") != 1:
        return set()
    payload, sig = token.split(".")
    if not hmac.compare_digest(sig, _sig(payload)):
        return set()
    try:
        ids = json.loads(_unb64(payload))
    except (ValueError, TypeError):
        return set()
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return set()
    return set(ids)
