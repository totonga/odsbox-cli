"""Semantic-release build hook and guarded publication preparation."""

from __future__ import annotations

import argparse
import os
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*arguments: str) -> str:
    return subprocess.check_output(arguments, cwd=ROOT, text=True).strip()


def build() -> None:
    # PSR has already stamped project.version; only refresh this project in the lock.
    run("uv", "lock", "--upgrade-package", "odsbox-cli")
    run("git", "add", "uv.lock")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for path in dist.iterdir():
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz")):
            path.unlink()
    run("uv", "build", "--no-sources")
    verify()


def verify() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(p for p in lock["package"] if p["name"] == "odsbox-cli")
    if package["version"] != version:
        raise RuntimeError("Release project/lock versions disagree")
    files = list((ROOT / "dist").iterdir())
    wheels = [p for p in files if p.suffix == ".whl"]
    sources = [p for p in files if p.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sources) != 1:
        raise RuntimeError("Expected exactly one release wheel and sdist")
    with zipfile.ZipFile(wheels[0]) as wheel:
        metadata = wheel.read(next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))).decode()
    with tarfile.open(sources[0]) as source:
        member = next(m for m in source.getmembers() if m.name.endswith("/PKG-INFO"))
        stream = source.extractfile(member)
        if stream is None:
            raise RuntimeError("Missing source distribution metadata")
        source_metadata = stream.read().decode()
    for content in (metadata, source_metadata):
        if f"\nVersion: {version}\n" not in content or "\nName: odsbox-cli\n" not in content:
            raise RuntimeError("Artifact metadata does not match release version")


def release() -> None:
    before = run("git", "rev-parse", "HEAD")
    run("uv", "run", "--no-sync", "semantic-release", "version")
    after = run("git", "rev-parse", "HEAD")
    released = before != after
    if released:
        version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
        if f"v{version}" not in run("git", "tag", "--points-at", "HEAD").splitlines():
            raise RuntimeError("Version commit does not have the expected release tag")
        verify()
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"released={'true' if released else 'false'}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "verify", "release"])
    arguments = parser.parse_args()
    {"build": build, "verify": verify, "release": release}[arguments.command]()
