import ast
import json
import runpy
import sys
import tomllib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from odsbox_cli.connections import Config
from odsbox_cli.database import Database, Session
from odsbox_cli.script_starter import generate, open_project, query_snapshot


@pytest.mark.parametrize("mode", ["basic", "m2m", "oidc"])
@pytest.mark.parametrize(
    "query", [None, {"Measurement": {"flag": True, "missing": None}, "$options": {"$rowlimit": 3}}]
)
def test_generated_project_compiles_and_executes(tmp_path, mode, query):
    config = Config(
        'Test "unicode \u00e4"\nproject',
        'https://example.invalid/a?x="q"',
        mode,
        username="user",
        token_endpoint="https://login.invalid/token",
        client_id="client",
        scope=["scope-a", "scope-b"],
        redirect_uri="http://127.0.0.1:12345",
        webfinger_path_prefix="/custom",
        redirect_url_allow_insecure=True,
        verify_certificate=False,
        context_variables={"LANGUAGE": "en", "quote": "'\"\n"},
    )
    saved = query_snapshot(query) if query else None
    with patch("odsbox_cli.script_starter.open_project") as opener:
        folder = generate(config, saved, tmp_path, open_folder=False)
    opener.assert_not_called()
    files = {str(path.relative_to(folder)).replace("\\", "/") for path in folder.rglob("*") if path.is_file()}
    assert files == {"pyproject.toml", "script.py", "README.md", ".vscode/mcp.json"}
    manifest = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))
    assert "odsbox-cli" not in repr(manifest)
    assert manifest["project"]["requires-python"] == ">=3.14"
    assert "odsbox[oidc]>=1.10.1" in manifest["project"]["dependencies"]
    source = (folder / "script.py").read_text(encoding="utf-8")
    ast.parse(source)
    environment = json.loads((folder / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    env = environment["servers"]["ods-mcp"]["env"]
    assert env["ODSBOX_MCP_MODE"] == mode and env["ODSBOX_MCP_VERIFY"] == "false"
    assert not any(word in key.lower() for key in env for word in ("password", "secret", "token_endpoint_secret"))
    factory = MagicMock()
    keyring = MagicMock()
    keyring.get_password.return_value = "runtime-credential-never-export"
    connection = MagicMock()
    connection.__enter__.return_value = connection
    getattr(factory, mode).return_value = connection
    connection.query.return_value = pd.DataFrame({"value": [1, 2]})
    connection.model.return_value.entities = {
        "e": SimpleNamespace(aid=1, name="Measurement", base_name="AoMeasurement")
    }
    with (
        patch.dict(sys.modules, {"keyring": keyring}),
        patch("odsbox.con_i_factory.ConIFactory", factory),
    ):
        runpy.run_path(str(folder / "script.py"), run_name="__main__")
    kwargs = getattr(factory, mode).call_args.kwargs
    assert kwargs["url"] == config.url
    assert kwargs["context_variables"] == config.context_variables
    assert kwargs["verify_certificate"] is False
    if mode == "basic":
        assert kwargs["password"] == "runtime-credential-never-export" and kwargs["username"] == "user"
    elif mode == "m2m":
        assert kwargs["scope"] == config.scope and kwargs["client_secret"] == "runtime-credential-never-export"
        assert env["ODSBOX_MCP_M2M_TOKEN_ENDPOINT"] == config.token_endpoint
    else:
        assert kwargs["webfinger_path_prefix"] == "/custom"
        assert kwargs["redirect_url_allow_insecure"] is True
        keyring.get_password.assert_not_called()
    if mode != "oidc":
        keyring.get_password.assert_called_once_with("ods-pilot", config.account)
    if query:
        connection.query.assert_called_once_with(query)
    else:
        connection.query.assert_not_called()
        connection.model.assert_called_once()
    connection.__exit__.assert_called_once()
    assert all(
        "runtime-credential-never-export" not in path.read_text(encoding="utf-8")
        for path in folder.rglob("*")
        if path.is_file()
    )


def test_missing_generated_credential_fails_before_connection(tmp_path):
    config = Config("Demo", "https://example.invalid", "basic", username="Demo")
    folder = generate(config, None, tmp_path, open_folder=False)
    with (
        patch("keyring.get_password", return_value=None),
        patch("odsbox.con_i_factory.ConIFactory.basic") as factory,
        pytest.raises(RuntimeError, match="keyring"),
    ):
        runpy.run_path(str(folder / "script.py"), run_name="__main__")
    factory.assert_not_called()


def test_keyring_setup_uses_literal_powershell_quoting(tmp_path):
    config = Config("Demo", "https://example.invalid", "basic", username="O'User $name")
    folder = generate(config, None, tmp_path, open_folder=False)
    readme = (folder / "README.md").read_text()
    assert "uv run python -m keyring set ods-pilot 'https://example.invalid::O''User $name'" in readme


@pytest.mark.parametrize(
    "query",
    [
        {"x": {1: "not-string"}},
        {"x": (1, 2)},
        {"x": float("nan")},
        {"x": pd.Timestamp("2020")},
        [],
        "not json",
        '{"x": Infinity}',
    ],
)
def test_nonportable_query_rejected(query):
    with pytest.raises((ValueError, TypeError)):
        query_snapshot(query)


def test_query_snapshot_lifecycle_and_generation(session, connection, tmp_path):
    db = Database(session, lambda frame: None)
    ids = [1, 2]
    query = {"Measurement": {"ids": ids, "ok": True, "missing": None}}
    original = deepcopy(query)
    db.find(query)
    ids.append(3)
    saved = session.last_query
    assert json.loads(saved) == original
    connection.query.side_effect = ValueError("failed")
    with pytest.raises(ValueError):
        db.find({"failed": {}})
    assert session.last_query == saved
    connection.query.side_effect = None
    db.model.find()
    assert session.last_query == saved
    with (
        patch("keyring.get_password", side_effect=AssertionError("generation accessed credentials")),
        patch.object(session.registry, "get", side_effect=AssertionError("generation reread registry")),
        patch.object(connection, "query", side_effect=AssertionError("generation issued query")),
        patch.object(connection, "model", side_effect=AssertionError("generation read model")),
    ):
        folder = db.script_starter(tmp_path, open_folder=False)
    assert folder.parent == tmp_path
    assert "ids" in (folder / "script.py").read_text()
    session.use("Demo")
    assert session.last_query is None and session.query_export_error is None
    db.find('{"Measurement": {"name": "new"}}')
    db.reconnect()
    assert session.last_query is None
    session.disconnect()
    assert session.config is None
    with pytest.raises(ValueError, match="Not connected"):
        db.script_starter(tmp_path)


def test_successful_nonportable_find_does_not_fail(session, connection, tmp_path):
    frames: list[pd.DataFrame] = []
    db = Database(session, frames.append)
    query = {"Measurement": {"date": pd.Timestamp("2020")}}
    assert db.find(query) is connection.query.return_value
    assert frames[-1] is connection.query.return_value
    with pytest.raises(ValueError, match="not JSON-portable"):
        db.script_starter(tmp_path, open_folder=False)
    assert list(tmp_path.iterdir())  # The fixture's registry already exists.
    assert not list(tmp_path.glob("demo-*"))
    db.find({"Measurement": {}})
    assert session.query_export_error is None


def test_configuration_snapshot_and_failed_replacement(session, connection, tmp_path):
    config = session.config
    db = Database(session, lambda frame: None)
    db.find({"Measurement": {}})
    previous = session.last_query
    broken = MagicMock()
    broken.model.side_effect = ValueError("bad model")
    session.factory = lambda value: broken
    with pytest.raises(ValueError):
        session.use("Demo")
    assert session.config is config and session.last_query == previous
    with patch.object(session.registry, "get", return_value=replace(config, url="https://changed.invalid")):
        folder = db.script_starter(tmp_path, open_folder=False)
    assert "changed.invalid" not in (folder / "script.py").read_text()
    config.context_variables["LANGUAGE"] = "old"
    with patch.object(session.registry, "get", return_value=config):
        session.factory = lambda value: value.context_variables.update({"LANGUAGE": "mutated"}) or connection
        session.use("Demo")
    assert session.config.context_variables["LANGUAGE"] == "old"


def test_collision_and_existing_files(tmp_path):
    config = Config("CON", "https://example.invalid", "oidc", client_id="c")
    with patch("odsbox_cli.script_starter.datetime") as clock:
        clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
        first = generate(config, None, tmp_path, open_folder=False)
        second = generate(config, None, tmp_path, open_folder=False)
    assert first != second and second.name.endswith("-1")
    marker = first / "keep.txt"
    marker.write_text("keep")
    assert marker.read_text() == "keep"


def test_partial_write_cleanup(tmp_path):
    config = Config("Demo", "https://example.invalid", "basic", username="u")
    original = Path.open

    def fail_script(path, *args, **kwargs):
        if path.name == "script.py":
            raise PermissionError("test denied")
        return original(path, *args, **kwargs)

    keep = tmp_path / "existing"
    keep.mkdir()
    with patch.object(Path, "open", fail_script), pytest.raises(PermissionError):
        generate(config, None, tmp_path, open_folder=False)
    assert list(tmp_path.iterdir()) == [keep]


def test_cleanup_failure_does_not_mask_write_error(tmp_path):
    config = Config("Demo", "url", "oidc")
    original = Path.open

    def fail_script(path, *args, **kwargs):
        if path.name == "script.py":
            raise PermissionError("original write error")
        return original(path, *args, **kwargs)

    with (
        patch.object(Path, "open", fail_script),
        patch.object(Path, "unlink", side_effect=PermissionError("cleanup error")),
        pytest.warns(UserWarning, match="Could not remove"),
        pytest.raises(PermissionError, match="original write error"),
    ):
        generate(config, None, tmp_path, open_folder=False)


def test_repeated_and_cyclic_queries(session, connection, tmp_path):
    db = Database(session, lambda frame: None)
    cyclic: dict[str, object] = {}
    cyclic["cycle"] = cyclic
    assert db.find(cyclic) is connection.query.return_value
    with pytest.raises(ValueError, match="not JSON-portable"):
        db.script_starter(tmp_path, open_folder=False)
    db.find({"Measurement": {}})
    saved = session.last_query
    connection.query.side_effect = ValueError("read failed")
    with pytest.raises(ValueError, match="read failed"):
        db.find({"Measurement": {"time": pd.Timestamp("2020")}})
    assert session.last_query == saved and session.query_export_error is None


@pytest.mark.parametrize("platform,command", [("darwin", "open"), ("linux", "xdg-open")])
def test_folder_open_platform_fallback(tmp_path, platform, command):
    with (
        patch("shutil.which", return_value=None),
        patch("odsbox_cli.script_starter.sys.platform", platform),
        patch("subprocess.run") as run,
    ):
        open_project(tmp_path)
    run.assert_called_once_with([command, str(tmp_path)], check=True, timeout=10)


def test_windows_folder_open(tmp_path):
    with (
        patch("shutil.which", return_value=None),
        patch("odsbox_cli.script_starter.sys.platform", "win32"),
        patch("os.startfile", create=True) as start,
    ):
        open_project(tmp_path)
    start.assert_called_once_with(str(tmp_path))


def test_invalid_mode_and_query_create_nothing(tmp_path):
    target = tmp_path / "absent"
    for config, query in [
        (Config("ATFX", "a.atfx", "atfx"), None),
        (Config("Demo", "url", "basic", username="u"), "invalid json"),
    ]:
        with pytest.raises(ValueError):
            generate(config, query, target, open_folder=False)
    assert not target.exists()


def test_folder_opening(tmp_path):
    with patch("shutil.which", return_value="code"), patch("subprocess.run") as run:
        open_project(tmp_path)
    run.assert_called_once_with(["code", str(tmp_path)], check=True, timeout=10)
    with (
        patch("shutil.which", return_value=None),
        patch("odsbox_cli.script_starter.sys.platform", "linux"),
        patch("subprocess.run") as run,
    ):
        open_project(tmp_path)
    run.assert_called_once_with(["xdg-open", str(tmp_path)], check=True, timeout=10)
    with (
        patch("shutil.which", return_value="code"),
        patch("subprocess.run", side_effect=OSError("cannot open")),
        patch("os.startfile", side_effect=OSError("cannot open"), create=True),
        pytest.warns(UserWarning) as warnings,
    ):
        open_project(tmp_path)
    assert len(warnings) == 2 and "Project created at" in str(warnings[-1].message)
    with patch("odsbox_cli.script_starter.open_project") as opener:
        folder = generate(Config("Demo", "url", "oidc"), None, tmp_path)
    opener.assert_called_once_with(folder)


def test_session_config_missing(registry, tmp_path):
    session = Session(registry)
    session.connection = MagicMock()
    with pytest.raises(ValueError, match="settings captured"):
        Database(session, lambda frame: None).script_starter(tmp_path)
