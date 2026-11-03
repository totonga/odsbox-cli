"""Build and smoke-test wheel and sdist outside the source checkout using uv."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="odsbox-package-") as directory:
        root = Path(directory)
        dist = args.dist.resolve() if args.dist else root / "dist"
        if args.dist is None:
            run("uv", "build", "--no-sources", "--out-dir", str(dist), cwd=Path.cwd())
        artifacts = sorted(p for p in dist.iterdir() if p.suffix == ".whl" or p.name.endswith(".tar.gz"))
        if len(artifacts) != 2:
            raise RuntimeError("Expected exactly one wheel and one source distribution")
        wheel = next(p for p in artifacts if p.suffix == ".whl")
        expected = tomllib.loads((Path.cwd() / "pyproject.toml").read_text())["project"]["version"]
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            metadata = archive.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
            if f"\nVersion: {expected}\n" not in metadata or "Requires-Dist: odsbox" not in metadata:
                raise RuntimeError("Incorrect distribution metadata")
            if not any(n.endswith("/LICENSE") for n in names):
                raise RuntimeError("Wheel does not contain its license")
        for index, artifact in enumerate(artifacts):
            env = root / f"env-{index}"
            run("uv", "venv", "--python", "3.14", str(env), cwd=root)
            interpreter = env / ("Scripts\\python.exe" if os.name == "nt" else "bin/python")
            run("uv", "pip", "install", "--python", str(interpreter), str(artifact), cwd=root)
            for arguments in (
                ("python", "-m", "odsbox_cli", "--help"),
                ("python", "-m", "odsbox_cli", "--version"),
                ("odsbox-cli", "--help"),
            ):
                run("uv", "run", "--no-project", "--python", str(interpreter), *arguments, cwd=root)
            installed = subprocess.check_output(
                [
                    "uv",
                    "run",
                    "--no-project",
                    "--python",
                    str(interpreter),
                    "python",
                    "-c",
                    "from importlib.metadata import version; from odsbox_cli.help import TOPICS, help_text; "
                    "from odsbox_cli.history import CommandHistory; from odsbox_cli.highlighting import InputLexer; "
                    "from odsbox_cli.database import Database; "
                    "from odsbox_cli.cli import Shell; import sys; import importlib.util; "
                    "assert importlib.util.find_spec('matplotlib') is None; "
                    "assert 'matplotlib.pyplot' not in sys.modules; "
                    "assert callable(Shell().namespace['gui'].plot); "
                    "assert {'bulk', 'history', 'gui', 'plot', 'table'} <= TOPICS.keys(); "
                    "assert CommandHistory(enabled=False).path is None; "
                    "assert callable(Database.bulk) and callable(InputLexer); "
                    "assert all(help_text(t) for t in TOPICS); print(version('odsbox-cli'))",
                ],
                cwd=root,
                text=True,
            ).strip()
            if installed != expected:
                raise RuntimeError("Installed version differs from the built project")
            for auth_type in ("basic", "m2m", "oidc"):
                template = root / f"server {index} {auth_type}.ods-pilot.con.toml"
                run(
                    "uv",
                    "run",
                    "--no-project",
                    "--python",
                    str(interpreter),
                    "odsbox-cli",
                    "--generate-connection-template",
                    auth_type,
                    str(template),
                    cwd=root,
                )
                run(
                    "uv",
                    "run",
                    "--no-project",
                    "--python",
                    str(interpreter),
                    "python",
                    "-c",
                    "import sys; from pathlib import Path; from odsbox_cli.connections import portable_file; "
                    "p = Path(sys.argv[1]); c = portable_file(p); assert c.auth_type == sys.argv[2]; "
                    "assert c.name == p.name.split('.', 1)[0]",
                    str(template),
                    auth_type,
                    cwd=root,
                )
            startup = root / "startup commands.ods"
            for source, status in (
                ("value = 42\nprint('startup-ok', value)\n", 0),
                ("print('startup-ok')\n1 / 0\nprint('must-not-run')\n", 1),
            ):
                startup.write_text(source, encoding="utf-8")
                result = subprocess.run(
                    [
                        "uv",
                        "run",
                        "--no-project",
                        "--python",
                        str(interpreter),
                        "odsbox-cli",
                        "--no-history",
                        "--script",
                        str(startup),
                    ],
                    cwd=root,
                    input="raise RuntimeError('stdin must not run')\n",
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if (
                    result.returncode != status
                    or "startup-ok" not in result.stdout
                    or "must-not-run" in result.stdout
                    or (status and f"{startup}:2: ZeroDivisionError" not in result.stdout)
                ):
                    raise RuntimeError(f"Installed startup script failed: {result.stdout}\n{result.stderr}")
            run(
                "uv",
                "run",
                "--no-project",
                "--python",
                str(interpreter),
                "python",
                "-c",
                "import ast, json, tomllib; from unittest.mock import MagicMock; "
                "from odsbox_cli.connections import Config; from odsbox_cli.database import Database, Session; "
                "from odsbox_cli.connections import Registry; "
                "s = Session(Registry()); s.connection = MagicMock(); s.name = 'Offline'; "
                "s.config = Config('Offline', 'https://example.invalid/api', 'basic', username='user'); "
                "p = Database(s, lambda frame: None).script_starter('starters', open_folder=False); "
                "ast.parse((p / 'script.py').read_text()); "
                "tomllib.loads((p / 'pyproject.toml').read_text()); "
                "json.loads((p / '.vscode' / 'mcp.json').read_text()); "
                "assert (p / 'README.md').is_file()",
                cwd=root,
            )
            run("uv", "pip", "install", "--python", str(interpreter), f"{artifact}[plot]", cwd=root)
            run(
                "uv",
                "run",
                "--no-project",
                "--python",
                str(interpreter),
                "python",
                "-c",
                "import matplotlib; matplotlib.use('Agg'); import pandas as pd; "
                "from pathlib import Path; from odsbox_cli.cli import Shell; "
                "s = Shell(); frame = pd.DataFrame({'signal': range(100)}); s.namespace['_'] = frame; "
                "s.gui.plot(save='plot.png'); s.gui.table(save='table.png'); "
                "assert s.namespace['_'] is frame; "
                "assert Path('plot.png').stat().st_size > 1000 and Path('table.png').stat().st_size > 1000",
                cwd=root,
            )
        run(
            "uv",
            "--cache-dir",
            str(root / "tool-cache"),
            "tool",
            "run",
            "--isolated",
            "--from",
            str(wheel),
            "odsbox-cli",
            "--no-history",
            "--help",
            cwd=root,
        )


if __name__ == "__main__":
    main()
