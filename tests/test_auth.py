"""
Unit tests for token-based auth (mfp_mcp.auth). No network, no creds.json.
"""

import time

import pytest
from mfp_api.auth import MfpAuth, MfpSession, TokenInfo

from mfp_mcp import auth as mcp_auth
from mfp_mcp import server


def make_session(expires_in: float = 3600) -> MfpSession:
    return MfpSession(
        user_token=TokenInfo(
            access_token="access-token",
            refresh_token="refresh-token",
            id_token="id-token",
            expires_at=time.time() + expires_in,
        ),
        domain_user_id="12345",
    )


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "session.json"
    session = make_session()
    assert mcp_auth.save_session(session, path) == path
    assert mcp_auth.load_session(path) == session


def test_session_file_contains_no_password(tmp_path):
    path = tmp_path / "session.json"
    mcp_auth.save_session(make_session(), path)
    content = path.read_text(encoding="utf-8").lower()
    assert "password" not in content
    assert "username" not in content


def test_load_missing_returns_none(tmp_path):
    assert mcp_auth.load_session(tmp_path / "nope.json") is None
    assert mcp_auth.load_client(tmp_path / "nope.json") is None


def test_load_corrupt_raises_with_fix_hint(tmp_path):
    path = tmp_path / "session.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="mfp-mcp-auth"):
        mcp_auth.load_session(path)


def test_expired_session_refreshes_and_persists(tmp_path, monkeypatch):
    path = tmp_path / "session.json"
    mcp_auth.save_session(make_session(expires_in=-60), path)

    rotated = make_session()
    rotated.user_token.access_token = "new-access-token"
    rotated.user_token.refresh_token = "new-refresh-token"
    monkeypatch.setattr(MfpAuth, "refresh", lambda self, session: rotated)

    client = mcp_auth.load_client(path)
    try:
        assert client is not None
        on_disk = mcp_auth.load_session(path)
        assert on_disk.user_token.access_token == "new-access-token"
        assert on_disk.user_token.refresh_token == "new-refresh-token"
    finally:
        client.close()


def test_fresh_session_loads_without_refresh(tmp_path, monkeypatch):
    path = tmp_path / "session.json"
    mcp_auth.save_session(make_session(), path)

    def boom(self, session):
        raise AssertionError("refresh should not be called for a fresh token")

    monkeypatch.setattr(MfpAuth, "refresh", boom)
    client = mcp_auth.load_client(path)
    try:
        assert client is not None
    finally:
        client.close()


def test_server_error_mentions_auth_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("MFP_TOKEN_PATH", str(tmp_path / "none.json"))
    monkeypatch.delenv("MFP_USERNAME", raising=False)
    monkeypatch.delenv("MFP_PASSWORD", raising=False)
    monkeypatch.setattr(server, "_client", None)
    with pytest.raises(RuntimeError, match="mfp-mcp-auth"):
        server.get_mfp_client()
