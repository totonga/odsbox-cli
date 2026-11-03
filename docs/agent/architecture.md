# Architecture and behavioral invariants

Use this document when changing behavior. For complete usage and examples, see
the [README](../../README.md) and [inline help](../../src/odsbox_cli/help.py).
Source and tests take precedence if these notes drift.

## Module map

| Module | Responsibility |
| --- | --- |
| [cli.py](../../src/odsbox_cli/cli.py) | Shell namespace, command dispatch, result previews, terminal controls and cleanup |
| [connections.py](../../src/odsbox_cli/connections.py) | Config validation, pilot/CLI registries, credentials and connection factory |
| [database.py](../../src/odsbox_cli/database.py) | Shared session lifecycle and stable `db`, model and bulk facades |
| [syntax.py](../../src/odsbox_cli/syntax.py) | Tolerant token scanning and relaxed inline-query compilation |
| [completion.py](../../src/odsbox_cli/completion.py) | Cached-model/local completion and full-token replacement |
| [history.py](../../src/odsbox_cli/history.py) | Bounded SQLite history and warned memory fallback |
| [highlighting.py](../../src/odsbox_cli/highlighting.py) | Input-only syntax styles; honors `NO_COLOR` |
| [help.py](../../src/odsbox_cli/help.py) | Offline help topics, also used for topic completion |
| [preview.py](../../src/odsbox_cli/preview.py) | Optional `gui.plot`/`gui.table`, reduction, paging and owned-window lifecycle |
| [script_starter.py](../../src/odsbox_cli/script_starter.py) | Independent uv project generation from nonsecret session/query snapshots |
| [editing.py](../../src/odsbox_cli/editing.py) | Conservative typed delimiter-pair decisions without evaluation |

## Connections and reconnect

- Discover the pilot registry read-only at `~/.ods-pilot/servers.json`.
  Explicit imports write the separate `~/.odsbox-cli/servers.json`, not pilot's
  registry. Retain conflict validation, idempotent imports and atomic writes.
- Portable JSON/TOML settings follow odsbox-pilot. Basic, M2M and OIDC use the
  existing factory. ATFX entries can be imported/listed but are not opened.
- `--generate-connection-template AUTH_TYPE PATH` is a one-shot, local TOML
  writer for basic/M2M/OIDC. Reuse Config defaults and portable mode-specific
  fields, not settings() with unrelated modes. No IDs/secrets, registry/keyring
  reads, authentication or shell startup. Require a `.ods-pilot.con.toml` destination and
  existing parent; exclusive creation must never overwrite files/symlinks.
  Derive the initial connection name from the filename before its first dot
  (all extensions removed); reject empty names before creating the file.
  Generation conflicts with `--script` and process connection subcommands.
- Registry files must not contain secrets. Reuse keyring service `ods-pilot`
  with account `URL::username-or-client_id`; missing secrets use hidden prompts.
  Do not add an echoed-input fallback or retain credentials just for reconnect.
- `Session.use` creates a replacement and obtains its model before swapping
  references. Failure preserves the old connection, selected name and model;
  a failed replacement is cleaned up. Only then is the old connection logged out.
- `db.reconnect()` resolves the selected name using current registry settings
  and normal authentication. It refreshes the model, returns `None`, and keeps
  the same facades and local namespace. Login may be needed again.
- There is no automatic reconnect or replay of failed reads. A retained session
  after a reconnect failure may still be expired. Explicit disconnect clears the
  selected name; reconnect then requires `use <server>` first.
- Logout failures warn; they must not undo an already successful replacement.
  Server-side transient state is not restored by reconnect.
- Capture a detached Config only on successful connection replacement for starter
  export. `db.find` remembers strict JSON data only after success, independently
  of `_`. Nonportable values are reported at generation, not as query failures.
  Successful use/reconnect/disconnect clears the query. Starter generation never
  accesses credentials/server data and does not change `_`. See
  [starter tests](../../tests/test_script_starter.py).

See [lifecycle tests](../../tests/test_database.py),
[connection tests](../../tests/test_connections.py), and
[shell tests](../../tests/test_cli.py).

## Relaxed JAQuel is still Python

- Normalization applies to inline dictionaries passed to `db.find(...)`, not
  arbitrary dictionaries or bulk calls. Identifier, `$` and dotted query keys
  become strings; special keys and string values still need quotes.
- Values may be Python expressions and must execute only once. Support
  `true`/`false`/`null` aliases alongside Python constants.
- `#` introduces comments; `//` is floor division, not a JavaScript comment.
  Computed keys belong in ordinary Python dictionaries constructed beforehand.
- Distinguish incomplete editable input from completed invalid syntax. Parsing,
  completion and highlighting share lexical helpers but must not accidentally
  change execution semantics.

See [syntax tests](../../tests/test_syntax.py). The console executes trusted
Python with the user's permissions; do not describe it as sandboxed.

## Startup command scripts

- `--script/-s PATH` runs trusted UTF-8 (optional BOM) CLI commands before the
  prompt in the same shell namespace. It is not a plain Python-module runner.
- The new file reader buffers compound AST statements until an unindented blank
  line or EOF; internal blank lines must remain indented. Normalization and
  execution remain shared. Compile with original filenames/line numbers.
