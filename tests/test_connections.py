import json
import warnings
from dataclasses import asdict, replace
from unittest.mock import MagicMock

import keyring
import pytest

from odsbox_cli.connections import Config, Registry, connect, portable_file, read_registry, secret_for


@pytest.mark.parametrize(
    "mode,fields",
    [
        ("basic", {"username": "u"}),
        ("m2m", {"client_id": "c", "token_endpoint": "https://token"}),
        ("oidc", {"client_id": "c", "redirect_uri": "http://127.0.0.1:12345"}),
        ("atfx", {}),
    ],
)
def test_config(mode, fields, tmp_path):
    data = {"name": "server", "url": "https://ods", "auth_type": mode, **fields}
    config = Config.parse(data, portable=True)
    assert config.verify_certificate is True
    assert config == Config.parse(asdict(config))
    path = tmp_path / "portable.json"
    path.write_text(json.dumps(data))
    assert portable_file(path, "renamed").name == "renamed"


@pytest.mark.parametrize(
    "data",
    [
        [],
        {},
        {"name": "", "url": "x", "auth_type": "atfx"},
        {"name": "x", "url": "x", "auth_type": "basic"},
        {"name": "x", "url": "x", "auth_type": "atfx", "password": "do-not-store"},
        {"name": "x", "url": "x", "auth_type": "atfx", "verify_certificate": "false"},
        {"name": "x", "url": "x", "auth_type": "atfx", "username": "u"},
        {"name": "x", "url": "x", "auth_type": "m2m", "client_id": "c", "token_endpoint": "x", "scope": [1]},
    ],
)
def test_invalid_portable(data):
    with pytest.raises(ValueError):
        Config.parse(data, portable=True)


def test_toml_and_fallback(tmp_path):
    text = 'name = "local"\nurl = "test.atfx"\nauth_type = "atfx"\n'
    for suffix in (".toml", ".con"):
        path = tmp_path / ("connection" + suffix)
        path.write_text(text)
        assert portable_file(path).auth_type == "atfx"
        with pytest.raises(ValueError, match="non-empty name"):
            portable_file(path, " ")
    path.write_text("not valid at all")
    with pytest.raises(ValueError):
        portable_file(path)


def test_registry_validation(tmp_path):
    path = tmp_path / "registry"
    assert read_registry(path) == []
    for text in ("{}", "[{}]", "garbage"):
        path.write_text(text)
        with pytest.raises(ValueError, match="Cannot load registry"):
            read_registry(path)
    with pytest.raises(ValueError):
        Config.parse({"name": "n", "url": "u", "auth_type": "atfx", "id": ""})


def test_registry_import(registry, tmp_path):
    config = registry.get("Demo")
    assert registry.import_configs([config]) == 0
    assert registry.import_configs([replace(config, id="fresh")]) == 0
    before = registry.path.read_bytes()
    with pytest.raises(ValueError, match="conflict"):
        registry.import_configs([Config("second", "url", "atfx"), replace(config, url="changed")])
    assert registry.path.read_bytes() == before
    assert registry.import_configs([replace(config, id="other", name="renamed")]) == 1
    with pytest.raises(ValueError, match="Unknown"):
        registry.get("unknown")
    assert "password" not in registry.path.read_text()
    registry.pilot_path.write_text(json.dumps([asdict(config)]))
    assert len(registry.entries()) == 2
    registry.pilot_path.write_text(json.dumps([asdict(replace(config, url="changed"))]))
    with pytest.raises(ValueError, match="Conflicting"):
        registry.entries()
    assert Registry().path.name == "servers.json"


def test_copy_discovered(registry):
    config = Config("pilot", "url", "atfx")
    registry.pilot_path.write_text(json.dumps([asdict(config)]))
    assert registry.import_configs([config]) == 1
    assert registry.import_configs([config]) == 0
    assert len(registry.entries()) == 2


def test_atomic_replace_failure(registry, monkeypatch):
    before = registry.path.read_bytes()
    monkeypatch.setattr("odsbox_cli.connections.os.replace", MagicMock(side_effect=OSError("cannot write")))
    with pytest.raises(OSError):
        registry.import_configs([Config("new", "url", "atfx")])
    assert before == registry.path.read_bytes()
    assert not list(registry.path.parent.glob(".servers-*"))


def test_secret(monkeypatch):
    config = Config("n", "url", "basic", username="u")
    getter = MagicMock(return_value="secret")
    monkeypatch.setattr(keyring, "get_password", getter)
    assert secret_for(config) == "secret"
    getter.assert_called_once_with("ods-pilot", "url::u")
    getter.return_value = None
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ValueError, match="secure terminal"):
        secret_for(config)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "typed")
    getter.side_effect = keyring.errors.NoKeyringError()
    with pytest.warns(UserWarning, match="Keyring unavailable"):
        assert secret_for(config) == "typed"
    getter.side_effect = None

    def insecure(prompt):
        warnings.warn("echo", __import__("getpass").GetPassWarning)

    monkeypatch.setattr("getpass.getpass", insecure)
    with pytest.raises(Warning):
        secret_for(config)


@pytest.mark.parametrize("mode", ["basic", "m2m", "oidc"])
def test_connect(monkeypatch, mode):
    factory = MagicMock()
    monkeypatch.setattr("odsbox_cli.connections.ConIFactory", factory)
    config = Config(
        "n",
        "url",
        mode,
        username="u",
        client_id="c",
        token_endpoint="token",
        scope=["openid"],
        context_variables={"LANGUAGE": "en"},
        verify_certificate=False,
        redirect_url_allow_insecure=True,
        webfinger_path_prefix="/ods",
    )
    assert connect(config, "secret", connection_timeout=5) is getattr(factory, mode).return_value
    args = getattr(factory, mode).call_args.kwargs
    assert args["verify_certificate"] is False
    assert args["context_variables"] == {"LANGUAGE": "en"}
    assert args["connection_timeout"] == 5
    if mode == "basic":
        assert args["password"] == "secret"
    elif mode == "m2m":
        assert args["client_secret"] == "secret" and args["scope"] == ["openid"]
    else:
        assert args["redirect_url_allow_insecure"] is True
        assert args["webfinger_path_prefix"] == "/ods"
    monkeypatch.setattr("odsbox_cli.connections.secret_for", lambda c: "saved")
    connect(config)
    with pytest.raises(ValueError, match="ATFX"):
        connect(replace(config, auth_type="atfx"))
