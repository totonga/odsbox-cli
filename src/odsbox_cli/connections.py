"""Pilot-compatible, secret-free connection storage."""

from __future__ import annotations

import getpass
import json
import os
import sys
import tempfile
import tomllib
import uuid
import warnings
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import keyring
from jsonschema import Draft202012Validator
from odsbox import ConI
from odsbox.con_i_factory import ConIFactory

COMMON = {"name", "url", "auth_type", "verify_certificate", "context_variables"}
MODES = {
    "basic": {"username"},
    "m2m": {"token_endpoint", "client_id", "scope"},
    "oidc": {"client_id", "redirect_uri", "webfinger_path_prefix", "redirect_url_allow_insecure"},
    "atfx": set(),
}
REQUIRED = {
    "basic": {"username"},
    "m2m": {"token_endpoint", "client_id"},
    "oidc": {"client_id", "redirect_uri"},
    "atfx": set(),
}
STRING_FIELDS = {
    "name",
    "url",
    "username",
    "token_endpoint",
    "client_id",
    "redirect_uri",
    "webfinger_path_prefix",
    "id",
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "url", "auth_type"],
    "additionalProperties": False,
    "properties": {
        **{name: {"type": "string"} for name in STRING_FIELDS},
        "auth_type": {"enum": list(MODES)},
        "verify_certificate": {"type": "boolean"},
        "redirect_url_allow_insecure": {"type": "boolean"},
        "scope": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "context_variables": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}


@dataclass(frozen=True)
class Config:
    name: str
    url: str
    auth_type: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    username: str = ""
    token_endpoint: str = ""
    client_id: str = ""
    scope: list[str] = field(default_factory=list)
    redirect_uri: str = "http://127.0.0.1:12345"
    webfinger_path_prefix: str = ""
    redirect_url_allow_insecure: bool = False
    verify_certificate: bool = True
    context_variables: dict[str, str] = field(default_factory=dict)

    @property
    def account(self) -> str:
        return f"{self.url}::{self.username or self.client_id}"

    def settings(self) -> dict[str, Any]:
        data = asdict(self)
        del data["id"]
        return data

    @classmethod
    def parse(cls, data: object, *, portable: bool = False) -> Config:
        errors = sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: str(e.path))
        if errors:
            raise ValueError(f"Invalid connection: {errors[0].message}")
        if not isinstance(data, dict):
            raise ValueError("Connection must be an object")
        mode = data["auth_type"]
        required = {"name", "url"} | REQUIRED[mode]
        if portable:
            unexpected = set(data) - COMMON - MODES[mode]
            if unexpected:
                raise ValueError(f"Unexpected portable fields: {', '.join(sorted(unexpected))}")
        for key in required:
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"Connection requires a non-empty {key}")
        if "id" in data and not data["id"].strip():
            raise ValueError("Connection id must not be empty")
        return cls(**data)


