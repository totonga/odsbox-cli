# Development, verification and release knowledge

Use the [README development sections](../../README.md#development-and-verification) for the full
workflow and [pyproject.toml](../../pyproject.toml) for current Python, dependency,
lint, typing, pytest and coverage settings. Do not hardcode versions from a past
session into new instructions.

## Local commands

Run from the repository root. Every Python/tool invocation goes through uv.
These commands use PowerShell-compatible paths:

```powershell
uv sync --locked --all-groups --extra plot
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src scripts tests
uv run --locked pytest --cov=odsbox_cli --cov-report=term-missing --cov-fail-under=85
uv build --no-sources
uv run --locked python scripts\package_smoke.py --dist dist
```

- Start with the smallest relevant test selection, then run the offline suite
  with package-wide coverage for code changes. The minimum is **85% line
  coverage**, including modules not imported by tests.
- Ordinary pytest excludes `integration`. Do not remove that default to make a
  local command convenient.
- Preview tests need the `plot` extra and use headless Agg. Keep base installation
  checks without the extra; never require a GUI/display for ordinary CI.
- Application and scripts use strict mypy. Tests allow unannotated definitions
  and calls to untyped helpers, but their bodies are still checked; all other
  strict rules remain enabled. The `tests` package marker scopes this override.
  `uv run --locked mypy` defaults to all three targets; `mypy tests` also resolves
  local source through the configured project-relative mypy path.
- Follow existing Ruff configuration. Add tests for changed
  behavior rather than disabling checks or narrowing coverage to pass.
- Do not reinstall dependencies speculatively. Use locked sync for setup; if a
  manifest changes, update the lock deliberately without unrelated upgrades.
- Documentation-only changes need factual/link and whitespace checks, not a
  package build, dependency install or live connection unless documentation
  tooling specifically requires them.

## Test design

- [conftest.py](../../tests/conftest.py) supplies model/connection/session
  fixtures and isolates command-history storage. Never use a developer's real
  registry, keyring or history file in ordinary tests.
- Keep lifecycle failures, result retention, no-network completion and exact
  bulk forwarding covered. Use real DataFrames for frame semantics, including
  object identity, dtypes/index and attrs.
- [Terminal tests](../../tests/test_cli.py) use prompt-toolkit pipe input and
  dummy output to validate actual key bindings, not only helper functions.
- [Startup tests](../../tests/test_startup.py) cover fail-fast command files,
  original line provenance, terminal debugging state, no stdin consumption and
  final cleanup. Installed smoke checks run success/failure files offline.
- [Template tests](../../tests/test_connection_templates.py) round-trip each
  authentication mode through portable import/registry storage and assert
  no overwrite, credentials, network or shell startup. Package smoke checks
  generate/import-parse TOML outside the checkout without a real registry.
- [Release test](../../tests/test_release.py) uses a disposable Git repository.
  Do not run release mutation against the working repository as a substitute.
- [Starter tests](../../tests/test_script_starter.py) parse generated Python,
  TOML and MCP JSON and execute scripts with mocked odsbox/keyring. Never run
  generated authentication against a real server as incidental validation.
  Starter generation itself must not read credentials or launch MCP/installers.

## Live-server tests are opt-in

See [README live-test setup](../../README.md#explicit-live-tests-local-only) and
[test_integration.py](../../tests/test_integration.py). Require explicit intent
to contact a server and execution-time `ODSBOX_TEST_URL`, `ODSBOX_TEST_USERNAME`
and `ODSBOX_TEST_PASSWORD` environment variables:

```powershell
uv run --locked pytest -m integration tests\test_integration.py -q
```

Never put an actual password in source, docs, committed configuration or test
fixtures. Use a hidden prompt or an approved secret mechanism; clear secret
environment values afterward. Do not silently skip missing credentials or
convert failed reads to passing tests.

Live tests exercise basic authentication, bounded model/query/bulk inspection,
explicit reconnect and temporary local exports. M2M/OIDC are covered with mocks,
not verified live by this suite. Do not mutate server data/models or pilot
registry/keyring state. Logout is required session cleanup. Bulk limits depend
on upstream/server behavior; see the [architecture caveat](architecture.md#dataframes-and-bulk-reads).

## Build and independent installation

[package_smoke.py](../../scripts/package_smoke.py) can build artifacts itself
when `--dist` is omitted. When given an artifact directory, it expects exactly
one wheel and one sdist. Use the current build's filenames, not a version copied
from an old session.

The script checks metadata/license, independently installs each artifact outside
the checkout, exercises launchers/version/help, checks installed API/help
surfaces, and runs an isolated uv tool with a fresh temporary cache. Reusing an
old cached environment for an unchanged version can otherwise test stale code.
It checks the base CLI before installing each artifact's `plot` extra, then saves
plot/table images with Agg. No live ODS server is needed for preview validation.

Virtual environments, caches, coverage reports and distributions are derived
outputs. Do not edit them manually or commit them as project knowledge.

### Local Windows executable

See the [local executable instructions](../../README.md#local-windows-executable).
[build_exe.py](../../scripts/build_exe.py) uses the opt-in `executable` dependency
group to build `dist\odsbox-cli.exe` with PyInstaller on Windows, then runs offline
smoke checks outside the checkout. Add `--extra plot` to bundle previews; the
installed build environment determines bundled optional dependencies.
Generated spec/work files stay under ignored `build\executable`. This local
unsigned build is separate from semantic-release, wheel/sdist packaging and CI
publication. Unit tests mock the builder; validate freezing changes with a real
Windows build as well.

## CI and release boundaries

- [build.yml](../../.github/workflows/build.yml) is authoritative: lint/type
  checks, offline tests and coverage, Linux/Windows test/package jobs, and a
  dependency audit precede release.
- Semantic-release runs on eligible pushes to `main`. Follow
  [pyproject configuration](../../pyproject.toml) for commit/version behavior,
  [release.py](../../scripts/release.py) for guarded build/version checks, and
  [README release guidance](../../README.md#ci-and-releases) for external setup.
- Publishing uses PyPI trusted publishing and the `pypi` environment, not a
  long-lived token committed to the project. Local checks do not prove that
  protected environments or trusted publishers are configured remotely.
- Never push/tag, bump versions or publish merely to validate an unrelated task.
  A failed publish may leave a version/tag; inspect the state before recovery.
  Do not blindly create another version or overwrite an existing distribution.

Keep these notes synchronized with source/configuration changes, and link to
canonical procedures rather than maintaining a second full user manual.
