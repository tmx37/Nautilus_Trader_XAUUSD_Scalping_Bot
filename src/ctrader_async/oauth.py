"""OAuth2 di cTrader Open API: URL di autorizzazione, scambio del codice, refresh, ricezione del codice.

Fonte: help.ctrader.com/open-api/account-authentication (letta il 2026-10-24).
- Il codice di autorizzazione vale **un minuto**: va scambiato subito.
- L'access token dura circa 30 giorni (`expiresIn` in secondi, 2.628.000 di default); il refresh token non
  scade, ma ogni refresh invalida la coppia precedente (rischio T6): la nuova coppia va scritta su disco
  prima di usarla, e un solo processo rinnova ciascuna coppia (`tokens.refresh_stored`).
- La documentazione non prevede il parametro `state`: il codice si riceve solo su un indirizzo di loopback.
- Endpoint del token: la tabella della documentazione dice GET con parametri in query, l'esempio di refresh
  usa POST. Si usa GET, come l'SDK ufficiale [DA VERIFICARE al primo login].

Le chiamate HTTP sono bloccanti (si fanno poche volte al mese); dentro un event loop vanno eseguite con
`asyncio.to_thread`. Nessun messaggio d'errore contiene l'URL della richiesta: in query ci sono il client
secret e il codice o il refresh token.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
SCOPES = ("accounts", "trading")  # accounts: sola lettura; trading: accesso completo
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")

# (url, timeout_s) -> (stato HTTP, corpo). Iniettabile nei test.
Fetch = Callable[[str, float], tuple[int, bytes]]


class OAuthError(Exception):
    """Errore del flusso OAuth. Il messaggio non contiene mai segreti né token."""

    def __init__(self, message: str, *, error_code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status = status


@dataclass(frozen=True, slots=True)
class OAuthApp:
    """Applicazione registrata su openapi.ctrader.com. Il secret non compare nella repr."""

    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Coppia di token con la scadenza assoluta (epoch UTC, secondi). I token non compaiono nella repr."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float
    scope: str
    token_type: str = "bearer"

    def seconds_left(self, now: float) -> float:
        return self.expires_at - now


def _check_scope(scope: str) -> None:
    if scope not in SCOPES:
        raise ValueError(f"scope sconosciuto {scope!r}: ammessi {SCOPES}")


def authorization_url(app: OAuthApp, scope: str = "trading") -> str:
    """URL da aprire nel browser; dopo il consenso cTrader reindirizza a `redirect_uri?code=...`."""
    _check_scope(scope)
    query = urllib.parse.urlencode(
        {"client_id": app.client_id, "redirect_uri": app.redirect_uri, "scope": scope, "product": "web"}
    )
    return f"{AUTH_URL}?{query}"


def http_get(url: str, timeout_s: float) -> tuple[int, bytes]:
    """GET con urllib. Gli errori HTTP restituiscono stato e corpo (contiene `errorCode`)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        # Si riporta solo un motivo di sistema (errno, DNS, TLS): un motivo testuale potrebbe contenere
        # l'URL. `from None` per lo stesso motivo: la catena delle eccezioni lo stamperebbe.
        reason = exc.reason
        detail = f"{type(reason).__name__}: {reason}" if isinstance(reason, OSError) else "URLError"
        raise OAuthError(f"endpoint del token non raggiungibile: {detail}") from None
    except OSError as exc:  # TimeoutError e altri errori di socket
        raise OAuthError(f"endpoint del token non raggiungibile: {type(exc).__name__}: {exc}") from None


def parse_token_response(status: int, body: bytes, *, scope: str, now: float) -> TokenPair:
    """Valida la risposta di /apps/token. Ogni anomalia è un errore: un token parziale non si salva."""
    try:
        data: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise OAuthError(f"risposta non JSON (HTTP {status})", status=status) from None
    if not isinstance(data, dict):
        raise OAuthError(f"risposta inattesa (HTTP {status})", status=status)
    if data.get("errorCode") is not None:
        raise OAuthError(
            f"cTrader ha rifiutato la richiesta: {data['errorCode']} ({data.get('description')})",
            error_code=str(data["errorCode"]),
            status=status,
        )
    if status != 200:
        raise OAuthError(f"HTTP {status} senza errorCode", status=status)
    access, refresh, expires_in = data.get("accessToken"), data.get("refreshToken"), data.get("expiresIn")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise OAuthError("risposta senza accessToken o refreshToken", status=status)
    if isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0:
        raise OAuthError(f"expiresIn non valido: {expires_in!r}", status=status)
    token_type = data.get("tokenType") or "bearer"
    return TokenPair(access, refresh, now + expires_in, scope, str(token_type))


