"""`ctrader-login` end-to-end senza rete: browser simulato, finto endpoint del token, token su disco."""

import io
import stat
from pathlib import Path

from fake_oauth import (
    CLIENT_ID,
    CLIENT_SECRET,
    CODE,
    SECRETS,
    FakeTokenEndpoint,
    app,
    free_port,
    redirect_later,
    token_body,
)

from ctrader_async.settings import CtraderSettings
from ctrader_async.tokens import TokenStore
from tradingsys.cli.ctrader_login import main, run_login


def _settings(tmp_path: Path) -> CtraderSettings:
    redirect = f"http://localhost:{free_port()}/callback"
    return CtraderSettings(app(redirect), "demo", None, tmp_path / "secrets" / "ctrader_tokens.json")


def _browser(query: str, opened: list[str]):
    """Browser finto: registra l'URL di autorizzazione e segue il redirect come farebbe cTrader."""

    def open_browser(url: str) -> None:
        opened.append(url)
        redirect_uri = url.split("redirect_uri=")[1].split("&")[0].replace("%3A", ":").replace("%2F", "/")
        redirect_later(f"{redirect_uri}?{query}")

    return open_browser


def test_login_saves_tokens_and_prints_no_secret(tmp_path):
    settings = _settings(tmp_path)
    endpoint = FakeTokenEndpoint([(200, token_body())])
    out, opened = io.StringIO(), []
    code = run_login(settings, open_browser=_browser(f"code={CODE}", opened), fetch=endpoint, out=out)
    assert code == 0, out.getvalue()
    assert len(opened) == 1 and endpoint.calls[0]["code"] == CODE
    pair = TokenStore(settings.token_file).load(CLIENT_ID)
    assert pair is not None and pair.scope == "trading"
    assert stat.S_IMODE(settings.token_file.stat().st_mode) == 0o600
    assert not any(s in out.getvalue() for s in SECRETS)


def test_existing_tokens_need_force(tmp_path):
    settings = _settings(tmp_path)
    settings.token_file.parent.mkdir(mode=0o700)
    settings.token_file.write_text("coppia in uso")
    opened: list[str] = []
    out = io.StringIO()
    assert run_login(settings, open_browser=opened.append, fetch=FakeTokenEndpoint([]), out=out) == 2
    assert opened == [] and settings.token_file.read_text() == "coppia in uso"
    assert "--force" in out.getvalue()


def test_force_replaces_existing_tokens(tmp_path):
    settings = _settings(tmp_path)
    store = TokenStore(settings.token_file)
    run_login(
        settings, open_browser=_browser(f"code={CODE}", []), fetch=FakeTokenEndpoint([(200, token_body())])
    )
    endpoint = FakeTokenEndpoint([(200, token_body("access-2", "refresh-2"))])
    assert run_login(settings, force=True, open_browser=_browser(f"code={CODE}", []), fetch=endpoint) == 0
    assert store.load(CLIENT_ID).access_token == "access-2"


def test_denied_authorization_saves_nothing(tmp_path):
    settings = _settings(tmp_path)
    out = io.StringIO()
    browser = _browser("error=access_denied", [])
    assert run_login(settings, open_browser=browser, fetch=FakeTokenEndpoint([]), out=out) == 1
    assert not settings.token_file.exists()
    assert "access_denied" in out.getvalue()


def test_rejected_code_saves_nothing(tmp_path):
    settings = _settings(tmp_path)
    endpoint = FakeTokenEndpoint([(200, token_body(errorCode="INVALID_GRANT", description="codice scaduto"))])
    out = io.StringIO()
    assert run_login(settings, open_browser=_browser(f"code={CODE}", []), fetch=endpoint, out=out) == 1
    assert not settings.token_file.exists()
    assert CLIENT_SECRET not in out.getvalue()


def test_main_without_env_file(tmp_path, capsys):
    assert main(["--env-file", str(tmp_path / "manca.env"), "--no-browser"]) == 1
    assert "ctrader.example.env" in capsys.readouterr().out
