import io
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from odsbox_cli.cli import Shell, Terminal, connection_command, main, parser, shell_words
from odsbox_cli.help import TOPICS, help_text


@pytest.fixture
def shell(session):
    output: list[str] = []
    return Shell(session, output.append)


def test_query_results(shell, connection, tmp_path):
    assert shell.execute("runs = db.find({AoMeasurement: {}, $attributes: {id: 1, name: 1}})")
    assert shell.namespace["_"] is shell.namespace["runs"]
    assert shell.execute("runs.head(3)")
    assert len(shell.namespace["_"]) == 3
    assert shell.execute("runs")
    assert len(shell.namespace["_"]) == 30
    assert any("truncated" in line for line in shell.output.__self__)
    assert shell.execute("runs.query('id > 20').sort_values('id')")
    assert len(shell.namespace["_"]) == 9
    csv = tmp_path / "runs.csv"
    js = tmp_path / "runs.json"
    shell.execute(f"runs.to_csv({str(csv)!r}, index=False)")
    shell.execute(f"runs.to_json({str(js)!r}, orient='records')")
    assert len(pd.read_csv(csv)) == 30
    assert len(json.loads(js.read_text())) == 30
    previous = shell.namespace["_"]
    shell.execute("1 + 1")
    assert shell.namespace["_"] is previous
    connection.query.side_effect = ValueError("query failed")
    with pytest.raises(ValueError):
        shell.execute("db.find({AoMeasurement: {}})")
    assert shell.namespace["_"] is previous


def test_reconnect_preserves_local_state_and_routes_reads(shell, connection, model):
    shell.execute("runs = db.find({AoMeasurement: {}})")
    shell.execute("selected_id = 42")
    previous = shell.namespace["_"]
    facade, model_facade = shell.db, shell.db.model
    find, bulk, inspect_model = facade.find, facade.bulk, model_facade.find
    replacement = MagicMock()
    replacement.model.return_value = model
    replacement.query.return_value = pd.DataFrame({"new": [1]})
    replacement.bulk.data_read.return_value = pd.DataFrame({"signal": [2]})
    replacement.bulk.data_read.return_value.attrs["partial_result"] = False
    shell.session.factory = MagicMock(return_value=replacement)
    connection.query.side_effect = ValueError("session expired")
    with pytest.raises(ValueError, match="session expired"):
        shell.execute("db.find({AoMeasurement: {}})")
    shell.session.factory.assert_not_called()
    assert connection.query.call_count == 2
    assert shell.namespace["_"] is previous
    output = list(shell.output.__self__)
    assert shell.execute("db.reconnect()")
    assert shell.output.__self__ == output
    assert shell.namespace["_"] is previous and shell.namespace["runs"] is previous
    assert shell.namespace["selected_id"] == 42
    assert shell.db is facade and shell.db.model is model_facade
    assert find({}) is replacement.query.return_value
    assert bulk(1) is replacement.bulk.data_read.return_value
    inspect_model()
    assert connection.query.call_count == 2
    shell.session.factory.assert_called_once()
    connection.bulk.data_read.assert_not_called()
    shell.session.factory.side_effect = ValueError("login failed")
    before_failure = shell.namespace["_"]
    with pytest.raises(ValueError, match="login failed"):
        shell.execute("db.reconnect()")
    assert shell.namespace["_"] is before_failure
    assert shell.session.connection is replacement


def test_dynamic_once(shell, connection):
    shell.execute("calls = []")
    shell.execute("selected_id = 42")
    shell.execute("db.find({AoMeasurement: {id: selected_id, x: (calls.append(1) or 8 // 2)}})")
    assert shell.namespace["calls"] == [1]
    assert connection.query.call_args.args[0]["AoMeasurement"] == {"id": 42, "x": 4}
    with pytest.raises(NameError):
        shell.execute("db.find({AoMeasurement: {id: missing_variable}})")
    assert shell.execute("db.find({AoMeasurement: {") is False
    assert shell.execute("x = 1")
    assert shell.execute("")
    shell.execute("db.model.find()")
    assert "base_name" in shell.namespace["_"].columns