- Stop at the first error; retain partial state for terminal debugging and keep
  failure status sticky (1; startup cancellation 130). Nonterminal execution
  exits after the script and must not consume stdin. Legacy piped execution
  without the option still continues on errors.
- Do not chdir or record file contents in history. `exit`/`quit` end the session;
  SystemExit is honored. Use one final cleanup boundary across file and prompt.
- Initialize interactive terminal/GUI capability before startup; GUI pumping
  starts at the prompt. Nonterminal previews still require explicit saving.
- `--script` conflicts with process-level connection subcommands. The standalone
  project generator `db.script_starter` is independent of this file runner.

## Completion and terminal editing

- Use the connection's cached model and local namespace only. Do not query
  servers, fetch distinct values/IDs, consult credentials, or evaluate expressions
  to generate suggestions.
- Respect application/base entity names, ambiguity, relation targets and nested
  JAQuel context. Do not invent attributes for ambiguous base entities.
- Bulk keyword completion uses `Database.bulk`'s explicit signature and omits
  used arguments; it must work without fetching model metadata.
- `SpanCompletion` and `CompletionBuffer` replace full tokens, including suffixes
  after the cursor. Keep preview, accept and cancellation edits consistent.
- Enter accepts a selected completion without executing it; a subsequent Enter
  submits. Preserve multiline editing and history navigation at boundaries.
- Typed brackets/quotes insert mates only at safe boundaries outside strings and
  comments. This is insertion only: no closer skipping, paired deletion, selection
  wrapping or indentation. Preserve bracketed paste/completion insertion and
  disable pairing in search. See [editing tests](../../tests/test_editing.py).
- Syntax highlighting changes presentation only. `NO_COLOR` disables input
  styles; table output and exports are not colored by the input lexer.

See [completion tests](../../tests/test_completion.py),
[bulk tests](../../tests/test_bulk.py), and
[highlighting tests](../../tests/test_highlighting.py).

## DataFrames and bulk reads

- Return real pandas DataFrames. Successful find/model/bulk calls remember their
  result in `_`, even when assigned. Assignments are silent; a displayed
  DataFrame expression updates `_`, while scalar display does not.
- Failed reads preserve the previous result. If a read succeeds and subsequent
  local chaining fails, keep the successful read available.
- The preview is bounded to 20 rows with column/cell truncation; the stored
  DataFrame is not truncated. There is no implicit query fetch limit: use JAQuel
  `$options.$rowlimit` to bound reads.
- `db.bulk(...)` delegates to the current connection's `bulk.data_read(...)`.
  Preserve every upstream parameter, default and keyword-only constraint, plus
  the returned object's index, dtypes and `attrs`.
- Bulk patterns use `*`/`?`; sample offsets are zero-based and `values_limit=0`
  means unlimited. A single independent column becomes the index by default.
- Warn on `attrs["partial_result"]`; strict partial-result mode and other errors
  propagate, not success-shaped empty frames.
- Forward `valid_flag` unchanged: it masks values, not rows. Upstream maps both
  booleans to mask 15; `None` disables masking.
- Known demo/upstream limitation: some stored sequences ignore sample limits
  while implicit sequences honor them, causing unequal-length array errors when
  combined. Do not silently slice or hide the error. Individual column patterns
  can help inspection; verify returned lengths rather than assuming a bound.

## History and privacy

- Interactive submissions persist as whole entries in
  `~/.odsbox-cli/history.sqlite3`, retaining the latest 1000 transactionally.
  Refresh between prompts so other sessions' entries become discoverable.
- Exclude blank and first-character-space commands before trimming or caching.
  Suppress consecutive duplicates. Do not record cancelled drafts, search text,
  completion previews, hidden credential prompts, or piped/scripted input.
- `--no-history` forbids all disk-history reads/writes, while bounded in-memory
  recall remains available. Storage failures warn once and fall back to memory.
- Ctrl-R performs case-insensitive reverse search; repeat for older matches.
  Enter recalls for editing, not execution; Escape/Ctrl-C restores draft/cursor.
- History is plaintext, not a credential store. POSIX private creation modes
  apply to new storage; do not change existing permissions or promise encryption
  or equivalent Windows ACL enforcement. Journals can also contain command text.

See [history tests](../../tests/test_history.py) and the pipe-input terminal
interaction tests in [test_cli.py](../../tests/test_cli.py).

## Optional GUI previews

- Register only `gui` in the shell namespace, with `plot` and `table` methods.
  Defaults resolve `_` at call time; both return None without changing it.
- Matplotlib is an optional `plot` extra, imported only on a preview call.
  Preserve base installs and never import pyplot during completion/help/startup.
- Plot first 8 numeric signals by default on stacked axes, with <=2000 points
  per signal via ordered min/max buckets. Reduction is a linear scan; missing
  bins conservatively break lines, possibly omitting extrema there.
- Table formats original rows in 50x8 pages plus index, not sampled plot data.
  Navigation retains a frame reference and only formats visible cells.
- Image saving is explicit and supports headless Agg; table saves its first
  page only. Interactive windows require an interactive backend and terminal.
- Prompt-toolkit pumps owned-window events on its main-thread event loop.
  Synchronous commands may pause GUI interaction. Do not move GUI work to worker
  threads or assume show alone maintains responsiveness.
- Close only helper-owned figures on exit, never all user matplotlib figures.
  See [preview tests](../../tests/test_preview.py) and README for limitations.
