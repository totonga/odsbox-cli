import inspect
from unittest.mock import Mock

import pandas as pd
import pytest
from odsbox.bulk_reader import BulkReader
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from odsbox_cli.completion import CompletionBuffer, InspectorCompleter
from odsbox_cli.database import Database


def test_bulk_signature_and_forwarding(session, connection):
    expected = inspect.signature(BulkReader.data_read)
    actual = inspect.signature(Database.bulk)
    assert list(actual.parameters.values()) == list(expected.parameters.values())
    frame = pd.DataFrame({"signal": pd.Series([1, 2], dtype="Int64")}, index=pd.Index([0, 1], name="time"))
    frame.attrs = {"unit_names": {"signal": "V"}, "partial_result": False}
    connection.bulk.data_read.return_value = frame
    remember = Mock()
    db = Database(session, remember)
    assert db.bulk(42) is frame
    connection.bulk.data_read.assert_called_once_with(
        42, None, False, True, True, 0, 0, raise_on_partial_result=False, valid_flag=None
    )
    remember.assert_called_once_with(frame)
    assert db.bulk(42, ["*sig?"], True, False, False, 2, 5, raise_on_partial_result=True, valid_flag=False) is frame
    connection.bulk.data_read.assert_called_with(
        42, ["*sig?"], True, False, False, 2, 5, raise_on_partial_result=True, valid_flag=False
    )
    with pytest.raises(TypeError):
        db.bulk(42, None, False, True, True, 0, 0, True)  # type: ignore[call-arg]  # Intentionally positional.


def test_bulk_partial_error_and_disconnect(session, connection):
    frame = pd.DataFrame({"x": [1]})
    frame.attrs["partial_result"] = True
    connection.bulk.data_read.return_value = frame
    remember = Mock()
    db = Database(session, remember)
    with pytest.warns(UserWarning, match="partial result"):
        assert db.bulk(1) is frame
    remember.reset_mock()
    connection.bulk.data_read.side_effect = ValueError("upstream failure")
    with pytest.raises(ValueError, match="upstream failure"):
        db.bulk(1)
    remember.assert_not_called()
    session.disconnect()
    with pytest.raises(ValueError, match="Not connected"):
        db.bulk(1)


def complete(source, cursor=None):
    def forbidden():
        pytest.fail("bulk completion fetched metadata")

    completer = InspectorCompleter(forbidden, forbidden, {})
    return list(completer.get_completions(Document(source, cursor_position=cursor), CompleteEvent()))


def test_bulk_completion():
    assert "submatrix_iid=" in {item.text for item in complete("db.bulk(")}
    assert "submatrix_iid=" not in {item.text for item in complete("db.bulk(1, ")}
    assert "values_limit=" not in {item.text for item in complete("db.bulk(1, values_limit=5, ")}
    assert {item.text for item in complete("result = db.bulk(1, val")} == {
        "values_start=",
        "values_limit=",
        "valid_flag=",
    }
    for source in ["db.bulk(1, ['", "db.bulk(1, foo(", "db.bulk(1, values_limit=", "db.bulk(1, 'val"]:
        assert complete(source) == []
    source = "db.bulk(1, values_limt=5)"
    cursor = source.index("limt") + 2
    candidates = complete(source, cursor)
    selected = next(item for item in candidates if item.text == "values_limit")
    buffer = CompletionBuffer()
    buffer.document = Document(source, cursor)
    buffer.apply_completion(selected)
    assert buffer.text == "db.bulk(1, values_limit=5)"
    source = "db.bulk(1, val, values_limit=5)"
    assert "values_limit=" not in {item.text for item in complete(source, source.index("val") + 3)}
