"""Generate independent uv projects from nonsecret connection settings."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

from odsbox_cli.connections import Config


def query_snapshot(query: object) -> str:
    """Encode portable query data without silently coercing Python values."""
    if isinstance(query, str):
        query = json.loads(query, parse_constant=_invalid_constant)
    if not isinstance(query, dict):
        raise ValueError("The saved query must be a JSON object")

    def validate(value: object) -> None:
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("Query object keys must be strings")
            for item in value.values():
                validate(item)
        elif isinstance(value, list):
            for item in value:
                validate(item)
        elif value is not None and type(value) not in (str, int, float, bool):
            raise ValueError(f"Query contains a nonportable {type(value).__name__} value")

    validate(query)
    return json.dumps(query, ensure_ascii=True, allow_nan=False, indent=4)


def _invalid_constant(value: str) -> Any:
    raise ValueError(f"Nonfinite JSON value: {value}")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "ods-starter"


def _mcp(config: Config) -> dict[str, Any]:
    env = {
        "ODSBOX_MCP_MODE": config.auth_type,
        "ODSBOX_MCP_URL": config.url,
        "ODSBOX_MCP_VERIFY": str(config.verify_certificate).lower(),
    }
    if config.auth_type == "basic":
        env["ODSBOX_MCP_USER"] = config.username
    elif config.auth_type == "m2m":
        env.update(
            {
                "ODSBOX_MCP_M2M_TOKEN_ENDPOINT": config.token_endpoint,
                "ODSBOX_MCP_M2M_CLIENT_ID": config.client_id,
            }
        )
    else:
        env.update(
            {
                "ODSBOX_MCP_OIDC_CLIENT_ID": config.client_id,
                "ODSBOX_MCP_OIDC_REDIRECT_URI": config.redirect_uri,
                "ODSBOX_MCP_OIDC_REDIRECT_INSECURE": str(config.redirect_url_allow_insecure).lower(),
            }
        )
        if config.webfinger_path_prefix:
            env["ODSBOX_MCP_OIDC_WEBFINGER_PATH_PREFIX"] = config.webfinger_path_prefix
    return {
        "servers": {
            "ods-mcp": {
                "type": "stdio",
                "command": "uvx",
                "args": ["odsbox-jaquel-mcp@latest"],
                "env": env,
            }
        },
        "inputs": [],
    }


def _script(config: Config, query: str | None) -> str:
    settings: dict[str, Any] = {
        "url": config.url,
        "verify_certificate": config.verify_certificate,
        "context_variables": config.context_variables or None,
    }
    if config.auth_type == "basic":
        settings["username"] = config.username
    elif config.auth_type == "m2m":
        settings.update(token_endpoint=config.token_endpoint, client_id=config.client_id, scope=config.scope or None)
    else:
        settings.update(
            client_id=config.client_id,
            redirect_uri=config.redirect_uri,
            webfinger_path_prefix=config.webfinger_path_prefix,
            redirect_url_allow_insecure=config.redirect_url_allow_insecure,
        )
    lines = [
        '"""Standalone ODS exploration starter. Run: uv run python script.py"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    if query is not None:
        lines += ["import json", ""]
    if config.auth_type != "oidc":
        lines += ["import keyring"]
    lines += ["from odsbox.con_i_factory import ConIFactory", "", "", "def main() -> None:"]
    if config.auth_type != "oidc":
        lines += [
            f"    secret = keyring.get_password('ods-pilot', {config.account!r})",
            "    if secret is None:",
            "        raise RuntimeError('No credential in OS keyring; see README.md for setup.')",
        ]
    lines += [f"    with ConIFactory.{config.auth_type}("]
    lines += [f"        {key}={value!r}," for key, value in settings.items()]
    if config.auth_type != "oidc":
        parameter = "password" if config.auth_type == "basic" else "client_secret"
        lines += [f"        {parameter}=secret,"]
    lines += ["    ) as connection:"]
    if query is None:
        lines += [
            "        model = connection.model()",
            "        for entity in sorted(model.entities.values(), key=lambda item: item.name):",
            "            print(entity.aid, entity.name, entity.base_name)",
        ]
    else:
        lines += [
            f"        query = json.loads({query!r})",
            "        frame = connection.query(query)",
            "        print(frame.head(20).to_string(max_cols=12, max_colwidth=40))",
            '        print(f"[{len(frame)} rows x {len(frame.columns)} columns]")',
        ]
    lines += ["", "", 'if __name__ == "__main__":', "    main()", ""]
    return "\n".join(lines)


