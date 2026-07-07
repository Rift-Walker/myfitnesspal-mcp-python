"""
Token-based authentication for the MyFitnessPal MCP server.

One-time setup: run `mfp-mcp-auth`, which prompts for your MyFitnessPal
credentials, performs the OAuth login, and saves the resulting session
(access/refresh tokens and user id -- never the password) to disk. The MCP
server then loads that session and refreshes it automatically, so no
credentials need to live in the MCP client config or environment.

Token file: ~/.mfp-mcp/session.json by default, overridable with the
MFP_TOKEN_PATH environment variable or the CLI's --token-path flag.
"""

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path
from typing import Optional

from mfp_api import MfpClient
from mfp_api.auth import MfpAuth, MfpAuthError, MfpSession, TokenInfo

SESSION_FILE_VERSION = 1


def default_token_path() -> Path:
    env = os.environ.get("MFP_TOKEN_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".mfp-mcp" / "session.json"


def save_session(session: MfpSession, path: Optional[Path] = None) -> Path:
    path = path or default_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SESSION_FILE_VERSION,
        "domain_user_id": session.domain_user_id,
        "user_token": {
            "access_token": session.user_token.access_token,
            "refresh_token": session.user_token.refresh_token,
            "id_token": session.user_token.id_token,
            "expires_at": session.user_token.expires_at,
        },
    }
    # Owner-only permissions; best-effort on Windows, where POSIX modes only
    # map onto the read-only bit.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def load_session(path: Optional[Path] = None) -> Optional[MfpSession]:
    """Load the stored session, or return None if no session file exists."""
    path = path or default_token_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        token = payload["user_token"]
        return MfpSession(
            user_token=TokenInfo(
                access_token=token["access_token"],
                refresh_token=token.get("refresh_token"),
                id_token=token.get("id_token"),
                expires_at=float(token["expires_at"]),
            ),
            domain_user_id=payload["domain_user_id"],
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Session file {path} is corrupt ({exc}). Run `mfp-mcp-auth --force` to recreate it."
        ) from exc


class PersistingAuth(MfpAuth):
    """MfpAuth that writes rotated tokens back to the session file, so the
    stored refresh token never goes stale while the server runs."""

    def __init__(self, token_path: Path):
        super().__init__()
        self._token_path = token_path

    def refresh(self, session: MfpSession) -> MfpSession:
        new_session = super().refresh(session)
        save_session(new_session, self._token_path)
        return new_session


def load_client(token_path: Optional[Path] = None) -> Optional[MfpClient]:
    """
    Build an MfpClient from the stored session, or return None if no session
    file exists. If the stored access token has already expired, refresh it
    eagerly so a dead refresh token surfaces here as a clear error instead of
    failing inside the first tool call.
    """
    path = token_path or default_token_path()
    session = load_session(path)
    if session is None:
        return None
    auth = PersistingAuth(path)
    if session.user_token.expired:
        try:
            session = auth.refresh(session)
        except MfpAuthError as exc:
            auth.close()
            raise RuntimeError(
                f"Stored MyFitnessPal session at {path} could not be refreshed ({exc}). "
                "Run `mfp-mcp-auth --force` to log in again."
            ) from exc
    return MfpClient(session, auth)


# ============================================================================
# `mfp-mcp-auth` CLI
# ============================================================================


def _verify(token_path: Path) -> int:
    try:
        session = load_session(token_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if session is None:
        print(f"No session file at {token_path}. Run `mfp-mcp-auth` to create one.", file=sys.stderr)
        return 1
    auth = PersistingAuth(token_path)
    try:
        auth.refresh(session)
    except MfpAuthError as exc:
        print(
            f"Stored session is no longer valid ({exc}). Run `mfp-mcp-auth --force` to log in again.",
            file=sys.stderr,
        )
        return 1
    finally:
        auth.close()
    print(f"Stored session at {token_path} is valid (MFP user id {session.domain_user_id}).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mfp-mcp-auth",
        description=(
            "One-time login for the MyFitnessPal MCP server. Exchanges your "
            "credentials for OAuth tokens and stores them on disk; your password "
            "is never saved. Credentials are prompted interactively, or read from "
            "MFP_USERNAME/MFP_PASSWORD if set."
        ),
    )
    parser.add_argument(
        "--token-path",
        type=Path,
        default=None,
        help=f"Where to store the session (default: {default_token_path()})",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check that the stored session still works instead of logging in.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Log in again even if a session file already exists.",
    )
    args = parser.parse_args()
    token_path = args.token_path or default_token_path()

    if args.verify:
        sys.exit(_verify(token_path))

    if token_path.exists() and not args.force:
        print(f"A session already exists at {token_path}.")
        print("Use --verify to check it, or --force to log in again.")
        sys.exit(1)

    username = os.environ.get("MFP_USERNAME") or input("MyFitnessPal username/email: ").strip()
    password = os.environ.get("MFP_PASSWORD") or getpass.getpass("MyFitnessPal password: ")
    if not username or not password:
        print("Username and password are required.", file=sys.stderr)
        sys.exit(1)

    print("Logging in to MyFitnessPal...")
    auth = MfpAuth()
    try:
        session = auth.login(username, password)
    except MfpAuthError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        auth.close()

    path = save_session(session, token_path)
    print(f"Success. OAuth session saved to {path} (MFP user id {session.domain_user_id}).")
    print("The MCP server will authenticate from this file -- no credentials needed in your MCP config.")


if __name__ == "__main__":
    main()
