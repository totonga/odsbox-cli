from unittest.mock import MagicMock

import pandas as pd
import pytest
from odsbox.proto import ods_pb2 as ods

from odsbox_cli.connections import Config, Registry
from odsbox_cli.database import Session


@pytest.fixture(autouse=True)
def isolate_history(tmp_path, monkeypatch):
    from odsbox_cli.history import CommandHistory

    monkeypatch.setattr(
        "odsbox_cli.cli.CommandHistory",
        lambda *, enabled: CommandHistory(tmp_path / "history.sqlite3", enabled=enabled),
    )


@pytest.fixture
def model():
    model = ods.Model()
    entity = model.entities["Measurement"]
    entity.name, entity.base_name, entity.aid = "Measurement", "AoMeasurement", 1
    for i, (name, base, dtype) in enumerate(
        [("Id", "id", ods.DT_LONGLONG), ("Name", "name", ods.DT_STRING), ("Status", "status", ods.DT_ENUM)]
    ):
        attribute = entity.attributes[name]
        attribute.name, attribute.base_name, attribute.id, attribute.data_type = name, base, i + 1, dtype
    entity.attributes["Status"].enumeration = "States"
    model.enumerations["States"].name = "States"
    model.enumerations["States"].items.update({"Ready": 1, "Running": 2})
    test = model.entities["Test"]
    test.name, test.base_name, test.aid = "Test", "AoTest", 2
    test.attributes["Name"].name, test.attributes["Name"].base_name = "Name", "name"
    test.attributes["Name"].data_type = ods.DT_STRING
    relation = entity.relations["test"]
    relation.name, relation.base_name, relation.entity_name, relation.entity_aid = "test", "test", "Test", 2
    relation.range_min, relation.range_max = 0, 1
    loop = test.relations["parent"]
    loop.name, loop.entity_name = "parent", "Test"
    return model


@pytest.fixture
def registry(tmp_path):
    registry = Registry(tmp_path / "cli.json", tmp_path / "pilot.json")
    registry.import_configs([Config("Demo", "https://example.invalid/api", "basic", username="Demo")])
    return registry


@pytest.fixture
def connection(model):
    connection = MagicMock()
    connection.model.return_value = model
    connection.query.return_value = pd.DataFrame({"id": range(30), "name": [f"run {i}" for i in range(30)]})
    return connection


@pytest.fixture
def session(registry, connection):
    session = Session(registry, lambda config: connection)
    session.use("Demo")
    return session
