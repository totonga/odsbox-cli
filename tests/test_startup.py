import io
import traceback
from unittest.mock import MagicMock

import pytest

from odsbox_cli.cli import Shell, main, parser


@pytest.fixture
def shell(session):
    output: list[str] = []
    return Shell(session, output.append)


@pytest.fixture
def script(tmp_path):
    def write(text):
        path = tmp_path / "startup commands.ods"
        path.write_text(text, encoding="utf-8")
        return path

    return write


class UnreadableStdin:
    def isatty(self):
        return False

    def __iter__(self):
        raise AssertionError("Startup must not consume stdin")


@pytest.mark.parametrize("option", ["--script", "-s"])
def test_option_and_main(option, script, monkeypatch, capsys):
    path = script("print('startup ran')\n")
    assert parser().parse_args([option, str(path)]).script == path
    monkeypatch.setattr("sys.stdin", UnreadableStdin())
    assert main(["--no-history", option, str(path)]) == 0
    assert "startup ran" in capsys.readouterr().out
    assert main([option, str(path), "connections", "list"]) == 1
    assert "cannot be combined" in capsys.readouterr().err


def test_commands_queries_and_namespace(shell, connection, script, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    path = script(
        "\ufeff# setup\nhelp queries\nuse Demo\n"
        "selected = 42\n"
        "runs = db.find({\nAoMeasurement: {id: selected},\n$options: {$rowlimit: 3}\n})\n"
        "runs\nruns.head(2)\n"
        "runs.to_csv('results.csv', index=False)\n"
        "match = 3\nmatch + 1"
    )
    assert shell.run_script(path) == 0
    assert shell.namespace["selected"] == 42
    assert len(shell.namespace["_"]) == 2
    assert len(shell.namespace["runs"]) == 30
    assert connection.query.call_count == 1
    assert connection.query.call_args.args[0]["AoMeasurement"] == {"id": 42}
    assert (tmp_path / "results.csv").is_file()
    assert not (tmp_path / "history.sqlite3").exists()
    assert shell.session.connection is connection


@pytest.mark.parametrize(
    "source",
    [
        "for i in [1, 2]:\n    values.append(i)\n    values.append(i + 10)\n",
        "if True:\n    values.append(1)\n    values.append(11)\nelse:\n    values.append(0)\n",
        "i = 1\nwhile i < 2:\n    values.extend([i, i + 10])\n    i += 1\n",
        "try:\n    raise ValueError()\nexcept ValueError:\n    values.append(1)\nfinally:\n    values.append(11)\n",
        "try:\n    raise ExceptionGroup('test', [ValueError()])\nexcept* ValueError:\n    values.extend([1, 11])\n",
        "match 1:\n    case 1:\n        values.append(1)\n        values.append(11)\n",
        "with __import__('contextlib').nullcontext():\n    values.append(1)\n    values.append(11)\n",
        "class Example:\n    values.append(1)\n    values.append(11)\n",
        "def collect():\n    for i in [1, 11]:\n        values.append(i)\n\ncollect()\n",
        "@(lambda f: f)\ndef collect():\n    values.append(1)\n    values.append(11)\n\ncollect()\n",
        "import asyncio\nasync def collect():\n    values.append(1)\n    values.append(11)\n\nasyncio.run(collect())\n",
    ],
)
@pytest.mark.parametrize("separator", ["", "\n"])
def test_compound_blocks(shell, script, source, separator):
    path = script("values = []\n" + source + separator)
    assert shell.run_script(path) == 0, shell.output.__self__
    assert shell.namespace["values"][:2] == [1, 11]


def test_indented_blank_lines_and_following_command(shell, script):
    path = script(
        "values = []\nfor i in [1, 2]:\n    values.append(i)\n    \n"
        "    values.append(i + 10)\n\nhelp script_starter\nfinished = True\n"
    )
    assert shell.run_script(path) == 0
    assert shell.namespace["values"] == [1, 11, 2, 12]
    assert shell.namespace["finished"] is True


@pytest.mark.parametrize(
    "source,line,exception",
    [
        ("ready = 1\n1 + * 2\n", 2, "SyntaxError"),
        ("ready = 1\nmissing_name\n", 2, "NameError"),
        ("ready = 1\nhelp nonexistent\n", 2, "ValueError"),
        ("ready = 1\nx = (\n", 2, "SyntaxError"),
        ("ready = 1\nif True:\n", 3, "IndentationError"),
        ("ready = 1\nif True:\n    x = missing\n\n", 3, "NameError"),
        ("ready = 1\nif True:\n    x =\n\n", 3, "SyntaxError"),
        ("ready = 1\nruns = db.find({\nAoMeasurement: {id: missing}\n})\n", 3, "NameError"),
    ],
)
def test_error_location_and_fail_fast(shell, script, source, line, exception):
    path = script(source + ("\n" if source.endswith("(\n") else "") + "later = True\n")
    assert shell.run_script(path) == 1
    assert shell.namespace["ready"] == 1
    assert "later" not in shell.namespace
    assert any(f"{path.resolve()}:{line}: {exception}" in text for text in shell.output.__self__)


@pytest.mark.parametrize("source", ["value = (", "if True:\n", "for value in [1]:\n"])
def test_incomplete_eof(shell, script, source):
    path = script("# comment\n" + source)
    assert shell.run_script(path) == 1
    assert any(f"{path.resolve()}:2: SyntaxError: Incomplete" in text for text in shell.output.__self__)


def test_saved_function_provenance(shell, script):
    path = script("# comment\n\ndef fail():\n    x = 1\n    return x / 0\n\n")
    assert shell.run_script(path) == 0
    with pytest.raises(ZeroDivisionError) as exc:
        shell.execute("fail()")
    frame = traceback.extract_tb(exc.value.__traceback__)[-1]
    assert (frame.filename, frame.lineno) == (str(path.resolve()), 5)
    path.write_text("fail()\nlater = True\n")
    assert shell.run_script(path) == 1
    assert any(f"{path.resolve()}:5: ZeroDivisionError" in text for text in shell.output.__self__)
    assert "later" not in shell.namespace


@pytest.mark.parametrize("contents", ["", "\ufeff", "# comment", "\n\n# comment\n"])
def test_empty_scripts(shell, script, contents):
    assert shell.run_script(script(contents)) == 0


@pytest.mark.parametrize("failure", ["runtime", "missing", "directory", "encoding", "interrupt", "connection"])
def test_nonterminal_failure_and_cleanup(shell, script, monkeypatch, failure):
    path = script("ready = 1\nraise RuntimeError('stop')\nlater = True\n")
    expected = 1
    if failure == "missing":
        path = path.with_name("missing.ods")
    elif failure == "directory":
        path = path.parent
    elif failure == "encoding":
        path.write_bytes(b"\xff")
    elif failure == "interrupt":
        path.write_text("raise KeyboardInterrupt()\nlater = True\n")
        expected = 130
    elif failure == "connection":
        shell.session.factory = MagicMock(side_effect=ValueError("login failed"))
        path.write_text("use Demo\nlater = True\n")
    disconnect = MagicMock(wraps=shell.session.disconnect)
    monkeypatch.setattr(shell.session, "disconnect", disconnect)
    close = MagicMock()
    monkeypatch.setattr(shell.gui, "close", close)
    monkeypatch.setattr("sys.stdin", UnreadableStdin())
    assert shell.run(path) == expected
    assert "later" not in shell.namespace
    assert shell.session.connection is None
    disconnect.assert_called_once()
    close.assert_called_once()


@pytest.mark.parametrize("failure", [False, True, "missing", "interrupt"])
def test_interactive_handoff(shell, connection, script, monkeypatch, failure):
    path = script("assert gui.interactive\nready = 1\nruns = db.find({AoMeasurement: {}})\n")
    if failure is True:
        path.write_text(path.read_text() + "raise ValueError('stop')\nlater = True\n")
    elif failure == "missing":
        path = path.with_name("missing.ods")
    elif failure == "interrupt":
        path.write_text(path.read_text() + "raise KeyboardInterrupt()\nlater = True\n")
    stdin = MagicMock()
    stdin.isatty.return_value = True
    monkeypatch.setattr("sys.stdin", stdin)
    terminal = MagicMock()
    terminal.history.append_string = MagicMock(side_effect=AssertionError("Must not record script"))
    reads: list[bool] = []

    def read():
        assert shell.session.connection is connection
        assert shell.gui.interactive
        if failure != "missing":
            assert shell.namespace["ready"] == 1
            assert shell.namespace["_"] is shell.namespace["runs"]
        assert "later" not in shell.namespace
        if not reads:
            reads.append(True)
            return "debugged = True"
        raise EOFError

    terminal.read.side_effect = read

    def create_terminal(instance):
        assert instance is shell
        assert "ready" not in shell.namespace
        instance.gui.interactive = True
        return terminal

    monkeypatch.setattr("odsbox_cli.cli.Terminal", create_terminal)
    assert shell.run(path) == (130 if failure == "interrupt" else int(bool(failure)))
    assert shell.namespace["debugged"] is True
    assert shell.session.connection is None
    terminal.history.append_string.assert_not_called()


def test_real_terminal_debugging_and_history(shell, script, monkeypatch, tmp_path):
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from odsbox_cli.history import CommandHistory

    path = script("ready = 42\n1 / 0\nlater = True\n")
    stdin = MagicMock()
    stdin.isatty.return_value = True
    monkeypatch.setattr("sys.stdin", stdin)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        pipe.send_text("\x1b[200~debugged = ready\x1b[201~\n\x04")
        assert shell.run(path) == 1
    assert shell.namespace["debugged"] == 42
    assert "later" not in shell.namespace
    history = CommandHistory(tmp_path / "history.sqlite3")
    assert list(history.load_history_strings()) == ["debugged = ready"]


@pytest.mark.parametrize("command", ["exit", "quit", "raise SystemExit(7)"])
def test_intentional_exit(shell, script, monkeypatch, command):
    path = script(f"ready = 1\n{command}\nlater = True\n")
    stdin = MagicMock()
    stdin.isatty.return_value = True
    monkeypatch.setattr("sys.stdin", stdin)
    terminal = MagicMock()
    monkeypatch.setattr("odsbox_cli.cli.Terminal", lambda instance: terminal)
    if command.startswith("raise"):
        with pytest.raises(SystemExit) as exc:
            shell.run(path)
        assert exc.value.code == 7
    else:
        assert shell.run(path) == 0
    terminal.read.assert_not_called()
    assert shell.namespace["ready"] == 1
    assert "later" not in shell.namespace
    assert shell.session.connection is None


def test_success_does_not_read_stdin_or_create_terminal(shell, script, monkeypatch):
    monkeypatch.setattr("sys.stdin", UnreadableStdin())
    monkeypatch.setattr("odsbox_cli.cli.Terminal", MagicMock(side_effect=AssertionError("No terminal")))
    assert shell.run(script("ready = 1")) == 0
    assert shell.namespace["ready"] == 1
    assert shell.session.connection is None


def test_legacy_pipe_keeps_continuing(shell, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("1 / 0\nlater = True\n"))
    assert shell.run() == 1
    assert shell.namespace["later"] is True
