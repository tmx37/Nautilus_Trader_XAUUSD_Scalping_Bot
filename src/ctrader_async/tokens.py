"""Archivio dei token OAuth su disco: scrittura atomica, permessi 600, un processo alla volta (rischio T6).

Il refresh invalida la coppia precedente. Se due processi rinnovano la stessa coppia, uno dei due resta con
token non validi; se un processo rinnova e non salva, la coppia nuova si perde e serve un nuovo login.
Quindi:
- ogni scrittura passa da un file temporaneo nella stessa cartella, fsync e `os.replace`;
- il rinnovo avviene sotto un lock esclusivo (`flock` su `<file>.lock`), non bloccante;
- un file leggibile da altri utenti non si carica: i token danno accesso completo al conto.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import stat
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ctrader_async.oauth import Fetch, OAuthApp, TokenPair, http_get, refresh

SCHEMA_VERSION = 1


class TokenStoreError(Exception):
    """File dei token assente, illeggibile, insicuro o di un'altra applicazione."""


class TokenLockBusy(TokenStoreError):
    """Un altro processo sta già scrivendo o rinnovando i token."""


class TokenStore:
    """File JSON con una sola coppia di token, legata al `client_id` dell'applicazione che l'ha ottenuta."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")

    def exists(self) -> bool:
        return self.path.exists()

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """Lock esclusivo fra processi; TokenLockBusy se è già preso (anche da questo processo)."""
        self._ensure_dir()
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise TokenLockBusy(f"token in uso da un altro processo ({self._lock_path})") from None
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def load(self, client_id: str) -> TokenPair | None:
        """Coppia salvata, o None se il file non esiste. Errore se è insicuro, corrotto o di un'altra app."""
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return None
        if st.st_mode & 0o077:
            raise TokenStoreError(
                f"{self.path} è accessibile ad altri utenti (permessi {stat.filemode(st.st_mode)}): "
                "correggere con chmod 600"
            )
        try:
            data: Any = json.loads(self.path.read_text(encoding="utf-8"))
            if data["schema"] != SCHEMA_VERSION:
                raise TokenStoreError(f"{self.path}: schema {data['schema']!r}, atteso {SCHEMA_VERSION}")
            if data["client_id"] != client_id:
                raise TokenStoreError(f"{self.path}: token di un'altra applicazione (client_id diverso)")
            pair = TokenPair(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=float(data["expires_at"]),
                scope=data["scope"],
                token_type=data["token_type"],
            )
        except TokenStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise TokenStoreError(f"{self.path} illeggibile: {type(exc).__name__}") from None
        if not pair.access_token or not pair.refresh_token:
            raise TokenStoreError(f"{self.path}: token vuoti")
        return pair

    def save(self, pair: TokenPair, client_id: str, *, clock: Callable[[], float] = time.time) -> None:
        """Scrittura atomica con permessi 600: dopo un errore resta intatto il file precedente."""
        self._ensure_dir()
        record = {
            "schema": SCHEMA_VERSION,
            "client_id": client_id,
            "scope": pair.scope,
            "token_type": pair.token_type,
            "access_token": pair.access_token,
            "refresh_token": pair.refresh_token,
            "expires_at": pair.expires_at,
            "saved_at": clock(),
        }
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        dir_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _ensure_dir(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)


def refresh_stored(
    app: OAuthApp,
    store: TokenStore,
    *,
    fetch: Fetch = http_get,
    clock: Callable[[], float] = time.time,
) -> TokenPair:
    """Rinnova la coppia salvata e la riscrive, tutto sotto il lock del file.

    Se la richiesta fallisce il file resta com'è. Se la richiesta riesce ma il salvataggio no, la coppia
    vecchia non vale più e quella nuova è persa: l'errore lo dice, perché serve un nuovo login.
    """
    with store.lock():
        pair = store.load(app.client_id)
        if pair is None:
            raise TokenStoreError(f"{store.path} non esiste: eseguire prima il login")
        new = refresh(app, pair, fetch=fetch, clock=clock)
        try:
            store.save(new, app.client_id, clock=clock)
        except Exception as exc:
            raise TokenStoreError(
                f"refresh riuscito ma salvataggio fallito ({type(exc).__name__}): la coppia precedente "
                "non è più valida, serve un nuovo login"
            ) from None
        return new
