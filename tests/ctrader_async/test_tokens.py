"""Archivio dei token: permessi 600, scrittura atomica, lock fra processi, refresh senza perdite (T6)."""

import json
import os
import stat

import pytest
from fake_oauth import ACCESS, CLIENT_ID, REFRESH, FakeTokenEndpoint, app, token_body

from ctrader_async import tokens
from ctrader_async.oauth import OAuthError, TokenPair
from ctrader_async.tokens import TokenLockBusy, TokenStore, TokenStoreError, refresh_stored

NOW = 1_790_000_000.0
PAIR = TokenPair(ACCESS, REFRESH, NOW + 2_628_000, "trading")


@pytest.fixture
def store(tmp_path):
    return TokenStore(tmp_path / "secrets" / "ctrader_tokens.json")


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_roundtrip_with_private_permissions(store):
    store.save(PAIR, CLIENT_ID)
    assert store.load(CLIENT_ID) == PAIR
    assert _mode(store.path) == 0o600
    assert _mode(store.path.parent) == 0o700


def test_missing_file_loads_none(store):
    assert store.load(CLIENT_ID) is None


def test_file_readable_by_others_is_refused(store):
    store.save(PAIR, CLIENT_ID)
    store.path.chmod(0o644)
    with pytest.raises(TokenStoreError, match="chmod 600"):
        store.load(CLIENT_ID)


def test_tokens_of_another_app_are_refused(store):
    store.save(PAIR, CLIENT_ID)
    with pytest.raises(TokenStoreError, match="altra applicazione"):
        store.load("9999_altra")


@pytest.mark.parametrize(
    "content",
    [
        "non json",
        "[]",
        "{}",
        json.dumps({"schema": 2}),
        json.dumps(
            {
                "schema": 1,
                "client_id": CLIENT_ID,
                "scope": "trading",
                "token_type": "bearer",
                "access_token": "",
                "refresh_token": REFRESH,
                "expires_at": NOW,
            }
        ),
        json.dumps(
            {
                "schema": 1,
                "client_id": CLIENT_ID,
                "scope": "trading",
                "token_type": "bearer",
                "access_token": ACCESS,
                "refresh_token": REFRESH,
                "expires_at": "domani",
            }
        ),
    ],
)
def test_corrupt_file_is_refused(store, content):
    store.path.parent.mkdir(mode=0o700)
    store.path.write_text(content)
    store.path.chmod(0o600)
    with pytest.raises(TokenStoreError):
        store.load(CLIENT_ID)


def test_failed_write_keeps_previous_file(store, monkeypatch):
    store.save(PAIR, CLIENT_ID)
    before = store.path.read_bytes()

    def boom(src, dst):
        raise OSError("disco pieno")

    monkeypatch.setattr(tokens.os, "replace", boom)
    with pytest.raises(OSError, match="disco pieno"):
        store.save(TokenPair("a2", "r2", NOW, "trading"), CLIENT_ID)
    assert store.path.read_bytes() == before
    assert sorted(p.name for p in store.path.parent.iterdir()) == [store.path.name]


def test_lock_is_exclusive(store):
    with store.lock(), pytest.raises(TokenLockBusy), store.lock():
        pass
    with store.lock():  # rilasciato all'uscita
        pass


def test_refresh_stored_replaces_pair(store):
    store.save(PAIR, CLIENT_ID)
    endpoint = FakeTokenEndpoint([(200, token_body("access-2", "refresh-2", expires_in=1000))])
    new = refresh_stored(app(), store, fetch=endpoint, clock=lambda: NOW)
    assert endpoint.calls[0]["refresh_token"] == REFRESH
    assert store.load(CLIENT_ID) == new == TokenPair("access-2", "refresh-2", NOW + 1000, "trading")


def test_failed_refresh_keeps_file(store):
    store.save(PAIR, CLIENT_ID)
    endpoint = FakeTokenEndpoint([(400, token_body(errorCode="INVALID_GRANT"))])
    with pytest.raises(OAuthError):
        refresh_stored(app(), store, fetch=endpoint)
    assert store.load(CLIENT_ID) == PAIR


def test_refresh_without_tokens_asks_for_login(store):
    with pytest.raises(TokenStoreError, match="login"):
        refresh_stored(app(), store, fetch=FakeTokenEndpoint([]))


def test_refresh_while_locked_does_not_call_endpoint(store):
    store.save(PAIR, CLIENT_ID)
    endpoint = FakeTokenEndpoint([])
    with store.lock(), pytest.raises(TokenLockBusy):
        refresh_stored(app(), store, fetch=endpoint)
    assert endpoint.calls == []


def test_refresh_saved_failure_says_new_login_needed(store, monkeypatch):
    """Il caso peggiore di T6: la coppia vecchia è già invalidata, la nuova non è salvata."""
    store.save(PAIR, CLIENT_ID)
    endpoint = FakeTokenEndpoint([(200, token_body("access-2", "refresh-2"))])
    monkeypatch.setattr(tokens.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("disco pieno")))
    with pytest.raises(TokenStoreError, match="nuovo login") as info:
        refresh_stored(app(), store, fetch=endpoint)
    assert "access-2" not in str(info.value) and "refresh-2" not in str(info.value)


def test_lock_file_is_private(store):
    with store.lock():
        pass
    lock = store.path.with_name(store.path.name + ".lock")
    assert _mode(lock) == 0o600
    assert not os.access(store.path, os.F_OK)  # il lock non crea il file dei token
