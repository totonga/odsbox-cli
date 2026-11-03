"""Offline help topics shared by the shell and documentation tests."""

TOPICS = {
    "connection_template": """odsbox-cli --generate-connection-template AUTH_TYPE PATH
AUTH_TYPE: basic, m2m or oidc. PATH must end in .ods-pilot.con.toml (case-insensitive).
Example: odsbox-cli --generate-connection-template oidc "C:\\temp\\my_server.ods-pilot.con.toml"
Creates an editable, commented, pilot-compatible TOML file, then exits.
The name is the filename before its first dot: my_server.ods-pilot.con.toml -> my_server.
The derived name must not be empty; edit it if desired.
Replace example.invalid URLs and login/client settings.
Import after editing: odsbox-cli connections import "PATH"
Never overwrites an existing file/symlink. The parent directory must already exist.
TLS verification stays enabled. OIDC defaults to http://127.0.0.1:12345,
with insecure redirects disabled; register that URI with your identity provider.
No passwords/client secrets in the template. Basic/M2M use OS keyring service
ods-pilot, account URL::username-or-client_id, or hidden terminal prompts.
OIDC uses browser login when connecting, not while generating the template.
No registry/history/keyring reads, network, browser, imports or shell at generation.
Cannot combine with --script or process-level connections subcommands.
TOML only; ATFX templates are not offered because the CLI cannot open ATFX.
See help connections for supported fields/authentication and import behavior.""",
    "script": """odsbox-cli --script PATH   # short option: -s PATH
Run a trusted UTF-8 CLI command file (optional BOM) before the interactive prompt.
Use shell commands, relaxed db.find queries, assignments and multiline expressions.
End compound Python blocks (for/if/def/...) with an unindented blank line or EOF.
Keep internal blank lines indented; shell commands are standalone top-level commands.
Stops at the first error with filename/line information; no rollback or retries.
With terminal stdin: retain connection/results/variables and open the prompt for debugging.
Without terminal stdin: exit after the file; never consume additional piped input.
Exit status: 0 on success, 1 on script failure (even after debugging), 130 on cancellation.
exit/quit end the whole session; Python SystemExit is honored. Cleanup runs on exit.
Relative paths use the process working directory, not the script directory.
Script contents are not added to history; commands entered while debugging are.
GUI windows require terminal/backend support and update once the prompt is idle;
save= works without a terminal. Long synchronous commands can pause windows.
Cannot combine --script with the process-level connections subcommand.
This executes trusted Python with your permissions, not a sandbox or plain Python module.
For independent Python projects instead, see help script_starter.""",
    "script_starter": """db.script_starter(r"C:\\temp")
db.script_starter(r"C:\\temp", open_folder=False)
Creates a new timestamped child directory and returns its Path; never overwrites.
Files: pyproject.toml, script.py, README.md, .vscode/mcp.json.
Uses the connected settings snapshot and last successful db.find query as evaluated
JSON data. No query yet: inspect model entities. Nonportable query values fail clearly.
Successful use/reconnect/disconnect clears the saved query; failed operations preserve it.
Generated scripts use standalone odsbox (no CLI dependency), pilot-compatible OS keyring
for basic/M2M, or browser OIDC login. Secrets are never read/exported during generation.
Review query/config values before sharing: they may contain sensitive application data.
Creation does not install/run/connect/launch MCP. Default opens VS Code or file explorer;
open_folder=False disables launching. Opening failures warn but keep the created project.
Inside the generated folder: uv sync; uv run python script.py. See its README for keyring.
Query fetch limits are preserved; the output preview limit does not bound data fetching.
Does not modify _, DataFrames, connection or registry. Requires a selected connection.""",
    "gui": """gui.plot()    # preview the last DataFrame (_); does not replace it
gui.table()   # original values in a paged table
gui.plot(samples, columns=["Speed"], max_points=2000, save="speed.png")
Optional dependency: uv sync --extra plot or uv tool install "odsbox-cli[plot]".
GUI windows require an interactive matplotlib backend (e.g. TkAgg with tkinter).
Headless/scripts: use save= explicitly, with MPLBACKEND=Agg if needed.
Windows stay responsive while the prompt is idle, including history search.
Long synchronous commands can temporarily pause windows. Exit closes owned windows.
See help plot and help table. There are no top-level plot()/table() aliases.""",
    "plot": """gui.plot(frame=None, *, columns=None, x=None, max_points=2000, save=None)
Defaults to _, first 8 real numeric signals, index as x; columns= selects explicitly.
Numeric/datetime/timedelta x supported; unsupported index uses row positions with notice.
Stacked signal axes share x; available bulk units and partial-result status are shown.
Large signals use min/max bucket extrema, <= max_points per signal, including endpoints.
Missing/nonfinite bins conservatively break lines; spikes inside such bins may be omitted.
max_points must be an integer >=6. This is a fixed preview, not lossless resampling.
Zoom does not reload full data. Initial reduction still scans each selected signal once.
gui.plot(samples, x="Time", columns=["Speed"], save="speed.png")
save writes an image without opening a GUI; otherwise a terminal/GUI backend is required.
Original values, index, attrs and _ are unchanged. No server reads. See help gui.""",
    "table": """gui.table(frame=None, *, columns=None, save=None)
Read-only GUI alternative: original rows, 50 rows by 8 columns per page, plus index.
Previous/Next rows and columns navigate; boundary controls are disabled.
columns= selects/reorders columns. Nonnumeric cells are supported; text is capped at
40 characters (or column width); floats use 6 significant digits for display only.
Range/total counts and partial-result status are shown.
No downsampling, sorting, filtering or editing widgets: transform with pandas first.
save="page.png" saves only the first page; use DataFrame.to_csv for full exports.
Pages read the existing frame; they are not a full immutable snapshot.
Original data and _ stay unchanged. See help gui for optional installation/backends.""",
    "reconnect": """db.reconnect()
Establish a fresh session for the currently selected server after a timeout.
Uses current registry settings and normal authentication (keyring/hidden prompt/OIDC).
May prompt or open login again; no plaintext credentials are retained for reconnect.
Refreshes the cached model while preserving db, local variables, DataFrames and _.
Failures propagate and leave the old session reference/model intact (possibly expired).
After disconnect or before use <server>, reconnect fails; select a server first.
Old-session logout failures warn but do not undo a successful replacement.
Returns None. No automatic reconnect or replay of failed queries/bulk reads.
Server-side transient state is not restored.""",
    "bulk": """db.bulk(submatrix_iid, column_patterns=None, column_patterns_case_insensitive=False,
        date_as_timestamp=True, set_independent_as_index=True, values_start=0, values_limit=0,
        *, raise_on_partial_result=False, valid_flag=None)
Delegates to con_i.bulk.data_read with all parameters unchanged. Tab completes keywords.
db.bulk(42, column_patterns=["Time", "*speed*"], values_limit=100)
Discover a real AoSubmatrix ID via db.model.find() and db.find() first.
Patterns support * and ?. values_start is zero-based; values_limit=0 means unlimited.
A single independent column becomes the index by default. Dates become timestamps.
DataFrame index, dtypes and attrs (unit_names, partial_result) are preserved; _ is updated.
Partial results warn; raise_on_partial_result=True propagates the upstream error.
valid_flag masks invalid values, not rows. None disables masking; upstream treats BOTH
True and False as mask 15. Use an integer for an explicit quality mask.
Limits depend on upstream/server sequence handling: the demo's mixed stored/implicit
columns can return unequal lengths for bounded reads. That upstream error is propagated;
select individual column patterns to inspect affected data.""",
    "history": """Interactive commands persist in ~/.odsbox-cli/history.sqlite3 (latest 1000 entries).
Up/Down recall old commands at multiline boundaries. Ctrl-R searches across sessions,
case-insensitively; repeated Ctrl-R finds older matches. Enter recalls for editing only,
not execution. Escape/Ctrl-C restores the original draft and cursor. No match is shown.
Blank input and commands starting with a space are not recorded; consecutive duplicates
are suppressed. Search text and cancelled drafts are not recorded.
Start with odsbox-cli --no-history to disable all disk-history reads/writes.
History is plaintext and may contain sensitive queries/values. Hidden credential prompts
are never recorded. Delete the history file while shells are closed to clear it.
Storage errors warn once and fall back to bounded memory for the process.""",
    "queries": """db.find({AoMeasurement: {}, $options: {$rowlimit: 20}})
Relaxed identifier/$/dotted keys are strings. Quote string values and special keys.
Values can be Python expressions: selected_id = 42
db.find({AoMeasurement: {id: selected_id}})
true/false/null and True/False/None work. Use # comments; // is floor division.
Build a normal Python dict first for computed keys: db.find(query).
No implicit server limit: $options.$rowlimit bounds fetching, not just printing.
Application names/base names depend on your server: inspect db.model.find() first.""",
    "model": """db.model.find()                  # entity names, base names and IDs
db.model.find("AoMeasurement")    # attributes, types, enum names, unit IDs
db.model.relations("AoMeasurement")  # relation targets and cardinalities
Prefer explicit application entity names when a base name has multiple derivations.
The model is cached for the connection; db.reconnect() refreshes it. See help reconnect.""",
    "results": """runs = db.find({AoMeasurement: {}, $attributes: {id: 1, name: 1}})
runs.head(5)
runs.tail(5)
runs[["id", "name"]].sort_values("name")
runs[runs["id"] > 100]
runs.query("id > 100")
runs.to_csv("runs.csv", index=False)
runs.to_json("runs.json", orient="records", date_format="iso")
_ keeps the last successful query/model or displayed DataFrame. Assignments do not print.
Preview: at most 20 rows; rows/columns/cells may be shortened, but data is retained.
pd is pandas. Python assignments/imports work. Results live only in this process.
This is trusted Python, not a sandbox; read-only server use is a convention.""",
    "connections": """connections list
connections import "example.ods-pilot.con.json" --name "Test server"
connections import "example.ods-pilot.con.toml"
connections import-pilot [--path PATH_TO_SERVERS_JSON]
use Test server
db.reconnect()  # fresh session for the selected server; see help reconnect
disconnect
Pilot registry: ~/.ods-pilot/servers.json (read-only discovery).
CLI imports: ~/.odsbox-cli/servers.json (no secrets).
Passwords/client secrets reuse keyring service ods-pilot and URL::username-or-client_id.
Missing secrets are prompted without echo; not saved automatically.
Supported: basic, m2m, oidc. ATFX entries are retained but cannot be opened.
Name/settings conflicts fail; identical repeated imports are a reported no-op.""",
    "completion": """Suggestions appear while typing. Tab opens/cycles; Shift-Tab cycles backward.
Enter accepts a selected suggestion without executing. Press Enter again to submit.
Escape dismisses/restores the input; incomplete input continues onto another line.
Typing (, [, {, ' or " inserts its mate at safe boundaries, with the cursor inside.
Strings/comments and escaped quotes stay literal; pairing is conservative.
Insertion only: closers do not skip and Backspace removes one character.
Use Right Arrow to move past an inserted mate. No auto-indentation or selection wrapping.
Bracketed paste and completion insertion remain verbatim; history search is not paired.
Terminals without bracketed paste cannot distinguish pasted keystrokes from typing.
Complete commands, use server names, entities, attributes, relation paths, operators,
enum labels, model arguments, bulk keyword parameters, and DataFrame column references.
Completion uses only cached/local metadata: no queries or Python calls.
Ambiguous base entities are annotated; use an explicit application name.
Basic input syntax colors aid readability; NO_COLOR disables them. Output is unchanged.
Ctrl-C cancels input/execution; Ctrl-D exits. See help history for persistent recall.""",
}


def help_text(topic: str = "") -> str:
    if not topic:
        return (
            "odsbox-cli: inspect ASAM ODS servers\nhelp <topic>: "
            + ", ".join(TOPICS)
            + "\nuse <server> | disconnect | exit"
        )
    if topic not in TOPICS:
        raise ValueError(f"Unknown help topic {topic!r}. Available: {', '.join(TOPICS)}")
    return TOPICS[topic]