def _token_request(params: dict[str, str], fetch: Fetch, timeout_s: float) -> tuple[int, bytes]:
    return fetch(f"{TOKEN_URL}?{urllib.parse.urlencode(params)}", timeout_s)


def exchange_code(
    app: OAuthApp,
    code: str,
    scope: str,
    *,
    fetch: Fetch = http_get,
    clock: Callable[[], float] = time.time,
    timeout_s: float = 30.0,
) -> TokenPair:
    """Scambia il codice di autorizzazione (valido un minuto) con la prima coppia di token."""
    _check_scope(scope)
    if not code:
        raise OAuthError("codice di autorizzazione vuoto")
    params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": app.redirect_uri,
        "client_id": app.client_id,
        "client_secret": app.client_secret,
    }
    status, body = _token_request(params, fetch, timeout_s)
    return parse_token_response(status, body, scope=scope, now=clock())


def refresh(
    app: OAuthApp,
    pair: TokenPair,
    *,
    fetch: Fetch = http_get,
    clock: Callable[[], float] = time.time,
    timeout_s: float = 30.0,
) -> TokenPair:
    """Rinnova la coppia. Dopo una risposta valida la coppia vecchia non vale più: salvare subito la nuova."""
    params = {
        "grant_type": "refresh_token",
        "refresh_token": pair.refresh_token,
        "client_id": app.client_id,
        "client_secret": app.client_secret,
    }
    status, body = _token_request(params, fetch, timeout_s)
    return parse_token_response(status, body, scope=pair.scope, now=clock())


class LoopbackReceiver:
    """Server HTTP di una sola richiesta utile su `redirect_uri` (solo loopback) per ricevere il codice.

    Si apre prima di mandare l'utente sul browser, così la porta è già occupata da noi:

        with LoopbackReceiver(app.redirect_uri) as rx:
            webbrowser.open(authorization_url(app))
            code = rx.wait(timeout_s=300)

    Le richieste su altri percorsi (es. /favicon.ico) ricevono 404 e non chiudono l'attesa. Il server non
    scrive log: la riga di richiesta contiene il codice.
    """

    def __init__(self, redirect_uri: str) -> None:
        parts = urllib.parse.urlsplit(redirect_uri)
        if parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS:
            raise ValueError(f"il redirect deve essere http su {LOOPBACK_HOSTS}, non {redirect_uri!r}")
        if parts.port is None:
            raise ValueError(f"il redirect deve indicare la porta: {redirect_uri!r}")
        self._host = "127.0.0.1"
        self._port = parts.port
        self._path = parts.path or "/"
        self._server: HTTPServer | None = None
        self._result: dict[str, str] | None = None

    @property
    def port(self) -> int:
        """Porta effettiva (diversa da quella del redirect solo se questo indica la porta 0, nei test)."""
        if self._server is None:
            return self._port
        return self._server.server_address[1]

    def __enter__(self) -> LoopbackReceiver:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parts = urllib.parse.urlsplit(self.path)
                query = dict(urllib.parse.parse_qsl(parts.query))
                if parts.path != receiver._path or not ({"code", "error"} & query.keys()):
                    self._reply(404, "Percorso sconosciuto.")
                    return
                receiver._result = query
                if "code" in query:
                    self._reply(200, "Autorizzazione ricevuta. Puoi chiudere questa finestra.")
                else:
                    self._reply(400, "Autorizzazione negata o non riuscita. Controlla il terminale.")

            def _reply(self, status: int, text: str) -> None:
                body = f"<!doctype html><meta charset=utf-8><p>{text}</p>".encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = HTTPServer((self._host, self._port), Handler)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.server_close()
            self._server = None

    def wait(self, timeout_s: float, *, clock: Callable[[], float] = time.monotonic) -> str:
        """Attende il redirect di cTrader e restituisce il codice. TimeoutError se non arriva in tempo."""
        if self._server is None:
            raise RuntimeError("LoopbackReceiver va usato come context manager")
        deadline = clock() + timeout_s
        while self._result is None:
            left = deadline - clock()
            if left <= 0:
                raise TimeoutError(f"nessun redirect da cTrader entro {timeout_s:.0f} s")
            self._server.timeout = left
            self._server.handle_request()
        result, self._result = self._result, None
        if "code" not in result or not result["code"]:
            detail = result.get("error_description") or result.get("error") or "senza codice"
            raise OAuthError(f"autorizzazione non concessa: {detail}", error_code=result.get("error"))
        return result["code"]
