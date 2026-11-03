import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from odsbox_cli.history import LIMIT, CommandHistory


def test_persistence_privacy_order_and_refresh(tmp_path):
    path = tmp_path / "nested" / "history.sqlite3"
    first, second = CommandHistory(path), CommandHistory(path)
    first.append_string("help")
    second.refresh()
    assert second.get_strings() == ["help"]
    for private in ["", "  ", " secret()", " \nsecret()"]:
        second.append_string(private)
    second.append_string("help")
    second.append_string("x = (\n1)")
    first.refresh()
    assert first.get_strings() == ["help", "x = (\n1)"]
    assert list(first.load_history_strings()) == ["x = (\n1)", "help"]


def test_retention_and_concurrent_writers(tmp_path):
    path = tmp_path / "history.sqlite3"
    history = CommandHistory(path)
    history.refresh()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executemany("INSERT INTO history(text) VALUES (?)", [(str(i),) for i in range(LIMIT + 10)])
    history.append_string("last")
    history.refresh()
    assert len(history.get_strings()) == LIMIT
    assert history.get_strings()[0] == "11"
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda value: CommandHistory(path).append_string(value), ["writer one", "writer two"]))
    history.refresh()
    assert set(history.get_strings()[-2:]) == {"writer one", "writer two"}
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM history").fetchone()[0] == LIMIT


def test_disabled_never_touches_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(CommandHistory, "_connect", lambda self: pytest.fail("disk access"))
    history = CommandHistory(tmp_path / "absent", enabled=False)
    history.refresh()
    for number in range(LIMIT + 1):
        history.append_string(str(number))
    assert len(history.get_strings()) == LIMIT
    assert not (tmp_path / "absent").exists()


def test_corrupt_storage_on_load_does_not_destroy_file(tmp_path):
    path = tmp_path / "history.sqlite3"
    path.write_text("invalid sqlite")
    history = CommandHistory(path)
    with pytest.warns(UserWarning, match="using memory only"):
        history.refresh()
    history.append_string("help")
    history.refresh()
    assert history.get_strings() == ["help"]
    assert path.read_text() == "invalid sqlite"


@pytest.mark.parametrize("failure", ["corrupt", "locked", "unwritable"])
def test_storage_failure_warns_once_and_preserves_memory(tmp_path, failure):
    path = tmp_path / "history.sqlite3"
    history = CommandHistory(path)
    if failure == "corrupt":
        path.write_text("not a database")
    elif failure == "unwritable":
        path.mkdir()
    else:
        history.refresh()
    lock = sqlite3.connect(path) if failure == "locked" else None
    try:
        if lock:
            lock.execute("BEGIN EXCLUSIVE")
        with pytest.warns(UserWarning, match="using memory only") as warnings:
            history.append_string("help")
            history.append_string("help model")
            history.refresh()
        assert len(warnings) == 1
        assert history.get_strings() == ["help", "help model"]
    finally:
        if lock:
            lock.close()