def _readme(config: Config, query: str | None) -> str:
    keyring_account = "'" + config.account.replace("'", "''") + "'"
    authentication = (
        "OIDC opens a browser for login. No password is embedded.\n"
        if config.auth_type == "oidc"
        else (
            "Set your password/client secret in the OS keyring (hidden prompt):\n\n"
            "```powershell\n"
            f"uv run python -m keyring set ods-pilot {keyring_account}\n"
            "```\n\n"
            "The script and pilot use the same service/account. Missing credentials fail clearly.\n"
        )
    )
    operation = (
        "The script replays the last successful query with evaluated values, not the original\n"
        "Python expressions. Fetch limits are preserved exactly: printing 20 rows does not\n"
        "limit network reads. Review the query before running; add a row limit if needed.\n"
        if query is not None
        else "No query was captured. The script lists model entities without querying instance data.\n"
    )
    return (
        "# ODS exploration starter\n\n"
        f"Generated by odsbox-cli for connection {json.dumps(config.name, ensure_ascii=False)}.\n"
        "Project layout follows [odsbox-pilot](https://github.com/totonga/odsbox-pilot).\n\n"
        "## Setup and run\n\n"
        "Requires uv and Python 3.14+. This project runs independently of odsbox-cli.\n\n"
        "```powershell\nuv sync\nuv run python script.py\n```\n\n"
        "## Authentication\n\n" + authentication + "\n"
        "Connection settings preserve TLS verification, context variables and auth options.\n"
        "No credential, session token or keyring contents were read/exported during generation.\n\n"
        "## Exploration\n\n" + operation + "\n"
        "Edit script.py to change the query and work with the pandas DataFrame.\n"
        "Generation did not install dependencies, run the script or contact the server.\n\n"
        "## Optional MCP\n\n"
        ".vscode/mcp.json configures odsbox-jaquel-mcp via uvx, matching pilot's nonsecret\n"
        "environment mapping. Launching it is a separate, explicit action in VS Code.\n"
        "The @latest MCP reference may change over time. Its mapping does not include\n"
        "context_variables or M2M scope; script.py does preserve those settings.\n"
        "No MCP process was started by generation. Authenticate according to MCP's documentation.\n\n"
        "## Before sharing\n\n"
        "Review every file: URLs, usernames, context settings and query literals may be\n"
        "sensitive even though authentication secrets are excluded. This is not automatic\n"
        "secret detection/redaction. Do not commit credentials or tokens.\n\n"
        "See [JAQuel examples](https://peak-solution.github.io/odsbox/jaquel_examples_notebook.html).\n"
    )


def open_project(folder: Path) -> None:
    """Opening is best-effort; generation has already succeeded."""
    code = shutil.which("code")
    if code:
        try:
            subprocess.run([code, str(folder)], check=True, timeout=10)
            return
        except (OSError, subprocess.SubprocessError) as exc:
            warnings.warn(f"Could not open VS Code ({type(exc).__name__}); trying file explorer.", stacklevel=2)
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)], check=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        warnings.warn(f"Project created at {folder}; could not open folder ({type(exc).__name__}).", stacklevel=2)


def generate(config: Config, query: str | None, parent: str | Path, *, open_folder: bool = True) -> Path:
    if config.auth_type not in {"basic", "m2m", "oidc"}:
        raise ValueError("Script starters require a connected basic, m2m or oidc server")
    query = query_snapshot(query) if query is not None else None
    slug = _slug(config.name)
    dependencies = ["odsbox[oidc]>=1.10.1"]
    if config.auth_type != "oidc":
        dependencies.append("keyring>=25")
    manifest = (
        "[project]\n"
        f'name = {json.dumps(slug)}\nversion = "0.1.0"\n'
        f"description = {json.dumps('ODS query starter for ' + config.name, ensure_ascii=False)}\n"
        'requires-python = ">=3.14"\n'
        f"dependencies = {json.dumps(dependencies)}\n\n"
        '[dependency-groups]\ndev = ["pytest>=9", "ruff>=0.15"]\n'
    )
    contents = {
        "pyproject.toml": manifest,
        "script.py": _script(config, query),
        "README.md": _readme(config, query),
        ".vscode/mcp.json": json.dumps(_mcp(config), ensure_ascii=False, indent=4) + "\n",
    }
    parent = Path(parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    name = f"{slug}-{datetime.now():%Y%m%d-%H%M%S-%f}"
    suffix = 0
    while True:
        folder = parent / (name if not suffix else f"{name}-{suffix}")
        try:
            folder.mkdir()
            break
        except FileExistsError:
            suffix += 1
    written: list[Path] = []
    vscode = folder / ".vscode"
    created_directories = [folder]
    try:
        vscode.mkdir()
        created_directories.append(vscode)
        for relative, content in contents.items():
            path = folder / relative
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                written.append(path)
                stream.write(content)
    except BaseException:
        for path in reversed(written):
            try:
                path.unlink()
            except OSError as exc:
                warnings.warn(f"Could not remove partial starter file {path} ({type(exc).__name__}).", stacklevel=2)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError as exc:
                warnings.warn(
                    f"Could not remove partial starter directory {directory} ({type(exc).__name__}).", stacklevel=2
                )
        raise
    if open_folder:
        open_project(folder)
    return folder
