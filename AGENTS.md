# Agent guide

odsbox-cli is an installable Python console for inspecting ASAM ODS servers with
odsbox, relaxed JAQuel queries, model-aware completion, and pandas DataFrames.
It is a trusted local Python console, not a sandbox; read-only server use is a
convention, not an enforced security boundary.

## Read selectively

- [README](README.md): installation, user-facing behavior, examples, and safety.
- [Architecture knowledge](docs/agent/architecture.md): module map and invariants;
  read before changing parsing, completion, sessions, results, or terminal behavior.
- [Development knowledge](docs/agent/development.md): uv commands, tests,
  packaging, live-test boundaries, and release safeguards.
- [Project configuration](pyproject.toml) and [CI](.github/workflows/build.yml)
  are authoritative for tool settings and validation. Update relevant knowledge
  when behavior changes; do not preserve stale facts over current source.

## Working rules

- Run Python and Python tools through **uv**, never bare `python`, `pip`,
  `pytest`, `ruff`, or `mypy`. Use the locked environment for normal development.
- Make focused changes, preserve existing behavior, and update directly related
  tests and help. Reuse shared helpers rather than adding parallel logic.
- Completion and input highlighting must not execute user expressions or issue
  server queries.
- Keep ordinary tests offline. For code changes, run focused tests first, then
  applicable Ruff/mypy checks (strict source/scripts, relaxed body-checked tests)
  and package-wide pytest-cov with **>=85% line coverage**.
  Documentation-only changes need content/link checks.
- Never commit credentials or secrets. Live-server tests require explicit
  selection and execution-time credentials; do not run them incidentally.
- Do not publish, tag, bump versions, or change external server data as part of
  routine validation. Build artifacts, caches, virtual environments, and coverage
  outputs are generated, not authoritative source.
