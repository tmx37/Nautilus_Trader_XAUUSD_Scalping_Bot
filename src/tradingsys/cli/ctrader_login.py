"""`ctrader-login`: primo login OAuth a cTrader Open API e salvataggio dei token in `secrets/`.

Uso (dalla radice del repo, con l'app in stato "Active" e `config/ctrader.env` compilato):

    uv run ctrader-login                 # apre il browser, attende il redirect, salva i token
    uv run ctrader-login --no-browser    # stampa solo l'URL da aprire

Il codice ricevuto vale un minuto e viene scambiato subito. Se esiste già un file di token serve `--force`:
un nuovo login mentre il nodo o il watchdog usano la coppia attuale potrebbe lasciarli senza token validi.
Non stampa mai token né secret.
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from ctrader_async.oauth import (
    SCOPES,
    Fetch,
    LoopbackReceiver,
    OAuthError,
    authorization_url,
    exchange_code,
    http_get,
)
from ctrader_async.settings import CtraderSettings, SettingsError, load_settings
from ctrader_async.tokens import TokenStore, TokenStoreError

DEFAULT_ENV_FILE = Path("config/ctrader.env")


def run_login(
    settings: CtraderSettings,
    *,
    scope: str = "trading",
    force: bool = False,
    timeout_s: float = 300.0,
    open_browser: Callable[[str], object] | None = webbrowser.open,
    fetch: Fetch = http_get,
    out: TextIO = sys.stdout,
) -> int:
    """Esegue il login; restituisce il codice d'uscita (0 = token salvati)."""
    store = TokenStore(settings.token_file)
    if store.exists() and not force:
        print(
            f"Esiste già {store.path}. Un nuovo login sostituisce la coppia di token in uso: chiudere nodo e "
            "watchdog e ripetere con --force.",
            file=out,
        )
        return 2
    url = authorization_url(settings.app, scope)
    try:
        with store.lock(), LoopbackReceiver(settings.app.redirect_uri) as rx:
            print(f"Apri questo indirizzo e autorizza l'app (scope {scope}):\n\n  {url}\n", file=out)
            if open_browser is not None:
                open_browser(url)
            print(
                f"In attesa del redirect su {settings.app.redirect_uri} (max {timeout_s:.0f} s)...", file=out
            )
            code = rx.wait(timeout_s)
            pair = exchange_code(settings.app, code, scope, fetch=fetch)
            store.save(pair, settings.app.client_id)
    except (OAuthError, TokenStoreError, TimeoutError, OSError) as exc:
        print(f"Login non riuscito: {exc}", file=out)
        return 1
    expires = datetime.fromtimestamp(pair.expires_at, UTC).strftime("%Y-%m-%d %H:%M UTC")
    days = pair.seconds_left(time.time()) / 86400
    print(
        f"Token salvati in {store.path} (permessi 600). Scadenza: {expires}, fra {days:.0f} giorni.", file=out
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ctrader-login", description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--scope", choices=SCOPES, default="trading")
    parser.add_argument("--force", action="store_true", help="sostituisce un file di token esistente")
    parser.add_argument("--no-browser", action="store_true", help="non apre il browser, stampa solo l'URL")
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="attesa massima del redirect, in secondi"
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.env_file)
    except FileNotFoundError:
        print(f"{args.env_file} non esiste: copiare config/ctrader.example.env e compilarlo.")
        return 1
    except SettingsError as exc:
        print(exc)
        return 1
    return run_login(
        settings,
        scope=args.scope,
        force=args.force,
        timeout_s=args.timeout,
        open_browser=None if args.no_browser else webbrowser.open,
    )


if __name__ == "__main__":
    raise SystemExit(main())
