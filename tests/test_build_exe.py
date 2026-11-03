"""Local executable builds must remain separate from publishing."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import build_exe


def test_build_windows_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(build_exe, "ROOT", tmp_path)
    monkeypatch.setattr("scripts.build_exe.sys.platform", "win32")
    run = Mock()
    verify = Mock()
    monkeypatch.setattr("scripts.build_exe.subprocess.run", run)
    monkeypatch.setattr(build_exe, "verify", verify)
    build_exe.main()
    command = run.call_args.args[0]
    assert command[:3] == [sys.executable, "-m", "PyInstaller"]
    assert "--onefile" in command
    assert "--console" in command
    assert command[command.index("--copy-metadata") + 1] == "odsbox-cli"
    assert command[command.index("--collect-submodules") + 1] == "keyring.backends"
    assert command[command.index("--distpath") + 1] == str(tmp_path / "dist")
    assert command[-1] == str(tmp_path / "src" / "odsbox_cli" / "__main__.py")
    assert (tmp_path / "build" / "executable").is_dir()
    assert run.call_args.kwargs == {"cwd": tmp_path, "check": True}
    verify.assert_called_once_with(tmp_path / "dist" / "odsbox-cli.exe")


def test_reject_cross_compilation(monkeypatch):
    monkeypatch.setattr("scripts.build_exe.sys.platform", "linux")
    run = Mock()
    monkeypatch.setattr("scripts.build_exe.subprocess.run", run)
    with pytest.raises(SystemExit, match="does not cross-compile"):
        build_exe.main()
    run.assert_not_called()


def test_build_failure_is_not_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(build_exe, "ROOT", tmp_path)
    monkeypatch.setattr("scripts.build_exe.sys.platform", "win32")
    monkeypatch.setattr(
        "scripts.build_exe.subprocess.run", Mock(side_effect=subprocess.CalledProcessError(1, "PyInstaller"))
    )
    verify = Mock()
    monkeypatch.setattr(build_exe, "verify", verify)
    with pytest.raises(subprocess.CalledProcessError):
        build_exe.main()
    verify.assert_not_called()


def test_smoke_failure_is_reported(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 2, stdout="output", stderr="missing dependency"))
    monkeypatch.setattr("scripts.build_exe.subprocess.run", run)
    with pytest.raises(RuntimeError, match="missing dependency"):
        build_exe.verify(Path("odsbox-cli.exe"))
    assert run.call_args.kwargs["input"]
    assert run.call_args.kwargs["timeout"] == 120
