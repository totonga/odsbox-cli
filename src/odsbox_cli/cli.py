"""Console entry points and trusted Python shell."""

from __future__ import annotations

import argparse
import ast
import asyncio
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Never

import pandas as pd
from prompt_toolkit import search
from prompt_toolkit.application import Application
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.widgets import SearchToolbar

from odsbox_cli import __version__
from odsbox_cli.completion import CompletionBuffer, InspectorCompleter
from odsbox_cli.connections import Registry, generate_connection_template, portable_file, read_registry
from odsbox_cli.database import Database, Session
from odsbox_cli.editing import PAIRS, closing_mate
from odsbox_cli.help import help_text
from odsbox_cli.highlighting import INPUT_STYLE, InputLexer
from odsbox_cli.history import CommandHistory
from odsbox_cli.preview import Gui
from odsbox_cli.syntax import compile_input


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError(message)


def parser() -> Parser:
    root = Parser(prog="odsbox-cli", description="Inspect ASAM ODS servers with JAQuel and pandas")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--no-history", action="store_true", help="Do not read or write persistent command history")
    startup = root.add_mutually_exclusive_group()
    startup.add_argument("--script", "-s", type=Path, help="Run a CLI command file, stopping at its first error")
    startup.add_argument(
        "--generate-connection-template",
        nargs=2,
        metavar=("AUTH_TYPE", "PATH"),
        help="Create a basic, m2m or oidc template ending in .ods-pilot.con.toml (never overwrites)",
    )
    commands = root.add_subparsers(dest="command")
    connections = commands.add_parser("connections", help="List or import pilot-compatible connections")
    actions = connections.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List pilot and CLI configurations")
    importer = actions.add_parser("import", help="Import a portable JSON/TOML connection")
    importer.add_argument("path", type=Path)
    importer.add_argument("--name", help="Import under a distinct name")
    pilot = actions.add_parser("import-pilot", help="Copy pilot's saved connection registry")
    pilot.add_argument("--path", type=Path)
    return root


def connection_command(args: argparse.Namespace, registry: Registry, output: Callable[[str], None]) -> None:
    if args.action == "list":
        rows = [
            {"name": c.name, "url": c.url, "auth": c.auth_type, "source": source} for c, source in registry.entries()
        ]
        output(pd.DataFrame(rows, columns=["name", "url", "auth", "source"]).to_string(index=False))
    else:
        if args.action == "import":
            configs = [portable_file(args.path, args.name)]
        else:
            path = args.path or registry.pilot_path
            if not path.is_file():
                raise ValueError(f"Pilot registry not found: {path}")
            configs = read_registry(path)
        count = registry.import_configs(configs)
        output(
            f"Imported {count} connection(s)" if count else "No changes: connections already imported or registry empty"
        )


def script_commands(lines: Iterable[str], *, filename: str) -> Iterator[tuple[int, str]]:
    pending = ""
    first_line = 1
    compound = False
    for number, line in enumerate(lines, 1):
        if not pending:
            first_line = number
            compound = False
        pending += line
        if compound:
            if line.rstrip("\r\n") != "":
                continue
        else:
            # Shell commands must bypass Python completeness checks.
            stripped = pending.strip()
            command = stripped in {"exit", "quit", "help", "disconnect"} or stripped.startswith(
                ("help ", "use ", "connections ")
            )
            if not command:
                tree = compile_input(pending, filename=filename, first_line=first_line)
                if tree is None:
                    continue
                compound = any(
                    isinstance(
                        node,
                        (
                            ast.AsyncFor,
                            ast.AsyncFunctionDef,
                            ast.AsyncWith,
                            ast.ClassDef,
                            ast.For,
                            ast.FunctionDef,
                            ast.If,
                            ast.Match,
                            ast.Try,
                            ast.TryStar,
                            ast.While,
                            ast.With,
                        ),
                    )
                    for node in tree.body
                )
                if compound and line.rstrip("\r\n") != "":
                    continue
        yield first_line, pending
        pending = ""
    if pending.strip():
        yield first_line, pending


