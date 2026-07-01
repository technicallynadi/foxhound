"""Security tests for the Python sandbox upload server.

Covers the two hardening fixes in docker/sandbox-runtime-api/upload_server.py:
  - tar extraction rejects path traversal / links (no writes outside APP_DIR)
  - the /upload + /env endpoints fail closed without a valid shared token

The upload server is stdlib-only and lives under docker/ (no package), so it is
loaded here by file path. Tests are hermetic: in-memory tarballs, tmp dirs, and
monkeypatched env — no network.
"""

import importlib.util
import io
import pathlib
import tarfile

import pytest

_UPLOAD_SERVER_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "docker" / "sandbox-runtime-api" / "upload_server.py"
)


@pytest.fixture(scope="module")
def upload_server():
    spec = importlib.util.spec_from_file_location("upload_server", _UPLOAD_SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_targz(members: dict[str, bytes]) -> io.BytesIO:
    """Build an in-memory .tar.gz from {arcname: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# Tar path traversal
# ---------------------------------------------------------------------------


def test_safe_extract_rejects_path_traversal(upload_server, tmp_path):
    """A member with a ../ escape is rejected and nothing is written outside."""
    dest = tmp_path / "app"
    dest.mkdir()
    outside = tmp_path / "etc"
    outside.mkdir()

    targz = _make_targz({"../../etc/evil": b"pwned"})

    with tarfile.open(fileobj=targz, mode="r:gz") as tar:
        with pytest.raises(ValueError):
            upload_server._safe_extract(tar, str(dest))

    # Nothing escaped the destination directory.
    assert not (outside / "evil").exists()
    assert list(dest.iterdir()) == []


def test_safe_extract_rejects_absolute_path(upload_server, tmp_path):
    """A member with an absolute path is rejected."""
    dest = tmp_path / "app"
    dest.mkdir()

    targz = _make_targz({"/etc/evil": b"pwned"})

    with tarfile.open(fileobj=targz, mode="r:gz") as tar:
        with pytest.raises(ValueError):
            upload_server._safe_extract(tar, str(dest))


def test_safe_extract_allows_normal_members(upload_server, tmp_path):
    """A well-formed archive extracts inside the destination directory."""
    dest = tmp_path / "app"
    dest.mkdir()

    targz = _make_targz({"main.py": b"print('ok')", "pkg/mod.py": b"x = 1"})

    with tarfile.open(fileobj=targz, mode="r:gz") as tar:
        upload_server._safe_extract(tar, str(dest))

    assert (dest / "main.py").read_bytes() == b"print('ok')"
    assert (dest / "pkg" / "mod.py").read_bytes() == b"x = 1"


# ---------------------------------------------------------------------------
# Upload/env authentication (fail closed)
# ---------------------------------------------------------------------------


def test_auth_fails_closed_without_token(upload_server, monkeypatch):
    """With SANDBOX_UPLOAD_TOKEN unset, every request is rejected."""
    monkeypatch.delenv("SANDBOX_UPLOAD_TOKEN", raising=False)

    assert upload_server._is_authorized({"Authorization": "Bearer anything"}) is False
    assert upload_server._is_authorized({"X-Sandbox-Token": "anything"}) is False
    assert upload_server._is_authorized({}) is False


def test_auth_fails_closed_with_empty_token(upload_server, monkeypatch):
    """An empty configured token is treated as unset (fail closed)."""
    monkeypatch.setenv("SANDBOX_UPLOAD_TOKEN", "")

    assert upload_server._is_authorized({"Authorization": "Bearer "}) is False


def test_auth_accepts_correct_bearer_token(upload_server, monkeypatch):
    """A matching bearer token passes the auth check."""
    monkeypatch.setenv("SANDBOX_UPLOAD_TOKEN", "s3cret-token")

    assert upload_server._is_authorized({"Authorization": "Bearer s3cret-token"}) is True


def test_auth_accepts_correct_x_sandbox_token(upload_server, monkeypatch):
    """A matching X-Sandbox-Token header passes the auth check."""
    monkeypatch.setenv("SANDBOX_UPLOAD_TOKEN", "s3cret-token")

    assert upload_server._is_authorized({"X-Sandbox-Token": "s3cret-token"}) is True


def test_auth_rejects_wrong_token(upload_server, monkeypatch):
    """A non-matching token is rejected even when a token is configured."""
    monkeypatch.setenv("SANDBOX_UPLOAD_TOKEN", "s3cret-token")

    assert upload_server._is_authorized({"Authorization": "Bearer wrong"}) is False
    assert upload_server._is_authorized({"X-Sandbox-Token": "wrong"}) is False
