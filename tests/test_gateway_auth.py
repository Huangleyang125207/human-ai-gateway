from gateway_auth import GatewayAccessTokenCache


class _Response:
    status_code = 200

    def json(self):
        return {"access_token": "short-access", "expires_in": 900}

    def raise_for_status(self):
        return None


def test_device_credential_is_exchanged_once_and_access_token_stays_in_memory():
    calls = []
    cache = GatewayAccessTokenCache()

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _Response()

    first = cache.get("https://edge.example/v1", "device-secret", post=post, now=1000.0)
    second = cache.get("https://edge.example/v1", "device-secret", post=post, now=1001.0)

    assert first == second == "short-access"
    assert calls == [(
        "https://edge.example/v1/auth/token",
        {"headers": {"X-Device-Token": "device-secret"}, "timeout": 15.0},
    )]