def portable_file(path: Path, name: str | None = None) -> Config:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".toml":
        data = tomllib.loads(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = tomllib.loads(text)
    config = Config.parse(data, portable=True)
    return Config.parse(asdict(replace(config, name=name))) if name is not None else config


def generate_connection_template(auth_type: str, path: Path) -> Path:
    if auth_type not in {"basic", "m2m", "oidc"}:
        raise ValueError("Template authentication must be basic, m2m or oidc")
    if not path.name.lower().endswith(".ods-pilot.con.toml"):
        raise ValueError("Connection templates require a .ods-pilot.con.toml destination")
    config = Config(path.name.split(".", 1)[0], "https://ods.example.invalid/api", auth_type)
    fields: dict[str, object] = {
        "name": config.name,
        "url": config.url,
        "auth_type": config.auth_type,
        "verify_certificate": config.verify_certificate,
    }
    comments = [
        "# Pilot-compatible connection template. Replace placeholders before import/use.",
        "# Never store passwords or client secrets here; keep certificate verification enabled.",
        '# After editing: odsbox-cli connections import "PATH_TO_THIS_FILE"',
        "# See help connection_template and help connections in the interactive CLI.",
    ]
    if auth_type == "basic":
        comments.extend(
            [
                "# Replace YOUR_USERNAME with your server login.",
                "# Password: OS keyring service ods-pilot, account URL::username.",
                "# If no saved password exists, the CLI prompts securely in a terminal.",
            ]
        )
        fields["username"] = "YOUR_USERNAME"
    elif auth_type == "m2m":
        comments.extend(
            [
                "# Replace the token endpoint and YOUR_CLIENT_ID with your provider settings.",
                "# scope is a list of strings; use [] if no scopes are required.",
                '# Example scope value: ["openid", "your-api-scope"].',
                "# Client secret: OS keyring service ods-pilot, account URL::client_id.",
                "# If no saved secret exists, the CLI prompts securely in a terminal.",
            ]
        )
        fields.update(
            token_endpoint="https://identity.example.invalid/token", client_id="YOUR_CLIENT_ID", scope=config.scope
        )
    else:
        comments.extend(
            [
                "# Replace YOUR_CLIENT_ID with your registered OIDC client ID.",
                "# Browser login: register redirect_uri with your identity provider.",
                "# webfinger_path_prefix is optional; leave empty unless your server requires it.",
                "# Insecure redirects are disabled by default; change only for a provider that requires it.",
            ]
        )
        fields.update(
            client_id="YOUR_CLIENT_ID",
            redirect_uri=config.redirect_uri,
            webfinger_path_prefix=config.webfinger_path_prefix,
            redirect_url_allow_insecure=config.redirect_url_allow_insecure,
        )
    Config.parse(fields, portable=True)
    content = "\n".join(
        [
            *comments,
            "",
            *(f"{name} = {json.dumps(value)}" for name, value in fields.items()),
            "",
            "# Optional string-to-string context settings; leave empty if unused.",
            "[context_variables]",
            '# LANGUAGE = "en"',
            "",
        ]
    )
    stream = path.open("x", encoding="utf-8", newline="\n")
    try:
        with stream:
            stream.write(content)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            warnings.warn(f"Cannot remove incomplete template {path}: {exc}", stacklevel=2)
        raise
    return path


def read_registry(path: Path) -> list[Config]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError("Registry must contain an array")
        if any(not isinstance(item, dict) or "id" not in item for item in data):
            raise ValueError("Saved registry records require stable IDs")
        return [Config.parse(item) for item in data]
    except (ValueError, OSError) as exc:
        raise ValueError(f"Cannot load registry {path}: {exc}") from exc


class Registry:
    def __init__(self, path: Path | None = None, pilot_path: Path | None = None) -> None:
        self.path = path or Path.home() / ".odsbox-cli" / "servers.json"
        self.pilot_path = pilot_path or Path.home() / ".ods-pilot" / "servers.json"

    def entries(self) -> list[tuple[Config, str]]:
        entries: list[tuple[Config, str]] = []
        for path, source in ((self.pilot_path, "pilot"), (self.path, "cli")):
            for config in read_registry(path):
                matches = [(c, s) for c, s in entries if c.id == config.id or c.name == config.name]
                if matches:
                    old, _ = matches[0]
                    if old.id == config.id and old.settings() == config.settings():
                        continue
                    raise ValueError(f"Conflicting registry entry {config.name!r}; rename the imported connection")
                entries.append((config, source))
        return entries

    def get(self, name: str) -> Config:
        for config, _ in self.entries():
            if config.name == name:
                return config
        raise ValueError(f"Unknown server {name!r}; use 'connections list'")

    def import_configs(self, incoming: list[Config]) -> int:
        entries = [c for c, _ in self.entries()]
        stored = read_registry(self.path)
        added = 0
        for config in incoming:
            config = Config.parse(asdict(config))
            own = next((c for c in stored if c.id == config.id or c.name == config.name), None)
            if own and own.settings() == config.settings():
                continue
            matches = [c for c in entries if c.id == config.id or c.name == config.name]
            if matches and not all(c.id == config.id and c.settings() == config.settings() for c in matches):
                raise ValueError(f"Connection conflict for {config.name!r}; import with --name to rename")
            stored.append(config)
            if not matches:
                entries.append(config)
            added += 1
        if added:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".servers-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump([asdict(c) for c in stored], stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return added


def secret_for(config: Config) -> str:
    try:
        secret = keyring.get_password("ods-pilot", config.account)
    except keyring.errors.KeyringError as exc:
        warnings.warn(f"Keyring unavailable ({type(exc).__name__}); prompting securely", stacklevel=2)
        secret = None
    if secret is not None:
        return secret
    if not sys.stdin.isatty():
        raise ValueError("No saved credential and no secure terminal; configure the OS keyring first")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(f"{config.name} {'password' if config.auth_type == 'basic' else 'client secret'}: ")


def connect(config: Config, secret: str | None = None, **timeouts: float) -> ConI:
    common: dict[str, Any] = {
        "url": config.url,
        "verify_certificate": config.verify_certificate,
        "context_variables": config.context_variables or None,
        **timeouts,
    }
    if config.auth_type == "atfx":
        raise ValueError("ATFX entries can be imported, but opening local ATFX files is not supported")
    if config.auth_type == "basic":
        return ConIFactory.basic(
            username=config.username, password=secret_for(config) if secret is None else secret, **common
        )
    if config.auth_type == "m2m":
        return ConIFactory.m2m(
            token_endpoint=config.token_endpoint,
            client_id=config.client_id,
            client_secret=secret_for(config) if secret is None else secret,
            scope=config.scope or None,
            **common,
        )
    return ConIFactory.oidc(
        client_id=config.client_id,
        redirect_uri=config.redirect_uri,
        redirect_url_allow_insecure=config.redirect_url_allow_insecure,
        webfinger_path_prefix=config.webfinger_path_prefix,
        **common,
    )
