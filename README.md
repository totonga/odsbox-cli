# odsbox-cli

An interactive command-line tool for **inspecting ASAM ODS servers** with
[odsbox](https://peak-solution.github.io/odsbox/), JAQuel queries, model-aware
autocomplete, and real pandas DataFrames. Python 3.14 or newer is required.

## Install and start

Development checkout:

```powershell
uv sync --locked --all-groups
uv run odsbox-cli
```

Equivalent launchers are `uv run python -m odsbox_cli`.
Every Python/tool command in this project runs through **uv**.

Build and install an independent command:

```powershell
uv build --no-sources
uv tool install .\dist\odsbox_cli-0.1.0-py3-none-any.whl
odsbox-cli --help
odsbox-cli --version
```

Use the wheel filename produced by your build, not a stale version.
After the project is published, `uv tool install odsbox-cli` installs from PyPI.
There is no claim that publication has already occurred.

### Local Windows executable

On Windows, build a standalone, single-file console executable:

```powershell
uv run --locked --group executable python scripts\build_exe.py
.\dist\odsbox-cli.exe --help
.\dist\odsbox-cli.exe --version
```

The build requires uv and Python 3.14+, but the resulting executable does **not**
require Python or uv on the destination machine. Build on Windows for the target
architecture; cross-compiling a Windows `.exe` from Linux/macOS is not supported.
Run it from PowerShell or another terminal for the interactive console.

To bundle optional plotting/table previews, include the existing extra:

```powershell
uv run --locked --group executable --extra plot python scripts\build_exe.py
```

PyInstaller bundles dependencies installed in the build environment; use a clean
environment without `plot` for a base-only build. The executable contains a fixed
set of Python modules, not a general-purpose Python installation: arbitrary
imports in console/startup scripts are limited to bundled modules.
Single-file startup extracts support files to a temporary directory.

The process writes `dist\odsbox-cli.exe` (replacing a previous local executable),
keeps generated build files under `build\executable`, and smoke-tests version,
help, connection templates, pandas/protobuf, the Windows keyring backend import,
startup success/failure, and bundled plotting offline outside the checkout.
It does not read credentials or connect to a server. This is a local, unsigned
build only: it does not change versions, tag, publish, or alter wheel/sdist builds.
Windows may warn about running an unsigned executable.

## Prepared startup commands

```powershell
uv run odsbox-cli --script ".\explore.ods"
uv run odsbox-cli -s ".\explore.ods" --no-history
```

The UTF-8 file (optional BOM) uses **CLI syntax**, for example:

```python
use My server
selected_id = 42
runs = db.find({
    AoMeasurement: {id: selected_id},
    $options: {$rowlimit: 20}
})
runs.head()
```

On success, a terminal opens the usual prompt with the same `db`, variables and
last DataFrame `_`. **The first error stops the script** and reports its filename
and line; with terminal stdin, the prompt opens for debugging without discarding
successful setup. There is no rollback or automatic retry, including for partial
side effects inside a failed statement. Final normal exit returns **1** after a
script error, even if debugging succeeds; startup Ctrl-C returns **130**.
Without terminal stdin, the process exits after the script (0 on success) and
never consumes additional piped input. File/encoding errors follow the same rules.

Multiline bracketed expressions work. End compound Python blocks (`for`, `if`,
`def`, etc.) with an **unindented blank line** or EOF. Keep internal blank lines
indented, and put CLI commands on their own at top level:

```python
names = []
for name in ["Speed", "Time"]:
    names.append(name)
    print(name)

help bulk
```

Relative paths use the process working directory, not the script's directory.
`exit`/`quit` intentionally end the entire session, skipping the remaining file
and prompt; explicit Python `SystemExit` is honored. Cleanup runs on final exit.
Script contents bypass persistent history; commands entered in the prompt still
follow normal history settings. GUI previews require an interactive backend and
terminal; they update once the prompt is idle. Use explicit `save=` without a
terminal. Synchronous commands can temporarily pause GUI interaction.

Only run files you trust: this executes Python with your permissions, **not a
sandbox**. `--script` cannot be combined with the process-level `connections`
subcommand. Existing piped input without `--script` still continues after errors
and returns a nonzero status. See `help script`. This is separate from
`db.script_starter()`, which generates a standalone Python/uv project.

## Connections: reuse odsbox-pilot settings

The CLI discovers `~/.ods-pilot/servers.json` **read-only**. Names can be used
immediately; no import is necessary for local pilot connections.

```text
ods> connections list
ods> use My server
ods> disconnect
```

To copy portable connections or a saved pilot registry into CLI-owned storage:

```powershell
uv run odsbox-cli connections import ".\lab.ods-pilot.con.json"
uv run odsbox-cli connections import ".\lab.ods-pilot.con.toml" --name "Test server"
uv run odsbox-cli connections import-pilot --path "C:\config\servers.json"
```

The same `connections ...` commands work inside the shell. Quoted Windows paths
retain their backslashes. Imports are saved atomically to
`~/.odsbox-cli/servers.json`; pilot files are never modified. Repeated identical
imports report no changes. Conflicting names/IDs/settings are rejected, not
silently overwritten. Rename a portable import with `--name`.

Portable files use pilot's JSON/TOML format, **without secrets**:

```json
{
  "name": "Lab",
  "url": "https://ods.example.invalid/api",
  "auth_type": "basic",
  "username": "alice",
  "verify_certificate": true,
  "context_variables": {"LANGUAGE": "en"}
}
```

### Generate a connection template

```powershell
uv run odsbox-cli --generate-connection-template oidc "C:\temp\my_server.ods-pilot.con.toml"
# Edit the generated file, then import it:
uv run odsbox-cli connections import "C:\temp\my_server.ods-pilot.con.toml"
uv run odsbox-cli
```

In the prompt, select the connection with `use my_server` (or the name you
configured). The generated `name` is the filename before its first dot, stripping
all extensions: `my_server.ods-pilot.con.toml` becomes `my_server`. The derived
name must not be empty and can be edited. Template modes are **basic**, **m2m** and **oidc**.
Generation supports **TOML only**: the destination must end in `.ods-pilot.con.toml`
(case-insensitive). The parent directory must already exist; an existing file,
directory or symlink is **never overwritten**. Choose a new path to regenerate.

The file includes comments and the fields for just that authentication mode.
Replace the `example.invalid` server/token URLs and
`YOUR_USERNAME` / `YOUR_CLIENT_ID` as applicable. Optional context variables are
a string-to-string table; M2M scopes are a string list, initially empty.
Certificate verification stays enabled. OIDC uses the default redirect URI
`http://127.0.0.1:12345` with insecure redirects disabled; register the URI with
your identity provider and adjust optional webfinger settings only if needed.

**Do not add passwords or client secrets to the file.** Basic/M2M retrieve
secrets at connection time from the pilot-compatible OS keyring, or a hidden
terminal prompt. OIDC opens browser login only when connecting.
Template generation itself does not read registries, history or keyring,
connect, open a browser, import the file or start the interactive shell.
It exits after printing the file location and edit/import instructions.
Do not combine it with `--script` or the process-level `connections` subcommand.
ATFX templates are not offered because this CLI cannot open ATFX.
See `help connection_template` and `help connections` in the prompt.

Supported settings match pilot:

| Authentication | Settings |
|---|---|
| `basic` | `username`; password in keyring or hidden prompt |
| `m2m` | `token_endpoint`, `client_id`, optional `scope` string list; client secret in keyring or hidden prompt |
| `oidc` | `client_id`, `redirect_uri`, optional `webfinger_path_prefix`, `redirect_url_allow_insecure`; browser login |
| All server modes | `verify_certificate` (default true), `context_variables` (string-to-string map) |
| `atfx` | Entries can be imported/listed; opening local ATFX files is not supported |

OIDC defaults match pilot: redirect URI `http://127.0.0.1:12345`, insecure
redirects disabled. Configure insecure loopback redirects explicitly only when
your provider requires them. TLS verification is never disabled automatically.

Passwords/client secrets reuse OS keyring service **`ods-pilot`**, account
**`URL::username-or-client_id`**. Missing credentials prompt without echo and
are not saved automatically. If a secure terminal is unavailable, the CLI
refuses an echoed-input fallback. Keyring backend problems are reported.
Listing/importing/help do not require credentials or connect to a server.

A failed server switch leaves the old connection usable. Successful switches
and disconnect/exit clean up sessions; logout problems produce warnings.

### Recover from an expired session

```text
Lab> db.reconnect()
```

This explicitly opens a new session for the selected server, using its **current
registry settings** and the normal authentication flow. Keyring credentials are
reused when available; a hidden prompt or OIDC login may be needed again.
No plaintext credentials are retained solely for reconnect.

The cached model is refreshed. The existing `db` object, local variables,
DataFrames and `_` are preserved. The method returns `None` and does not print a
result. On connection/authentication, registry or model-loading failure, the
error is reported and the old session reference/model remain intact, although
that session may still be expired. Logout errors from the old session produce
warnings without undoing a successful replacement.

There is **no automatic reconnect or retry**: after reconnecting, explicitly
rerun the failed operation. Server-side transient state is not restored.
Before selecting a server, or after `disconnect`, use `use <server>` first.

## Inline help

At startup, type `help`. Topics work **without a connection**:

```text
help queries
help model
help results
help connections
help completion
help bulk
help history
help reconnect
help script_starter
```

Process commands also provide `--help`, including
`uv run odsbox-cli connections import --help`.
Python calls such as `help(pd.DataFrame)` remain ordinary Python.

## Generate a standalone exploration project

```python
folder = db.script_starter(r"C:\temp")
# No application launch:
folder = db.script_starter(r"C:\temp", open_folder=False)
```

The argument is a **parent directory**. Each call creates a new connection-named,
timestamped subfolder containing `pyproject.toml`, `script.py`, `README.md` and
`.vscode/mcp.json`, following odsbox-pilot's starter layout. It returns the created
`Path`; existing projects are never overwritten. By default the folder opens in
VS Code, or the file explorer if unavailable. Opening failures warn without
discarding the generated project.

The project is independent of odsbox-cli:

```powershell
Set-Location <generated-folder>
uv sync
uv run python script.py
```

It uses the **current successful connection's settings snapshot** (including TLS,
context variables and authentication options), not subsequent registry edits.
Basic/M2M secrets are retrieved only when running the generated script, using
pilot's `ods-pilot` OS keyring service/account. OIDC opens browser login. Follow
the generated README to set up credentials. Generation never reads credentials,
installs dependencies, runs the script, contacts the server, or starts MCP.

