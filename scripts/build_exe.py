"""Build and smoke-test a standalone Windows console executable locally."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def verify(executable: Path) -> None:
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    with tempfile.TemporaryDirectory(prefix="odsbox-exe-") as directory:
        work = Path(directory)
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)

        def run(*arguments: str, status: int = 0) -> str:
            result = subprocess.run(
                [str(executable), *arguments],
                cwd=work,
                env=env,
                input="raise RuntimeError('stdin must not run')\n",
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if result.returncode != status:
                raise RuntimeError(
                    f"Executable smoke check failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
                )
            return result.stdout

        if run("--version").strip() != expected:
            raise RuntimeError("Executable version differs from the project version")
        if "--script" not in run("--help"):
            raise RuntimeError("Executable help is missing startup commands")
        for mode in ("basic", "m2m", "oidc"):
            template = work / f"{mode}.ods-pilot.con.toml"
            run("--generate-connection-template", mode, str(template))
            if tomllib.loads(template.read_text(encoding="utf-8"))["auth_type"] != mode:
                raise RuntimeError(f"Executable did not generate the {mode} template")
        startup = work / "startup commands.ods"
        startup.write_text(
            "import sys\n"
            "assert getattr(sys, 'frozen', False)\n"
            "from keyring.backends.Windows import WinVaultKeyring\n"
            "from odsbox.proto import ods_pb2\n"
            "assert ods_pb2.Model.FromString(ods_pb2.Model().SerializeToString()) == ods_pb2.Model()\n"
            "assert pd.DataFrame({'value': [1, 2]}).value.sum() == 3\n"
            + (
                "import matplotlib\n"
                "matplotlib.use('Agg')\n"
                "gui.plot(pd.DataFrame({'value': [1, 2]}), save='plot.png')\n"
                "gui.table(pd.DataFrame({'value': [1, 2]}), save='table.png')\n"
                "from pathlib import Path\n"
                "assert Path('plot.png').is_file() and Path('table.png').is_file()\n"
                if importlib.util.find_spec("matplotlib") is not None
                else ""
            )
            + "print('frozen-startup-ok')\n",
            encoding="utf-8",
        )
        if "frozen-startup-ok" not in run("--no-history", "--script", str(startup)):
            raise RuntimeError("Executable did not complete the offline startup script")
        startup.write_text("1 / 0\nprint('must-not-run')\n", encoding="utf-8")
        output = run("--no-history", "--script", str(startup), status=1)
        if "ZeroDivisionError" not in output or "must-not-run" in output:
            raise RuntimeError("Executable did not preserve startup error handling")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the .exe on Windows; PyInstaller does not cross-compile.")
    work = ROOT / "build" / "executable"
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name",
            "odsbox-cli",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(work / "work"),
            "--specpath",
            str(work),
            "--copy-metadata",
            "odsbox-cli",
            "--collect-submodules",
            "keyring.backends",
            str(ROOT / "src" / "odsbox_cli" / "__main__.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    executable = ROOT / "dist" / "odsbox-cli.exe"
    verify(executable)
    print(f"Built and verified {executable}")


if __name__ == "__main__":
    main()
