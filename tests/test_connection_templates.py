import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from odsbox_cli.cli import main
from odsbox_cli.connections import Config, generate_connection_template, portable_file
from odsbox_cli.help import help_text


@pytest.mark.parametrize("auth_type", ["basic", "m2m", "oidc"])
def test_template_round_trip(auth_type, tmp_path, registry):
    destination = tmp_path / "my server.ods-pilot.con.toml"
    assert generate_connection_template(auth_type, destination) == destination
    content = destination.read_bytes()
    assert b"\r" not in content
    data = tomllib.loads(content.decode("utf-8"))
    assert data["name"] == "my server"
    assert data["url"] == "https://ods.example.invalid/api"
    assert data["auth_type"] == auth_type
    assert data["verify_certificate"] is True
    assert data["context_variables"] == {}
    assert not ({"id", "password", "client_secret", "secret", "token"} & data.keys())
    common = {"name", "url", "auth_type", "verify_certificate", "context_variables"}
    mode_fields = {
        "basic": {"username"},
        "m2m": {"token_endpoint", "client_id", "scope"},
        "oidc": {"client_id", "redirect_uri", "webfinger_path_prefix", "redirect_url_allow_insecure"},
    }
    assert data.keys() == common | mode_fields[auth_type]
    defaults = Config("test", "https://example.invalid", auth_type)
    if auth_type == "oidc":
        assert data["redirect_uri"] == defaults.redirect_uri
        assert data["webfinger_path_prefix"] == defaults.webfinger_path_prefix
        assert data["redirect_url_allow_insecure"] is defaults.redirect_url_allow_insecure is False
    elif auth_type == "m2m":
        assert data["scope"] == []
        assert data["token_endpoint"].startswith("https://identity.example.invalid/")
    config = portable_file(destination)
    assert config == Config.parse({**data, "id": config.id})
    assert registry.import_configs([config]) == 1
    assert registry.get("my server").settings() == config.settings()
    assert registry.import_configs([config]) == 0


def test_edit_and_import_workflow(tmp_path, registry, monkeypatch, capsys):
    path = tmp_path / "my_server.ods-pilot.con.toml"
    assert main(["--generate-connection-template", "oidc", str(path)]) == 0
    output = capsys.readouterr().out
    assert str(path) in output
    assert f'odsbox-cli connections import "{path}"' in output
    path.write_text(
        path.read_text().replace("my_server", "Customer server").replace("YOUR_CLIENT_ID", "registered-client"),
        encoding="utf-8",
    )
    monkeypatch.setattr("odsbox_cli.cli.Registry", lambda: registry)
    assert main(["connections", "import", str(path)]) == 0
    assert "Imported 1 connection(s)" in capsys.readouterr().out
    assert registry.get("Customer server").client_id == "registered-client"


@pytest.mark.parametrize("auth_type", ["basic", "m2m", "oidc"])
def test_generation_has_no_external_side_effects(auth_type, tmp_path, monkeypatch):
    no_calls = MagicMock(side_effect=AssertionError("Generation must be local and standalone"))
    for symbol in ("Shell", "Registry"):
        monkeypatch.setattr(f"odsbox_cli.cli.{symbol}", no_calls)
    for symbol in ("connect", "secret_for", "read_registry"):
        monkeypatch.setattr(f"odsbox_cli.connections.{symbol}", no_calls)
    monkeypatch.setattr("odsbox_cli.connections.keyring.get_password", no_calls)
    monkeypatch.setattr("webbrowser.open", no_calls)
    destination = tmp_path / "new config.ODS-PILOT.CON.TOML"
    assert main(["--no-history", "--generate-connection-template", auth_type, str(destination)]) == 0
    assert portable_file(destination).auth_type == auth_type
    no_calls.assert_not_called()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["new config.ODS-PILOT.CON.TOML"]


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("my_server.ods-pilot.con.toml", "my_server"),
        ("lab.ods-pilot.con.toml", "lab"),
        ("My server.extra.parts.ODS-PILOT.CON.TOML", "My server"),
        ("lab..ods-pilot.con.toml", "lab"),
    ],
)
def test_name_uses_filename_before_first_dot(filename, expected, tmp_path):
    directory = tmp_path / "parent.with.dots"
    directory.mkdir()
    path = directory / filename
    generate_connection_template("oidc", path)
    assert portable_file(path).name == expected


@pytest.mark.parametrize("filename", [".ods-pilot.con.toml", " .ods-pilot.con.toml"])
def test_empty_derived_name_is_rejected(filename, tmp_path):
    path = tmp_path / filename
    with pytest.raises(ValueError, match="non-empty name"):
        generate_connection_template("oidc", path)
    assert not path.exists()