def test_commands(shell):
    for topic in ["", *TOPICS]:
        shell.execute("help " + topic)
    with pytest.raises(ValueError):
        shell.execute("help unknown")
    assert "help <topic>" in help_text()
    shell.execute('use "Demo"')
    shell.execute("disconnect")
    shell.execute("connections list")
    shell.execute("connections --help")
    with pytest.raises(ValueError):
        shell.execute("connections invalid")
    with pytest.raises(EOFError):
        shell.execute("exit")
    assert shell.server_names() == ["Demo"]
    shell.session.registry.path.write_text("invalid")
    assert shell.server_names() == []


def test_gui_namespace_and_last_frame(shell, tmp_path):
    import matplotlib

    matplotlib.use("Agg", force=True)
    shell.execute("samples = pd.DataFrame({'value': range(10)})")
    shell.execute("samples")
    previous = shell.namespace["_"]
    assert shell.namespace["gui"] is shell.gui
    assert "plot" not in shell.namespace and "table" not in shell.namespace
    shell.execute(f"gui.plot(save={str(tmp_path / 'plot.png')!r})")
    shell.execute(f"gui.table(samples, save={str(tmp_path / 'table.png')!r})")
    assert shell.namespace["_"] is previous
    assert (tmp_path / "plot.png").is_file() and (tmp_path / "table.png").is_file()


def test_script_starter_shell_preserves_results(shell, tmp_path):
    shell.execute("runs = db.find({AoMeasurement: {}, $options: {$rowlimit: 3}})")
    previous = shell.namespace["_"]
    shell.execute(f"folder = db.script_starter({str(tmp_path)!r}, open_folder=False)")
    assert shell.namespace["_"] is previous and shell.namespace["runs"] is previous
    assert (shell.namespace["folder"] / "script.py").is_file()


@pytest.mark.parametrize("failure", [False, True, "cleanup"])
def test_gui_events_during_prompt_and_search(shell, failure):
    import asyncio
    from unittest.mock import patch

    shell.gui = MagicMock()
    shell.gui.has_windows = True
    if failure:
        shell.gui.pump.side_effect = RuntimeError("backend stopped")
    if failure == "cleanup":
        shell.gui.close.side_effect = RuntimeError("close failed")
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        terminal = Terminal(shell)

        async def interact():
            pipe.send_text("\x12")
            await asyncio.sleep(0.2)
            assert terminal.application.is_running
            assert shell.gui.pump.call_count >= 1
            pipe.send_text("\x03")
            await asyncio.sleep(0.05)
            pipe.send_text("help\n")

        async def run():
            interaction = asyncio.create_task(interact())
            result = await asyncio.wait_for(terminal.application.run_async(), timeout=5)
            await interaction
            assert not terminal.application._background_tasks
            return result

        assert asyncio.run(run()) == "help"
        if failure:
            assert shell.gui.pump.call_count == 1
            shell.gui.close.assert_called_once()
            assert sum("GUI event processing failed" in line for line in shell.output.__self__) == 1
        else:
            previous = shell.gui.pump.call_count
            pipe.send_text("help\n")
            assert terminal.read() == "help"
            assert shell.gui.pump.call_count >= previous
    with patch.object(shell.gui, "close") as close, patch("sys.stdin", io.StringIO("exit\n")):
        assert shell.run() == 0
        close.assert_called_once()


def test_interactive_loop(shell, monkeypatch):
    stream = MagicMock()
    stream.isatty.return_value = True
    monkeypatch.setattr("sys.stdin", stream)
    terminal = MagicMock()
    terminal.read.side_effect = [KeyboardInterrupt(), "1 + * 2", EOFError()]
    monkeypatch.setattr("odsbox_cli.cli.Terminal", lambda s: terminal)
    shell.run()
    assert shell.session.connection is None
    assert any("Cancelled" in line for line in shell.output.__self__)


def test_display(shell, monkeypatch):
    monkeypatch.setattr("shutil.get_terminal_size", lambda default: __import__("os").terminal_size((60, 24)))
    shell.display(pd.DataFrame({"long": ["x" * 60], **{str(i): [i] for i in range(10)}}))
    assert any("Long cells" in text for text in shell.output.__self__)
    assert shell.namespace["_"].iloc[0, 0] == "x" * 60
    shell.display(pd.DataFrame())
    shell.display(None)


