"""Impostazioni di `config/ctrader.env`: chiavi obbligatorie, sconosciute e valori non validi sono errori."""

from pathlib import Path

import pytest
from fake_oauth import CLIENT_ID, CLIENT_SECRET

from ctrader_async.settings import SettingsError, load_settings, read_env_file

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "ctrader.example.env"

VALID = f"""\
# commento
CTRADER_CLIENT_ID={CLIENT_ID}
CTRADER_CLIENT_SECRET="{CLIENT_SECRET}"
CTRADER_REDIRECT_URI=http://localhost:8765/callback
CTRADER_ENV=demo
CTRADER_ACCOUNT_ID=
CTRADER_TOKEN_FILE=secrets/ctrader_tokens.json
"""


def _write(tmp_path, text: str) -> Path:
    path = tmp_path / "ctrader.env"
    path.write_text(text)
    return path


def test_example_lists_every_key_and_is_incomplete():
    """Il modello committato contiene tutte le chiavi, ma senza credenziali non si carica."""
    assert set(read_env_file(EXAMPLE)) == {
        "CTRADER_CLIENT_ID",
        "CTRADER_CLIENT_SECRET",
        "CTRADER_REDIRECT_URI",
        "CTRADER_ENV",
        "CTRADER_ACCOUNT_ID",
        "CTRADER_TOKEN_FILE",
    }
    with pytest.raises(SettingsError) as info:
        load_settings(EXAMPLE)
    assert sorted(info.value.errors) == [
        "CTRADER_CLIENT_ID mancante o vuota",
        "CTRADER_CLIENT_SECRET mancante o vuota",
        "CTRADER_REDIRECT_URI mancante o vuota",
    ]


def test_valid_file_loads(tmp_path):
    s = load_settings(_write(tmp_path, VALID), base_dir=tmp_path)
    assert s.app.client_id == CLIENT_ID and s.app.client_secret == CLIENT_SECRET  # virgolette tolte
    assert s.env == "demo" and s.host == "demo.ctraderapi.com"
    assert s.account_id is None
    assert s.token_file == tmp_path / "secrets" / "ctrader_tokens.json"
    assert CLIENT_SECRET not in repr(s)


def test_account_id_is_parsed(tmp_path):
    s = load_settings(_write(tmp_path, VALID.replace("CTRADER_ACCOUNT_ID=", "CTRADER_ACCOUNT_ID=4123456")))
    assert s.account_id == 4123456


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        ("CTRADER_ENV=demo", "CTRADER_ENV=Demo", "CTRADER_ENV"),
        ("CTRADER_ACCOUNT_ID=", "CTRADER_ACCOUNT_ID=abc", "CTRADER_ACCOUNT_ID"),
        ("CTRADER_ACCOUNT_ID=", "CTRADER_ACCOUNT_ID=0", "CTRADER_ACCOUNT_ID"),
        ("CTRADER_ACCOUNT_ID=", "CTRADER_ACOUNT_ID=1", "sconosciuta"),
        ("# commento", "riga senza uguale", "CHIAVE=valore"),
        ("# commento", "CTRADER_ENV=live", "ripetuta"),
    ],
)
def test_invalid_values_are_errors(tmp_path, old, new, error):
    with pytest.raises(SettingsError, match=error):
        load_settings(_write(tmp_path, VALID.replace(old, new)))
