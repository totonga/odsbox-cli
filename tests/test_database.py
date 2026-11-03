from dataclasses import replace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from odsbox_cli.database import Database, Session


def test_data_and_model(session, connection):
    remembered: list[pd.DataFrame] = []
    db = Database(session, remembered.append)
    result = db.find({"AoMeasurement": {}})
    assert remembered[-1] is result
    connection.query.assert_called_once_with({"AoMeasurement": {}})
    overview = db.model.find()
    assert list(overview.columns) == ["aid", "name", "base_name"]
    attrs = db.model.find("AoMeasurement")
    assert set(attrs["name"]) == {"Id", "Name", "Status"}
    assert attrs.loc[attrs["name"] == "Status", "enumeration"].iloc[0] == "States"
    relations = db.model.relations("Measurement")
    assert relations.iloc[0]["target"] == "Test"
    assert db.model.relations("Test").iloc[0]["name"] == "parent"
    with pytest.raises(ValueError):
        db.model.find("missing")
    session.disconnect()
    with pytest.raises(ValueError, match="Not connected"):
        db.find({})


def test_switch(session, connection, model):
    old_db = Database(session, lambda r: None)
    old_method = old_db.model.find
    replacement = MagicMock()
    replacement.model.return_value = model
    session.factory = lambda c: replacement
    session.use("Demo")
    connection.logout.assert_called_once()
    assert old_method().shape[0] == 2
    assert session.connection is replacement
    broken = MagicMock()
    broken.model.side_effect = RuntimeError("model failed")
    session.factory = lambda c: broken
    with pytest.raises(RuntimeError):
        session.use("Demo")
    assert session.connection is replacement
    broken.logout.assert_called_once()
    replacement.logout.side_effect = RuntimeError("logout failed")
    with pytest.warns(UserWarning, match="logout failed"):
        session.disconnect()
    assert session.model is None and session.name is None
    session.disconnect()


def test_empty_models(model, session, connection):
    model.entities.clear()
    db = Database(session, lambda r: None)
    assert list(db.model.find().columns) == ["aid", "name", "base_name"]


def test_failed_factory(registry):
    session = Session(registry, MagicMock(side_effect=RuntimeError("connect failed")))
    with pytest.raises(RuntimeError):
        session.use("Demo")
    assert session.connection is None


def test_reconnect_refreshes_and_validates_before_logout(session, connection, model):
    db = Database(session, lambda result: None)
    model_method = db.model.find
    refreshed = type(model)()
    refreshed.CopyFrom(model)
    refreshed.entities["Test"].name = "Refreshed"
    replacement = MagicMock()

    def load_model():
        connection.logout.assert_not_called()
        assert session.connection is connection
        return refreshed

    replacement.model.side_effect = load_model
    factory = MagicMock(return_value=replacement)
    session.factory = factory
    config = replace(session.registry.get("Demo"), url="https://changed.invalid/api")
    with patch.object(session.registry, "get", return_value=config) as lookup:
        db.reconnect()
    lookup.assert_called_once_with("Demo")
    factory.assert_called_once_with(config)
    connection.logout.assert_called_once()
    assert session.connection is replacement
    assert session.model is refreshed and session.name == "Demo"
    replacement.model.side_effect = None
    replacement.model.return_value = refreshed
    assert "Refreshed" in set(model_method()["name"])


@pytest.mark.parametrize("failure", ["registry", "authentication", "model"])
def test_reconnect_failure_preserves_session(session, connection, model, failure):
    replacement = MagicMock()
    factory = MagicMock(return_value=replacement)
    session.factory = factory
    if failure == "registry":
        session.registry.get = MagicMock(side_effect=ValueError("registry failed"))
    elif failure == "authentication":
        factory.side_effect = ValueError("authentication failed")
    else:
        replacement.model.side_effect = ValueError("model failed")
    with pytest.raises(ValueError, match=f"{failure} failed"):
        Database(session, lambda result: pytest.fail("remember called")).reconnect()
    assert session.connection is connection and session.model is model and session.name == "Demo"
    connection.logout.assert_not_called()
    if failure == "model":
        replacement.logout.assert_called_once()
    else:
        replacement.logout.assert_not_called()
    connection.query.assert_not_called()
    connection.bulk.data_read.assert_not_called()


def test_reconnect_stale_logout_warns(session, connection, model):
    replacement = MagicMock()
    replacement.model.return_value = model
    session.factory = lambda config: replacement
    connection.logout.side_effect = RuntimeError("expired")
    with pytest.warns(UserWarning, match="Session logout failed"):
        session.reconnect()
    assert session.connection is replacement and session.name == "Demo"


def test_reconnect_requires_selection(registry):
    factory = MagicMock()
    session = Session(registry, factory)
    db = Database(session, lambda result: None)
    with pytest.raises(ValueError, match="use <server name>"):
        db.reconnect()
    factory.assert_not_called()
    session.use("Demo")
    session.disconnect()
    factory.reset_mock()
    with pytest.raises(ValueError, match="use <server name>"):
        db.reconnect()
    factory.assert_not_called()