The last successful `db.find` query is captured as detached, evaluated JSON data;
later mutation of the original dict does not change it. Failed reads leave the
previous captured query intact. Model/bulk reads do not replace it. A successful
`use`, reconnect, or disconnect clears it. Without a saved query, the script lists
model entities instead. Non-JSON-compatible Python values cause an explicit
generation error, without changing whether the original query succeeds.

When run, the script replays that query exactly: **fetch limits are preserved**,
not silently inserted. Its 20-row output preview is not a network limit.
Review the query before execution. Generated settings and query literals may
contain sensitive application data even though authentication secrets are
excluded; inspect all files before sharing.

The MCP file matches pilot's nonsecret environment mapping. It does not carry
context variables or M2M scope (the Python script does). MCP installation/login/
launch remain separate explicit steps. The starter does not capture bulk reads,
DataFrames, local Python variables or live session tokens. `db`, `_`, and existing
results are unchanged. See `help script_starter`.

## Inspect the model first

```text
ods> use Lab
Lab> db.model.find()
Lab> db.model.find("AoMeasurement")
Lab> db.model.relations("AoMeasurement")
```

The first table lists entity IDs, application names and base names. Entity
details list attributes, types, enum names, unit IDs and flags. Relations list
targets and cardinalities (`range_max == -1` means unbounded).
An empty result preserves its table columns.