class Shell:
    def __init__(
        self, session: Session | None = None, output: Callable[[str], None] = print, *, history_enabled: bool = True
    ) -> None:
        self.session = session or Session(Registry())
        self.output = output
        self.history_enabled = history_enabled
        self.namespace: dict[str, object] = {"pd": pd}
        self.db = Database(self.session, self.remember)
        self.namespace["db"] = self.db
        self.gui = Gui(self.namespace, output)
        self.namespace["gui"] = self.gui
        self.completer = InspectorCompleter(lambda: self.session.model, self.server_names, self.namespace)

    def server_names(self) -> list[str]:
        try:
            return [c.name for c, _ in self.session.registry.entries()]
        except (ValueError, OSError) as exc:
            self.output(f"Completion registry error: {exc}")
            return []

    def remember(self, result: pd.DataFrame) -> None:
        self.namespace["_"] = result

    def display(self, result: object) -> None:
        if result is None:
            return
        if isinstance(result, pd.DataFrame):
            self.remember(result)
            max_cols = max(1, shutil.get_terminal_size((100, 24)).columns // 20)
            self.output(result.to_string(max_rows=20, max_cols=max_cols, max_colwidth=40))
            self.output(f"[{len(result)} rows x {len(result.columns)} columns]")
            if len(result) > 20 or len(result.columns) > max_cols:
                self.output("Preview truncated; full data remains available in _ and named variables.")
            preview = result if len(result) <= 20 else pd.concat([result.head(10), result.tail(10)])
            if any(len(str(value)) > 40 for value in preview.to_numpy().flat):
                self.output("Long cells shortened in preview; original values retained.")
        else:
            self.output(repr(result))

    def execute(self, text: str, *, filename: str = "<odsbox>", first_line: int = 1) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        if stripped in {"exit", "quit"}:
            raise EOFError
        if stripped == "help" or stripped.startswith("help "):
            self.output(help_text(stripped[4:].strip()))
            return True
        if stripped == "disconnect":
            self.session.disconnect()
            self.output("Disconnected")
            return True
        if stripped.startswith("use "):
            name = stripped[4:].strip()
            if name.startswith(("'", '"')):
                name = ast.literal_eval(name)
            self.session.use(name)
            self.output(f"Connected to {name}")
            return True
        if stripped.startswith("connections "):
            # Windows paths retain backslashes; quote handling is limited to shell words.
            try:
                args = parser().parse_args(shell_words(stripped))
            except SystemExit as exc:
                if exc.code:
                    raise ValueError("Invalid connection command") from exc
                return True
            connection_command(args, self.session.registry, self.output)
            return True
        tree = compile_input(text, filename=filename, first_line=first_line)
        if tree is None:
            return False
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            final = tree.body.pop()
            assert isinstance(final, ast.Expr)
            exec(compile(tree, filename, "exec"), self.namespace)
            self.display(eval(compile(ast.Expression(final.value), filename, "eval"), self.namespace))
        else:
            exec(compile(tree, filename, "exec"), self.namespace)
        return True

    def run_script(self, path: Path) -> int:
        filename = str(path.resolve())
        first_line = 1
        try:
            with path.open(encoding="utf-8-sig") as source:
                for first_line, text in script_commands(source, filename=filename):
                    if not self.execute(text, filename=filename, first_line=first_line):
                        raise SyntaxError("Incomplete input at EOF", (filename, first_line, 1, None))
        except EOFError:
            raise
        except KeyboardInterrupt:
            self.output(f"{filename}:{first_line}: Cancelled")
            return 130
        except Exception as exc:
            line = first_line
            if isinstance(exc, SyntaxError) and exc.filename == filename:
                line = exc.lineno or first_line
            traceback = exc.__traceback__
            while traceback is not None:
                if traceback.tb_frame.f_code.co_filename == filename:
                    line = traceback.tb_lineno
                traceback = traceback.tb_next
            self.output(f"{filename}:{line}: {type(exc).__name__}: {exc}")
            return 1
        return 0

    def run(self, script: Path | None = None) -> int:
        self.output("odsbox-cli: type help, use <server>, Tab for completion, or Ctrl-R for history. Ctrl-D exits.")
        status = 0
        try:
            interactive = sys.stdin.isatty()
            terminal = Terminal(self) if interactive else None
            if script is not None:
                status = self.run_script(script)
            if terminal is not None:
                while True:
                    try:
                        self.execute(terminal.read())
                    except EOFError:
                        raise
                    except KeyboardInterrupt:
                        self.output("Cancelled")
                    except Exception as exc:
                        self.output(f"{type(exc).__name__}: {exc}")
            elif script is None:
                pending = ""
                for line in sys.stdin:
                    pending += line
                    try:
                        if self.execute(pending):
                            pending = ""
                    except EOFError:
                        return status
                    except Exception as exc:
                        self.output(f"{type(exc).__name__}: {exc}")
                        status = 1
                        pending = ""
                if pending.strip():
                    raise SyntaxError("Incomplete input at EOF")
        except EOFError:
            pass
        finally:
            try:
                self.gui.close()
            finally:
                self.session.disconnect()
        return status


def shell_words(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in text:
        if quote:
            if character == quote:
                quote = None
            else:
                current.append(character)
        elif character in "'\"":
            quote = character
        elif character.isspace():
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    if quote:
        raise ValueError("Unclosed path/name quote")
    if current:
        words.append("".join(current))
    return words


class Terminal:
    def __init__(self, shell: Shell, history: CommandHistory | None = None) -> None:
        shell.gui.interactive = True
        self.history = history if history is not None else CommandHistory(enabled=shell.history_enabled)
        self.buffer = CompletionBuffer(completer=shell.completer, complete_while_typing=True, history=self.history)
        self.search_toolbar = SearchToolbar(ignore_case=True)
        searching = Condition(lambda: self.application.layout.current_control is self.search_toolbar.control)
        self._draft = Document()
        keys = KeyBindings()

        def insert_opener(event: KeyPressEvent) -> None:
            buffer = self.buffer
            opener = event.data
            mate = "" if buffer.selection_state else closing_mate(buffer.text, buffer.cursor_position, opener)
            buffer.insert_text(opener + mate)
            if mate:
                buffer.cursor_left()

        for opener in PAIRS:
            keys.add(opener, filter=~searching)(insert_opener)

        @keys.add("c-r")
        def reverse_search(event: KeyPressEvent) -> None:
            if searching():
                search.do_incremental_search(search.SearchDirection.BACKWARD)
            else:
                self.buffer.cancel_completion()
                self._draft = self.buffer.document
                search.start_search(direction=search.SearchDirection.BACKWARD)

        @keys.add("enter", filter=searching)
        def accept_search(event: KeyPressEvent) -> None:
            if self._has_match():
                search.accept_search()
            else:
                self._cancel_search()

        @keys.add("escape", filter=searching, eager=True)
        @keys.add("c-c", filter=searching)
        def cancel_search(event: KeyPressEvent) -> None:
            self._cancel_search()

        @keys.add("tab", filter=~searching)
        def tab(event: KeyPressEvent) -> None:
            if self.buffer.complete_state:
                self.buffer.complete_next()
            else:
                candidates = list(shell.completer.get_completions(self.buffer.document, CompleteEvent()))
                if candidates:
                    self.buffer._set_completions(candidates)
                    self.buffer.go_to_completion(0)

        @keys.add("s-tab", filter=~searching)
        def previous(event: KeyPressEvent) -> None:
            self.buffer.complete_previous()

        @keys.add("escape", filter=~searching)
        def escape(event: KeyPressEvent) -> None:
            self.buffer.cancel_completion()

        @keys.add("enter", filter=~searching)
        def enter(event: KeyPressEvent) -> None:
            state = self.buffer.complete_state
            if state and state.current_completion:
                self.buffer.complete_state = None
                return
            self.buffer.complete_state = None
            text = self.buffer.text
            command = text.strip().split(maxsplit=1)[0] if text.strip() else ""
            try:
                complete = (
                    command in {"use", "help", "exit", "quit", "disconnect", "connections"}
                    or compile_input(text) is not None
                )
            except SyntaxError:
                complete = True
            if complete:
                self.history.append_string(text)
                event.app.exit(result=text)
            else:
                self.buffer.insert_text("\n")

        @keys.add("c-c", filter=~searching)
        def cancel(event: KeyPressEvent) -> None:
            event.app.exit(exception=KeyboardInterrupt())

        @keys.add("c-d", filter=~searching)
        def end(event: KeyPressEvent) -> None:
            if not self.buffer.text:
                event.app.exit(exception=EOFError())
            else:
                self.buffer.delete()

        control = BufferControl(
            self.buffer,
            lexer=InputLexer(),
            search_buffer_control=self.search_toolbar.control,
            preview_search=True,
            input_processors=[BeforeInput(lambda: f"{shell.session.name or 'ods'}> ")],
        )
        body = FloatContainer(
            HSplit(
                [
                    Window(control, wrap_lines=True),
                    self.search_toolbar,
                    Window(
                        FormattedTextControl(
                            lambda: "No history match" if searching() and not self._has_match() else ""
                        ),
                        height=1,
                    ),
                ]
            ),
            floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=10))],
        )
        self.application: Application[str] = Application(
            layout=Layout(body, focused_element=control),
            key_bindings=keys,
            full_screen=False,
            style=INPUT_STYLE,
        )
        self.application.pre_run_callables.append(self.buffer.load_history_if_not_yet_loaded)
        self.application.pre_run_callables.append(self._start_gui)
        self._shell = shell
        self._gui_task: asyncio.Task[None] | None = None

    def _start_gui(self) -> None:
        if self._gui_task is None or self._gui_task.done():
            self._gui_task = self.application.create_background_task(self._pump_gui())

    async def _pump_gui(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            if self._shell.gui.has_windows:
                try:
                    self._shell.gui.pump()
                except Exception as exc:
                    self._shell.output(f"GUI event processing failed ({type(exc).__name__}): {exc}")
                    try:
                        self._shell.gui.close()
                    except Exception as cleanup_error:
                        self._shell.output(f"GUI cleanup failed ({type(cleanup_error).__name__}): {cleanup_error}")
                    return

    def _has_match(self) -> bool:
        needle = self.search_toolbar.control.buffer.text.casefold()
        return any(needle in entry.casefold() for entry in [*self.history.get_strings(), self._draft.text])

    def _cancel_search(self) -> None:
        search.stop_search()
        self.buffer.document = self._draft

    def read(self) -> str:
        self.history.refresh()
        self.buffer.reset()

        def pre_run() -> None:
            self.buffer.load_history_if_not_yet_loaded()
            self._start_gui()

        return self.application.run(pre_run=pre_run)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.script is not None and args.command is not None:
            raise ValueError("--script cannot be combined with the connections subcommand")
        if args.generate_connection_template is not None:
            if args.command is not None:
                raise ValueError("--generate-connection-template cannot be combined with the connections subcommand")
            auth_type, destination = args.generate_connection_template
            path = generate_connection_template(auth_type, Path(destination))
            print(f"Created connection template: {path}")
            print(f'Edit its placeholders, then import:\n  odsbox-cli connections import "{path}"')
            return 0
        if args.command == "connections":
            connection_command(args, Registry(), print)
        else:
            shell = Shell(history_enabled=not args.no_history)
            return shell.run(args.script) if args.script is not None else shell.run()
        return 0
    except (ValueError, OSError, SyntaxError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
