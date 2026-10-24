"""OAuth di cTrader: parametri documentati, risposte anomale rifiutate, nessun segreto nei messaggi."""

import io
import urllib.error
import urllib.parse

import pytest
from fake_oauth import (
    ACCESS,
    CLIENT_ID,
    CLIENT_SECRET,
    CODE,
    REFRESH,
    SECRETS,
    FakeTokenEndpoint,
    app,
    redirect_later,
    token_body,
)

from ctrader_async import oauth
from ctrader_async.oauth import (
    AUTH_URL,
    LoopbackReceiver,
    OAuthError,
    TokenPair,
    authorization_url,
    exchange_code,
    http_get,
    refresh,
)

NOW = 1_790_000_000.0


def test_authorization_url_has_documented_parameters():
    url = authorization_url(app(), "trading")
    base, _, query = url.partition("?")
    assert base == AUTH_URL
    assert dict(urllib.parse.parse_qsl(query)) == {
        "client_id": CLIENT_ID,
        "redirect_uri": "http://localhost:8765/callback",
        "scope": "trading",
        "product": "web",
    }
    assert CLIENT_SECRET not in url


def test_unknown_scope_is_rejected():
    with pytest.raises(ValueError, match="scope"):
        authorization_url(app(), "admin")


def test_exchange_code_sends_documented_parameters():
    endpoint = FakeTokenEndpoint([(200, token_body())])
    pair = exchange_code(app(), CODE, "trading", fetch=endpoint, clock=lambda: NOW)
    assert endpoint.calls == [
        {
            "grant_type": "authorization_code",
            "code": CODE,
            "redirect_uri": "http://localhost:8765/callback",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
    ]
    assert pair == TokenPair(ACCESS, REFRESH, NOW + 2_628_000, "trading", "bearer")
    assert pair.seconds_left(NOW) == 2_628_000


def test_refresh_sends_refresh_token_and_keeps_scope():
    old = TokenPair(ACCESS, REFRESH, NOW, "accounts")
    endpoint = FakeTokenEndpoint([(200, token_body("access-2", "refresh-2"))])
    new = refresh(app(), old, fetch=endpoint, clock=lambda: NOW)
    assert endpoint.calls == [
        {
            "grant_type": "refresh_token",
            "refresh_token": REFRESH,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }
    ]
    assert (new.access_token, new.refresh_token, new.scope) == ("access-2", "refresh-2", "accounts")


BAD_RESPONSES = [
    (200, token_body(errorCode="ACCESS_DENIED", description="codice scaduto")),
    (400, token_body(errorCode="INVALID_REQUEST", description="redirect_uri diverso")),
    (500, b"<html>errore</html>"),
    (200, b"[]"),
    (403, b"{}"),
    (200, token_body(refresh="")),
    (200, token_body(access=None)),
    (200, token_body(expires_in=0)),
    (200, token_body(expires_in=-5)),
    (200, token_body(expires_in="2628000")),
    (200, token_body(expires_in=True)),
    (200, token_body(expires_in=None)),
]


@pytest.mark.parametrize(("status", "body"), BAD_RESPONSES)
def test_anomalous_responses_are_errors_without_secrets(status, body):
    """Una risposta anomala non produce mai una coppia parziale, e l'errore non riporta segreti."""
    endpoint = FakeTokenEndpoint([(status, body)])
    with pytest.raises(OAuthError) as info:
        exchange_code(app(), CODE, "trading", fetch=endpoint, clock=lambda: NOW)
    assert not any(s in str(info.value) for s in SECRETS)


def test_error_code_is_reported():
    endpoint = FakeTokenEndpoint([(200, token_body(errorCode="ACCESS_DENIED", description="scaduto"))])
    with pytest.raises(OAuthError, match="ACCESS_DENIED") as info:
        exchange_code(app(), CODE, "trading", fetch=endpoint)
    assert info.value.error_code == "ACCESS_DENIED"


def test_empty_code_is_rejected_without_request():
    endpoint = FakeTokenEndpoint([])
    with pytest.raises(OAuthError):
        exchange_code(app(), "", "trading", fetch=endpoint)
    assert endpoint.calls == []


def test_reprs_hide_secrets():
    pair = TokenPair(ACCESS, REFRESH, NOW, "trading")
    assert not any(s in repr(app()) + repr(pair) for s in SECRETS)


def test_http_get_returns_error_body(monkeypatch):
    body = token_body(errorCode="INVALID_REQUEST")

    def fail(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(body))

    monkeypatch.setattr(oauth.urllib.request, "urlopen", fail)
    assert http_get(f"{oauth.TOKEN_URL}?client_secret={CLIENT_SECRET}", 1.0) == (400, body)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")), "ConnectionRefusedError"),
        (
            urllib.error.URLError(f"motivo testuale con {oauth.TOKEN_URL}?client_secret={CLIENT_SECRET}"),
            "URLError",
        ),
        (TimeoutError("timed out"), "TimeoutError"),
    ],
)
def test_network_errors_hide_url(monkeypatch, error, expected):
    def fail(request, timeout):
        raise error

    monkeypatch.setattr(oauth.urllib.request, "urlopen", fail)
    with pytest.raises(OAuthError, match=expected) as info:
        exchange_code(app(), CODE, "trading")
    assert not any(s in str(info.value) for s in SECRETS)
    assert info.value.__suppress_context__  # la traceback non riporta l'eccezione originale


def _receiver_url(rx: LoopbackReceiver, query: str, path: str = "/callback") -> str:
    return f"http://127.0.0.1:{rx.port}{path}?{query}"


def test_loopback_receives_code():
    with LoopbackReceiver("http://127.0.0.1:0/callback") as rx:
        browser = redirect_later(_receiver_url(rx, f"code={CODE}"))
        assert rx.wait(5) == CODE
    browser.join(5)
    assert browser.statuses == [200]


def test_loopback_ignores_other_paths():
    """/favicon.ico o una richiesta senza codice ricevono 404 e non chiudono l'attesa."""
    with LoopbackReceiver("http://localhost:0/callback") as rx:
        browser = redirect_later(
            _receiver_url(rx, "x=1", path="/favicon.ico"),
            _receiver_url(rx, "x=1"),
            _receiver_url(rx, f"code={CODE}"),
        )
        assert rx.wait(5) == CODE
    browser.join(5)
    assert browser.statuses == [404, 404, 200]


def test_loopback_reports_denied_authorization():
    with LoopbackReceiver("http://127.0.0.1:0/callback") as rx:
        browser = redirect_later(_receiver_url(rx, "error=access_denied&error_description=negato"))
        with pytest.raises(OAuthError, match="negato"):
            rx.wait(5)
    browser.join(5)
    assert browser.statuses == [400]


def test_loopback_times_out():
    with LoopbackReceiver("http://127.0.0.1:0/callback") as rx, pytest.raises(TimeoutError):
        rx.wait(0.2)


@pytest.mark.parametrize(
    "uri",
    [
        "https://localhost:8765/callback",
        "http://example.com:8765/callback",
        "http://0.0.0.0:8765/callback",
        "http://localhost/callback",
    ],
)
def test_loopback_rejects_non_loopback_redirects(uri):
    with pytest.raises(ValueError):
        LoopbackReceiver(uri)


def test_loopback_requires_context_manager():
    with pytest.raises(RuntimeError):
        LoopbackReceiver("http://127.0.0.1:0/callback").wait(0.1)