@pytest.mark.parametrize("auth_type", ["atfx", "unknown", "OIDC", ""])
def test_unknown_authentication(auth_type, tmp_path):
    path = tmp_path / "new.ods-pilot.con.toml"
    with pytest.raises(ValueError, match="basic, m2m or oidc"):
        generate_connection_template(auth_type, path)
    assert not path.exists()


@pytest.mark.parametrize(
    "name",
    ["new.json", "new.con", "new", "new.toml", "new.con.toml", "new.ods-pilot.toml", "new.ods-pilot.con.toml.txt"],
)
def test_wrong_suffix(name, tmp_path):
    path = tmp_path / name
    with pytest.raises(ValueError, match=r"\.ods-pilot\.con\.toml"):
        generate_connection_template("oidc", path)
    assert not path.exists()


def test_existing_file_and_directory_are_not_overwritten(tmp_path):
    path = tmp_path / "existing.ods-pilot.con.toml"
    original = b"customer settings\x00\n"
    path.write_bytes(original)
    with pytest.raises(FileExistsError):
        generate_connection_template("oidc", path)
    assert path.read_bytes() == original
    directory = tmp_path / "directory.ods-pilot.con.toml"
    directory.mkdir()
    with pytest.raises(OSError):
        generate_connection_template("basic", directory)
    assert directory.is_dir()


def test_missing_parent_is_not_created(tmp_path):
    path = tmp_path / "absent" / "new.ods-pilot.con.toml"
    with pytest.raises(FileNotFoundError):
        generate_connection_template("m2m", path)
    assert not path.parent.exists()


def test_symlink_is_not_overwritten(tmp_path):
    target = tmp_path / "customer.ods-pilot.con.toml"
    target.write_text("customer data")
    destination = tmp_path / "link.ods-pilot.con.toml"
    try:
        destination.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")
    with pytest.raises(FileExistsError):
        generate_connection_template("basic", destination)
    assert destination.is_symlink()
    assert target.read_text() == "customer data"
    target.unlink()
    with pytest.raises(FileExistsError):
        generate_connection_template("basic", destination)
    assert destination.is_symlink()


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--generate-connection-template", "oidc"], "expected 2 arguments"),
        (["--generate-connection-template", "unknown", "new.toml"], "basic, m2m or oidc"),
        (["--generate-connection-template", "basic", "new.json"], ".ods-pilot.con.toml"),
        (["--generate-connection-template", "basic", "new.toml", "--script", "start.ods"], "not allowed"),
        (["--script", "start.ods", "--generate-connection-template", "oidc", "new.toml"], "not allowed"),
        (["--generate-connection-template", "oidc", "new.toml", "connections", "list"], "cannot be combined"),
    ],
)
def test_invalid_cli_usage(arguments, message, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(arguments) == 1
    captured = capsys.readouterr()
    assert message in captured.err
    assert not captured.out
    assert list(tmp_path.iterdir()) == []


def test_cli_filesystem_errors(tmp_path, capsys):
    path = tmp_path / "existing.ods-pilot.con.toml"
    path.write_text("unchanged")
    assert main(["--generate-connection-template", "basic", str(path)]) == 1
    assert "Error:" in capsys.readouterr().err
    assert path.read_text() == "unchanged"
    assert main(["--generate-connection-template", "oidc", str(tmp_path / "absent" / "new.ods-pilot.con.toml")]) == 1
    assert "Error:" in capsys.readouterr().err


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_write_cleanup(tmp_path, monkeypatch, cleanup_fails):
    destination = tmp_path / "new.ods-pilot.con.toml"
    original_open = Path.open

    class FailedWrite:
        def __enter__(self):
            return self

        def write(self, text):
            raise OSError("disk full")

        def __exit__(self, *exc):
            assert stream is not None
            stream.close()

    stream = None

    def open_file(path, *args, **kwargs):
        nonlocal stream
        stream = original_open(path, *args, **kwargs)
        stream.write("partial")
        return FailedWrite()

    monkeypatch.setattr(Path, "open", open_file)
    if cleanup_fails:
        monkeypatch.setattr(Path, "unlink", MagicMock(side_effect=PermissionError("cleanup denied")))
        with pytest.warns(UserWarning, match="Cannot remove incomplete template"):
            with pytest.raises(OSError, match="disk full"):
                generate_connection_template("oidc", destination)
        assert destination.exists()
    else:
        with pytest.raises(OSError, match="disk full"):
            generate_connection_template("oidc", destination)
        assert not destination.exists()


def test_permission_denied_before_creation(tmp_path, monkeypatch):
    destination = tmp_path / "new.ods-pilot.con.toml"
    monkeypatch.setattr(Path, "open", MagicMock(side_effect=PermissionError("access denied")))
    with pytest.raises(PermissionError, match="access denied"):
        generate_connection_template("oidc", destination)
    assert not destination.exists()


def test_offline_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "--generate-connection-template AUTH_TYPE PATH" in capsys.readouterr().out
    assert "TOML" in help_text("connection_template")
