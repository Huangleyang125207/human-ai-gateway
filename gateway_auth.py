"""Short-lived Gateway access tokens for desktop model calls.

The long-lived device credential is used only at the exchange endpoint. Access
tokens remain process memory and are renewed before expiry.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Callable

import httpx


class GatewayAccessTokenCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[str, float]] = {}

    def get(
        self,
        base_url: str,
        device_credential: str,
        *,
        post: Callable | None = None,
        now: float | None = None,
    ) -> str:
        base = str(base_url or "").strip().rstrip("/")
        credential = str(device_credential or "").strip()
        if not base or not credential:
            raise RuntimeError("Gateway device credential is not configured")
        clock = time.monotonic() if now is None else now
        cache_key = base + "\n" + hashlib.sha256(credential.encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._tokens.get(cache_key)
            if cached and cached[1] > clock:
                return cached[0]
            response = (post or httpx.post)(
                base + "/auth/token",
                headers={"X-Device-Token": credential},
                timeout=15.0,
            )
            response.raise_for_status()
            payload = response.json()
            access_token = str(payload.get("access_token") or "").strip()
            expires_in = int(payload.get("expires_in") or 0)
            if not access_token or expires_in <= 0:
                raise RuntimeError("Gateway returned an invalid access token")
            refresh_at = clock + max(1, expires_in - 30)
            self._tokens[cache_key] = (access_token, refresh_at)
            return access_token


_ACCESS_TOKENS = GatewayAccessTokenCache()


def get_gateway_access_token(base_url: str, device_credential: str) -> str:
    return _ACCESS_TOKENS.get(base_url, device_credential)
