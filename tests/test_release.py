"""Verify release stamping/building in a disposable repository, never this checkout."""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


def test_semantic_release_sandbox(tmp_path):
    root = Path(__file__).resolve().parents[1]
    sandbox = tmp_path / "release"
    sandbox.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE"):
        shutil.copy2(root / name, sandbox / name)
    for name in ("src", "scripts"):
        shutil.copytree(root / name, sandbox / name, ignore=shutil.ignore_patterns("__pycache__"))

    def run(*command):
        return subprocess.check_output(command, cwd=sandbox, text=True, stderr=subprocess.STDOUT)

    run("git", "init", "-b", "main")
    run("git", "config", "user.name", "Release test")
    run("git", "config", "user.email", "release-test@example.invalid")
    run("git", "remote", "add", "origin", "https://github.com/example/odsbox-cli.git")
    run("git", "add", ".")
    run("git", "commit", "-m", "chore: initial project")
    run("git", "tag", "v0.1.0")
    (sandbox / "README.md").write_text("Release fixture\n")
    run("git", "add", "README.md")
    run("git", "commit", "-m", "feat: inspect an ODS server")
    env = os.environ.copy()
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    command = [
        "uv",
        "run",
        "--no-project",
        "--python",
        sys.executable,
        "semantic-release",
        "version",
        "--no-push",
        "--no-vcs-release",
    ]
    result = subprocess.run(command, cwd=sandbox, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    version = tomllib.loads((sandbox / "pyproject.toml").read_text())["project"]["version"]
    assert version != "0.1.0"
    assert f"v{version}" in run("git", "tag", "--points-at", "HEAD")
    assert (sandbox / "CHANGELOG.md").is_file()
    lock = tomllib.loads((sandbox / "uv.lock").read_text())
    assert next(p["version"] for p in lock["package"] if p["name"] == "odsbox-cli") == version
    original_lock = tomllib.loads((root / "uv.lock").read_text())
    assert {p["name"]: p["version"] for p in lock["package"] if p["name"] != "odsbox-cli"} == {
        p["name"]: p["version"] for p in original_lock["package"] if p["name"] != "odsbox-cli"
    }
    assert not run("git", "status", "--porcelain", "--untracked-files=no").strip()
    assert len(list((sandbox / "dist").glob("*.whl"))) == 1
    assert len(list((sandbox / "dist").glob("*.tar.gz"))) == 1
    before = run("git", "rev-parse", "HEAD")
    result = subprocess.run(command, cwd=sandbox, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert run("git", "rev-parse", "HEAD") == before