def test_process_commands(registry, tmp_path, capsys, monkeypatch):
    path = tmp_path / "portable.json"
    path.write_text('{"name":"new","url":"file.atfx","auth_type":"atfx"}')
    output: list[str] = []
    connection_command(parser().parse_args(["connections", "import", str(path)]), registry, output.append)
    connection_command(parser().parse_args(["connections", "import", str(path)]), registry, output.append)
    with pytest.raises(ValueError, match="not found"):
        connection_command(parser().parse_args(["connections", "import-pilot"]), registry, output.append)
    registry.pilot_path.write_text("[]")
    connection_command(parser().parse_args(["connections", "import-pilot"]), registry, output.append)
    assert output[0] == "Imported 1 connection(s)"
    monkeypatch.setattr("odsbox_cli.cli.Registry", lambda: registry)
    assert main(["connections", "list"]) == 0
    assert main(["wrong"]) == 1
    fake = MagicMock()
    fake.run.return_value = 0
    monkeypatch.setattr("odsbox_cli.cli.Shell", lambda **kwargs: fake)
    assert main([]) == 0
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_shell_words():
    assert shell_words(r'connections import "C:\some path\file.json" --name "Test server"') == [
        "connections",
        "import",
        r"C:\some path\file.json",
        "--name",
        "Test server",
    ]
    with pytest.raises(ValueError):
        shell_words('"unfinished')


def test_scripted_run(shell, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("help\n1 + * 2\nx = (\n1)\nexit\n"))
    assert shell.run() == 1
    assert shell.namespace["x"] == 1
    assert shell.session.connection is None


def test_preview_exact_bound(shell):
    rows = pd.DataFrame({"value": [f"row-{i:03d}" for i in range(50)]})
    shell.display(rows)
    rendered = "\n".join(shell.output.__self__)
    assert rendered.count("row-") == 20
    assert "[50 rows x 1 columns]" in rendered
    assert len(shell.namespace["_"]) == 50


def test_incomplete_eof(shell, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("x = (\n"))
    with pytest.raises(SyntaxError, match="Incomplete"):
        shell.run()


def test_terminal_pipe(shell):
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        terminal = Terminal(shell)
        pipe.send_text("help\n")
        assert terminal.read() == "help"
        pipe.send_text("\x1b[200~x = (\n1)\x1b[201~\n")
        assert terminal.read() == "x = (\n1)"
        pipe.send_text("abc\x1b[D\x04\n")
        assert terminal.read() == "ab"
        pipe.send_text("\x03")
        with pytest.raises(KeyboardInterrupt):
            terminal.read()
        pipe.send_text("\x04")
        with pytest.raises(EOFError):
            terminal.read()


@pytest.mark.parametrize(
    "keys,expected,cursor",
    [
        ("(", "()", 1),
        ("[", "[]", 1),
        ("{", "{}", 1),
        ('"', '""', 1),
        ("'", "''", 1),
        ("({[", "({[]})", 3),
        ("()", "())", 2),
        ("(\x1b[C", "()", 2),
        ("(\x7f", ")", 0),
        ('""', '"""', 2),
        ('use "', 'use ""', 5),
        ("# note (", "# note (", 8),
        ('\x1b[200~x = "value\x1b[201~(', 'x = "value(', 11),
        ("\x1b[200~db.find({name: 'x'})\x1b[201~", "db.find({name: 'x'})", 20),
        ("abc\x1b[D(", "ab(c", 3),
        ("\x12('", "", 0),
    ],
)
def test_terminal_typed_pairing(shell, keys, expected, cursor):
    import asyncio

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        terminal = Terminal(shell)

        async def interact():
            pipe.send_text(keys)
            await asyncio.sleep(0.1)
            if keys.startswith("\x12"):
                assert terminal.search_toolbar.control.buffer.text == "('"
                pipe.send_text("\x03")
                await asyncio.sleep(0.05)
            assert terminal.buffer.text == expected
            assert terminal.buffer.cursor_position == cursor
            pipe.send_text("\x03")

        async def run():
            interaction = asyncio.create_task(interact())
            try:
                await asyncio.wait_for(terminal.application.run_async(), timeout=3)
            except KeyboardInterrupt:
                pass
            finally:
                if not interaction.done():
                    interaction.cancel()
                await interaction

        asyncio.run(run())
        assert terminal.history.get_strings() == []