Application schemas differ. Prefer a specific application entity name if
several entities derive from `AoMeasurement`; autocomplete annotates ambiguous
base names rather than guessing their attributes. Manually entered base-name
queries retain odsbox's resolution behavior. The application model is cached;
call `db.reconnect()` to see external schema changes.

## Write JAQuel queries

```text
db.find({AoMeasurement: {}})
db.find({AoMeasurement: {}, $attributes: {id: 1, name: 1}, $options: {$rowlimit: 20}})
db.find({AoMeasurement: {name: {$like: "*test*"}}})
```

These are schema-dependent examples; discover the real names through the model.
The [JAQuel examples](https://peak-solution.github.io/odsbox/jaquel_examples_notebook.html)
explain projections, filters, ordering, grouping, and options.

Inline syntax is **relaxed Python**, not full JSON5:

- Identifier keys, `$` operator keys and dotted keys need no quotes.
- String **values** and keys with spaces/special characters must be quoted.
- `true`, `false`, `null` work alongside `True`, `False`, `None`.
- Python expressions are allowed as values; expressions execute once.
- Use `#` comments. `//` is always floor division, **not a comment**.
- Trailing commas and multiline queries work; JavaScript block comments do not.
- For computed dictionary keys, create an ordinary Python dict first.

```text
selected_id = 42
db.find({AoMeasurement: {id: selected_id}})
db.find({AoMeasurement: {}, $attributes: {test.name: 1}})
query = {"AoMeasurement": {"id": selected_id}}
db.find(query)
```

The dotted projection works only if `test` is a relation on that entity.
The CLI delegates JAQuel validation/execution to odsbox instead of implementing
a second query engine.

## Autocomplete and editing

Suggestions appear while typing:

```text
use Tes<Tab>                                  registered server names
db.find({AoMea<Tab>                           application/base entities
db.find({AoMeasurement: {na<Tab>               attributes and relations
db.find({AoMeasurement: {test.na<Tab>          relation-target attributes
db.find({AoMeasurement: {}, $att<Tab>          query clauses
db.find({AoMeasurement: {}, $options: {$row<Tab>
db.model.find("AoMea<Tab>                     model arguments
runs["na<Tab>                                actual DataFrame column names
```

Tab selects/cycles candidates; Shift-Tab cycles backward. **Enter accepts a
selected candidate without running the command**; press Enter again to submit.
Escape cancels completion. Incomplete input continues onto another line.
Ctrl-C cancels input/execution, Ctrl-D on an empty buffer exits.

Typing an opening `(`, `[`, `{`, `'` or `"` inserts its matching closer and
leaves the cursor inside. Pairing is conservative: only at end-of-input or
before whitespace/closing punctuation, not inside existing strings or comments,
or for escaped quotes. Quotes after ordinary words remain literal, while Python
string prefixes such as `r` and `f` are supported. Formatted/triple strings are
treated conservatively, without special interpolation editing.

This is **insertion only**: typing a closer inserts it normally even if one is
already ahead, and Backspace deletes one character, not the whole pair.
Use **Right Arrow** to move past the auto-inserted closer. There is no selection
wrapping or automatic indentation. Completion insertion and bracketed paste
remain verbatim; Ctrl-R search text is not paired. Terminals without bracketed
paste cannot reliably distinguish pasted keystrokes from typing.

Completion understands nested projections, filters, ordering/grouping paths,
enumeration labels on known attributes, direct DataFrame column selections,
and simple `sort_values("...")` column arguments. It does not evaluate arbitrary
Python expressions or complete pandas query-string syntax. It uses cached
model/local metadata only: no server queries, credential lookups or distinct
value fetching while typing. `db.bulk(` also completes unused keyword parameters,
without consulting the server model.

Interactive input has basic syntax highlighting for commands, relaxed query keys,
strings, numbers, keywords, punctuation and comments. Set `NO_COLOR` (any value)
to disable input colors. Tables, exports and piped output are unchanged.

### Persistent history and search

The latest **1000 commands** are stored in plaintext at
`~/.odsbox-cli/history.sqlite3`, shared across sessions. Up/Down recalls commands
at multiline boundaries. **Ctrl-R** starts case-insensitive reverse search;
repeat Ctrl-R for older matches. **Enter recalls the match for editing, without
executing it**; Enter again submits. Escape or Ctrl-C restores your original
draft and cursor. A failed search displays `No history match`.

Blank commands, consecutive duplicates and commands whose **first character
is a space** are excluded. Search text and cancelled drafts are not recorded.
Hidden credential prompts do not enter command history. Queries and Python
expressions may contain sensitive data: prefix them with a space, or start with
`uv run odsbox-cli --no-history` to prevent **all disk-history reads and writes**.
Disabled history remains bounded in memory for that process. Noninteractive
input, help and connection-management commands do not open history storage.
Storage failures warn once and fall back to memory. Delete the history file
with shells closed to clear stored commands.

## Read bulk measurement data

`db.bulk(...)` delegates to `con_i.bulk.data_read(...)` with its full signature:

```python
db.bulk(
    submatrix_iid,
    column_patterns=None,
    column_patterns_case_insensitive=False,
    date_as_timestamp=True,
    set_independent_as_index=True,
    values_start=0,
    values_limit=0,
    *,
    raise_on_partial_result=False,
    valid_flag=None,
)
```

Discover the application entity derived from `AoSubmatrix` using
`db.model.find()`, then use a bounded `db.find(...)` query to obtain a real ID.
For example (replace `42` with that ID):

```text
samples = db.bulk(42, column_patterns=["Time", "*speed*"], values_start=0, values_limit=100)
samples.head()
samples.attrs["unit_names"]
samples.to_csv("samples.csv")
```

Patterns support `*` and `?`; case-insensitive matching is opt-in. Sample
offsets are zero-based. **`values_limit=0` is unlimited**, so provide a limit
for exploratory reads. Dates become timestamps by default, and a single
independent column becomes the index. The original DataFrame is returned,
preserving index, dtypes and `attrs`, including `unit_names` and
`partial_result`; successful calls update `_`, even when assigned.

Partial results produce a warning. Set `raise_on_partial_result=True` to
propagate odsbox's completeness error instead. Other upstream errors propagate
without replacing the prior result. `valid_flag` masks invalid **values**, not
rows: `None` disables masking; integers specify a quality mask. Upstream
currently maps **both `True` and `False` to mask 15**; the CLI forwards them
unchanged. Bulk calls use normal Python syntax, not relaxed JAQuel keys.

Sample limiting relies on odsbox and the server's sequence handling. On the demo
server, some stored columns return full sequences despite a limit while implicit
columns honor it; reading those together can raise `ValueError: All arrays must
be of the same length`. This upstream behavior is not silently sliced or hidden.
Select individual column patterns to inspect affected data, and verify returned
lengths before assuming the server honored a limit.

## Work with complete DataFrames

### Optional graphical previews

Install the single optional matplotlib extra:

```powershell
uv sync --locked --extra plot
# Independent installation:
uv tool install "odsbox-cli[plot]"
```

The base CLI does not require matplotlib. Preview tools live under **`gui`**,
not top-level `plot` or `table` names:

```python
gui.plot()  # last DataFrame (_)
gui.plot(samples, columns=["Speed", "Torque"])
gui.plot(samples, x="Time", columns=["Speed"], max_points=2000)
gui.table(samples)  # original values, paged
gui.table(samples, columns=["Time", "Speed", "Torque"])
gui.plot(samples, columns=["Speed"], save="speed.png")
gui.table(samples, save="samples-page.png")
```

These are schema-dependent column examples. Both methods return `None` and
leave the DataFrame, index, attrs and `_` untouched. They work entirely locally:
no additional ODS reads. `help gui`, `help plot`, and `help table` work offline.

**Plot:** by default, display the first 8 real numeric signal columns (excluding
an explicit x column); select others with `columns=`. Boolean, complex and text
signals are not plotted. Each signal has its own stacked axes with shared x and
available unit metadata. The index supplies x, or use a numeric/datetime/timedelta
column. Unsupported index types use row positions with a notice. Original row
order is retained, not sorted; timedelta axes use seconds.

Large signals use a **min/max envelope capped at 2,000 points per series** by
default, including endpoints. This preserves isolated spikes in finite-data bins
better than every-Nth sampling. Missing/nonfinite samples conservatively break
their entire bin; extrema in those bins can be omitted. This is not a lossless
analysis/resampling result. `max_points` must be an integer >=6. Zoom/pan uses
the fixed reduced data, not a full-resolution reload.

Reduction scans each selected signal once: startup still depends on row count
and hardware, but rendering is bounded. It does not construct a melted or copied
version of the entire frame. Partial-result metadata is displayed prominently.

**Table:** render original values, not plot-reduced samples, in **50-row by
8-column pages**, plus the original index. Previous/Next controls navigate row
and column pages, with disabled boundary buttons. Only visible cells are
formatted; long/multiline values are shortened/escaped for display (up to 40
characters, further bounded by column width). Floats display 6 significant digits,
without changing stored precision. No sorting,
filtering or editing widgets: use pandas first. Pages reference the existing
frame, not an immutable full-data snapshot. Saving a table writes **only its
first page**; pandas exports remain the full-data export mechanism.

**Windows and headless use:** interactive previews require a working matplotlib
desktop GUI backend, such as TkAgg with tkinter supplied by your Python installation.
No Qt/PySide dependency is added. Windows are nonblocking and their events are
pumped while the terminal prompt is idle, including while editing/searching.
Long synchronous reads or Python commands can temporarily pause GUI interaction.
Exit closes only helper-owned windows. Existing backend selection is respected;
notebook/browser backends are not supported by this terminal integration.

Scripts/piped input should use `save=`. In headless environments select Agg
(for example, `$env:MPLBACKEND = "Agg"` in PowerShell) and save an image.
Missing dependencies, unsupported backends and save errors are reported, not
silently treated as successful displays. No windows open automatically for bulk
reads or other results.

### Pandas operations and terminal output

```text
runs = db.find({AoMeasurement: {}, $attributes: {id: 1, name: 1}})
runs.head(5)
runs.tail(5)
runs[["id", "name"]].sort_values("name")
runs[runs["id"] > 100]
runs.query("id > 100")
runs.to_csv("runs.csv", index=False)
runs.to_json("runs.json", orient="records", date_format="iso")
```

`pd` is pandas. Named variables last for this shell session. `_` holds the last
successful query/model result, even after assignment. Displaying another
DataFrame expression updates `_`; scalar output does not. Assignments do not
print. Failed queries leave the previous result intact. If a query succeeds but
a chained local operation fails, the successful query remains available.

Tables preview at most **20 rows**, with terminal-aware column and cell-width
limits, full shape and truncation notices. **All fetched data is retained.**
There is **no implicit server row limit**: use `$options: {$rowlimit: N}` to
bound network transfers and memory. Export calls use pandas directly and errors
are not hidden; choose paths deliberately because pandas can overwrite files.

This is a **trusted local Python console, not a sandbox**. There are no CLI
commands for modifying server data/models, but arbitrary Python has your normal
permissions. Use server credentials with read-only permissions if enforcement
is needed. No automatic reconnect/retry replays queries.

## Development and verification

```powershell
uv sync --locked --all-groups
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src scripts tests
uv run --locked pytest --cov=odsbox_cli --cov-report=term-missing --cov-report=xml --cov-fail-under=85
uv run --locked python scripts\package_smoke.py
```

Mypy checks application code and scripts strictly. Tests allow unannotated
functions and calls to untyped helpers, but their bodies and all other strict
checks remain enabled. `uv run --locked mypy` defaults to `src scripts tests`;
`uv run --locked mypy tests` checks tests using the local source tree.
Ruff lint and formatting cover the entire repository, including tests.

Offline tests enforce **at least 85% total package line coverage**, including
unimported modules. Linux/Windows CI both enforce this gate. There is no per-file
or branch-percentage requirement. Missing-line and XML reports are produced.
Clean wheel **and** sdist installations are tested outside the checkout.
Semantic-release stamping is tested in a disposable Git repository without
pushing or publishing.

### Explicit live tests (local-only)

Normal tests exclude the `integration` marker. To run read-only integration
tests against the demo server, set process-local variables:

```powershell
$env:ODSBOX_TEST_URL = "https://docker.peak-solution.de:10032/api"
$env:ODSBOX_TEST_USERNAME = "<demo username>"
$credential = Read-Host "Demo password" -AsSecureString
$env:ODSBOX_TEST_PASSWORD = [System.Net.NetworkCredential]::new("", $credential).Password
uv run --locked pytest -m integration -q
Remove-Item Env:\ODSBOX_TEST_PASSWORD
```

Do not commit passwords or save them in command history/configuration files.
Explicit live runs fail on missing settings, authentication/network errors,
or assertions; they never quietly skip/fall back to mocks. They open/close ODS
sessions, read the model, issue explicitly bounded reads, and export only to
temporary local files. They do **not** modify server data/models or your pilot
registry/keyring. Session DELETE/logout is necessary lifecycle cleanup.
Basic authentication is live-tested; M2M/OIDC are covered with mocked factories.
Live tests run separately and do not inflate offline coverage.

### CI and releases

The pipeline adapts
[odsbox-diff](https://github.com/peak-solution/odsbox-diff): Ruff, mypy (strict
source/scripts, relaxed body-checked tests),
offline pytest-cov, Linux/Windows build/install checks, dependency audit, and
weekly uv/GitHub Actions Dependabot updates.

On `main`, after all checks pass, **python-semantic-release** uses Conventional
Commits (`feat:`, `fix:`, breaking changes) to stamp `project.version`, update
`uv.lock` without upgrading unrelated dependencies, create a changelog/version
commit and `v{version}` tag, and build distributions once. The installed version
comes from package metadata. Commits requiring no new version do not publish.
The release job publishes the exact new distributions with
`uv publish --trusted-publishing always`.

Maintainers must configure the real GitHub remote, main-branch rules and Actions
write permissions, a protected **`pypi`** environment, PyPI package-name ownership
and a trusted publisher matching the repository/workflow/environment. No long-lived
PyPI token is required. This setup cannot be completed just by adding YAML.

If publication fails after a version/tag has been created, do not blindly bump
another version. Inspect the failed job and PyPI for partial uploads, then recover
the **same tagged artifacts** through an approved trusted-publisher job. Never
overwrite an existing PyPI distribution. Actual publishing is not performed by
local verification.

## License

Apache-2.0. See [LICENSE](LICENSE).