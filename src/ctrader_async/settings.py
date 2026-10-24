"""Impostazioni di connessione da `config/ctrader.env` (ignorato da git; modello in `ctrader.example.env`).

Come per la config del rischio: chiavi sconosciute e valori mancanti sono errori, così un refuso non
diventa un default silenzioso. Il file non passa da `os.environ`, per non esporre il secret ai processi
figli.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ctrader_async.oauth import OAuthApp

HOSTS = {"demo": "demo.ctraderapi.com", "live": "live.ctraderapi.com"}
PORT = 5035

REQUIRED = ("CTRADER_CLIENT_ID", "CTRADER_CLIENT_SECRET", "CTRADER_REDIRECT_URI", "CTRADER_ENV")
OPTIONAL = ("CTRADER_ACCOUNT_ID", "CTRADER_TOKEN_FILE")
DEFAULT_TOKEN_FILE = "secrets/ctrader_tokens.json"


class SettingsError(ValueError):
    """File di impostazioni non valido; `errors` elenca i problemi trovati."""

    def __init__(self, path: Path, errors: list[str]) -> None:
        super().__init__(f"{path} non valido:\n- " + "\n- ".join(errors))
        self.errors = errors


@dataclass(frozen=True, slots=True)
class CtraderSettings:
    app: OAuthApp
    env: str  # demo | live
    account_id: int | None  # ctidTraderAccountId; None finché non è stato letto dall'API
    token_file: Path

    @property
    def host(self) -> str:
        return HOSTS[self.env]


def read_env_file(path: Path) -> dict[str, str]:
    """Righe `CHIAVE=valore`; ignora righe vuote e commenti, toglie le virgolette esterne."""
    values: dict[str, str] = {}
    errors: list[str] = []
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            errors.append(f"riga {n}: attesa la forma CHIAVE=valore")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in values:
            errors.append(f"riga {n}: {key} ripetuta")
        values[key] = value
    if errors:
        raise SettingsError(Path(path), errors)
    return values


def load_settings(path: Path, *, base_dir: Path | None = None) -> CtraderSettings:
    """Carica e valida le impostazioni. Un `CTRADER_TOKEN_FILE` relativo si risolve rispetto a `base_dir`
    (default: la cartella corrente)."""
    path = Path(path)
    values = read_env_file(path)
    errors = [f"chiave sconosciuta: {k}" for k in values if k not in REQUIRED + OPTIONAL]
    errors += [f"{k} mancante o vuota" for k in REQUIRED if not values.get(k)]
    env = values.get("CTRADER_ENV", "")
    if env and env not in HOSTS:
        errors.append(f"CTRADER_ENV deve essere uno di {sorted(HOSTS)}, non {env!r}")
    account_id: int | None = None
    if raw_id := values.get("CTRADER_ACCOUNT_ID", ""):
        if raw_id.isdigit() and int(raw_id) > 0:
            account_id = int(raw_id)
        else:
            errors.append(f"CTRADER_ACCOUNT_ID deve essere un intero positivo, non {raw_id!r}")
    if errors:
        raise SettingsError(path, errors)
    token_file = Path(values.get("CTRADER_TOKEN_FILE") or DEFAULT_TOKEN_FILE)
    if not token_file.is_absolute():
        token_file = (base_dir or Path.cwd()) / token_file
    app = OAuthApp(
        client_id=values["CTRADER_CLIENT_ID"],
        client_secret=values["CTRADER_CLIENT_SECRET"],
        redirect_uri=values["CTRADER_REDIRECT_URI"],
    )
    return CtraderSettings(app=app, env=env, account_id=account_id, token_file=token_file)