def test_terminal_pair_submission_and_completion(shell):
    import asyncio

    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        terminal = Terminal(shell)
        pipe.send_text("x = [1\x1b[C\n")
        assert terminal.read() == "x = [1]"
        assert terminal.history.get_strings() == ["x = [1]"]
        terminal.buffer.reset()

        async def interact():
            pipe.send_text("db.fi\t")
            await asyncio.sleep(0.1)
            pipe.send_text("\n")
            await asyncio.sleep(0.1)
            assert terminal.buffer.text == "db.find("
            assert terminal.application.is_running
            pipe.send_text("\x03")

        async def run():
            interaction = asyncio.create_task(interact())
            try:
                await asyncio.wait_for(terminal.application.run_async(), timeout=3)
            except KeyboardInterrupt:
                pass
            finally:
                if not interaction.done():
                    interaction.cancel()
                await interaction

        asyncio.run(run())
        assert terminal.history.get_strings() == ["x = [1]"]


@pytest.mark.parametrize("text,expected", [("help quer", "help queries"), ("use De", "use Demo")])
def test_terminal_completion(shell, text, expected):
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        terminal = Terminal(shell)

        # Queue Tab; completion generation is asynchronous, allow it to finish before Enter.
        async def interact():
            import asyncio

            pipe.send_text(text + "\t")
            await asyncio.sleep(0.1)
            pipe.send_text("\n")
            await asyncio.sleep(0.05)
            assert terminal.application.is_running
            pipe.send_text("\n")

        import asyncio

        async def run():
            task = asyncio.create_task(interact())
            result = await terminal.application.run_async()
            await task
            return result

        assert asyncio.run(run()) == expected


@pytest.mark.parametrize(
    "keys,expected",
    [
        (["\x12", "needle", "\n"], "older NEEDLE"),
        (["\x12", "needle", "\x12", "\n"], "oldest needle"),
        (["draft", "\x12", "needle", "\x1b"], "draft"),
        (["draft", "\x12", "needle", "\x03"], "draft"),
        (["draft", "\x12", "missing", "\n"], "draft"),
        (["\x1b[A"], "latest"),
    ],
)
def test_terminal_history_search(shell, tmp_path, keys, expected):
    import asyncio

    from odsbox_cli.history import CommandHistory

    history = CommandHistory(tmp_path / "recall.sqlite3")
    for text in ["oldest needle", "older NEEDLE", "latest"]:
        history.append_string(text)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        terminal = Terminal(shell, history)

        async def interact():
            for key in keys:
                pipe.send_text(key)
                await asyncio.sleep(0.6 if key == "\x1b" else 0.08)
            assert terminal.application.is_running
            assert terminal.buffer.text == expected
            pipe.send_text("\n")

        async def run():
            terminal.history.refresh()
            interaction = asyncio.create_task(interact())
            try:
                result = await asyncio.wait_for(terminal.application.run_async(), timeout=5)
                await interaction
                return result
            finally:
                interaction.cancel()

        assert asyncio.run(run()) == expected
        assert history.get_strings()[-1] == expected
        assert "needle" not in history.get_strings()


def test_terminal_private_input_and_cross_session(shell, tmp_path):
    from odsbox_cli.history import CommandHistory

    path = tmp_path / "history.sqlite3"
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        first = Terminal(shell, CommandHistory(path))
        pipe.send_text(" visible = 1\n")
        assert first.read() == " visible = 1"
        assert first.history.get_strings() == []
        pipe.send_text("\x1b[200~value = (\n42)\x1b[201~\n")
        assert first.read() == "value = (\n42)"
        second = Terminal(shell, CommandHistory(path))
        pipe.send_text("\x1b[A\n")
        assert second.read() == "value = (\n42)"
    assert parser().parse_args(["--no-history"]).no_history
