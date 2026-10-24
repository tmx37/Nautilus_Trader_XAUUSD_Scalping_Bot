"""Finto endpoint `/apps/token` di cTrader e redirect simulato, per i test OAuth senza rete."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from ctrader_async.oauth import TOKEN_URL, OAuthApp

CLIENT_ID = "1234_clientid"
CLIENT_SECRET = "segreto-del-client-0001"
CODE = "codice-autorizzazione-0001"
ACCESS = "access-token-0001"
REFRESH = "refresh-token-0001"
SECRETS = (CLIENT_SECRET, CODE, ACCESS, REFRESH)


def app(redirect_uri: str = "http://localhost:8765/callback") -> OAuthApp:
    return OAuthApp(CLIENT_ID, CLIENT_SECRET, redirect_uri)


def token_body(
    access: str = ACCESS, refresh: str = REFRESH, expires_in: object = 2_628_000, **extra
) -> bytes:
    """Risposta documentata di /apps/token (help.ctrader.com/open-api/account-authentication)."""
    data = {
        "accessToken": access,
        "tokenType": "bearer",
        "expiresIn": expires_in,
        "refreshToken": refresh,
        "errorCode": None,
        "description": None,
    }
    data.update(extra)
    return json.dumps(data).encode()


@dataclass
class FakeTokenEndpoint:
    """Restituisce le risposte in ordine e registra i parametri di ogni richiesta."""

    responses: list[tuple[int, bytes]]
    calls: list[dict[str, str]] = field(default_factory=list)

    def __call__(self, url: str, timeout_s: float) -> tuple[int, bytes]:
        base, _, query = url.partition("?")
        assert base == TOKEN_URL
        self.calls.append(dict(urllib.parse.parse_qsl(query)))
        return self.responses.pop(0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Browser(threading.Thread):
    """Simula il browser che segue i redirect di cTrader, uno dopo l'altro; registra gli stati HTTP."""

    def __init__(self, *urls: str) -> None:
        super().__init__(daemon=True)
        self.urls = urls
        self.statuses: list[int] = []

    def run(self) -> None:
        for url in self.urls:
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    self.statuses.append(response.status)
            except urllib.error.HTTPError as exc:
                self.statuses.append(exc.code)


def redirect_later(*urls: str) -> Browser:
    browser = Browser(*urls)
    browser.start()
    return browser
