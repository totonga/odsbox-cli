"""Explicit, read-only smoke tests. Never run in ordinary CI."""

import json
import os
from unittest.mock import patch

import pandas as pd
import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from odsbox_cli.cli import Shell
from odsbox_cli.connections import Config, Registry, connect
from odsbox_cli.database import Session

pytestmark = pytest.mark.integration


@pytest.fixture
def live_shell(tmp_path):
    settings = [os.environ.get("ODSBOX_TEST_" + field) for field in ("URL", "USERNAME", "PASSWORD")]
    if not all(settings):
        pytest.fail("Set ODSBOX_TEST_URL, ODSBOX_TEST_USERNAME, and ODSBOX_TEST_PASSWORD for integration tests")
    url, username, password = settings
    assert url is not None and username is not None and password is not None
    registry = Registry(tmp_path / "cli.json", tmp_path / "absent-pilot.json")
    registry.import_configs([Config("Live demo", url, "basic", username=username)])
    session = Session(
        registry,
        lambda config: connect(config, password, connection_timeout=15, request_timeout=30),
    )
    try:
        session.use("Live demo")
    except Exception as exc:
        pytest.fail(f"Demo connection failed ({type(exc).__name__}); check endpoint/TLS/credentials", pytrace=False)
    shell = Shell(session, lambda text: None)
    try:
        yield shell
    finally:
        session.disconnect()


def test_live_inspection(live_shell, tmp_path):
    shell = live_shell
    shell.execute("entities = db.model.find()")
    assert not shell.namespace["entities"].empty
    model = shell.session.model
    entities = sorted(model.entities.values(), key=lambda e: (e.base_name != "AoMeasurement", e.name))
    entity = next((e for e in entities if any(a.base_name == "id" for a in e.attributes.values())), None)
    assert entity is not None, "Demo model must have a queryable entity with an ID attribute"
    attribute = next(a for a in entity.attributes.values() if a.base_name == "id")
    shell.execute(f"attributes = db.model.find({entity.name!r})")
    assert attribute.name in set(shell.namespace["attributes"]["name"])
    shell.execute(f"db.model.relations({entity.name!r})")
    shell.namespace["limit"] = 3
    shell.execute(
        f"rows = db.find({{{entity.name!r}: {{}}, $attributes: {{{attribute.name!r}: 1}}, "
        "$options: {$rowlimit: limit}})"
    )
    rows = shell.namespace["rows"]
    assert isinstance(rows, pd.DataFrame)
    assert list(rows.columns) == [attribute.name]
    assert len(rows) <= 3
    shell.execute("rows.head()")
    csv, js = tmp_path / "rows.csv", tmp_path / "rows.json"
    shell.execute(f"rows.to_csv({str(csv)!r}, index=False)")
    shell.execute(f"rows.to_json({str(js)!r}, orient='records')")
    assert len(pd.read_csv(csv)) == len(rows)
    assert len(json.loads(js.read_text())) == len(rows)
    # Keystrokes must only consult the already cached model.
    with patch.object(shell.session.connection, "query", side_effect=AssertionError("completion issued a query")):
        completions = list(shell.completer.get_completions(Document("db.find({"), CompleteEvent()))
    assert entity.name in {c.text for c in completions}
    old_connection, old_model, facade = shell.session.connection, shell.session.model, shell.db
    previous = shell.namespace["_"]
    shell.execute("db.reconnect()")
    assert shell.session.connection is not old_connection
    assert shell.session.model is not old_model
    assert shell.db is facade and shell.namespace["_"] is previous
    assert shell.namespace["rows"] is rows
    shell.execute(
        f"reconnected_rows = db.find({{{entity.name!r}: {{}}, "
        f"$attributes: {{{attribute.name!r}: 1}}, $options: {{$rowlimit: 3}}}})"
    )
    assert len(shell.namespace["reconnected_rows"]) <= 3
    shell.execute("db.model.find()")
    assert not shell.namespace["_"].empty


def test_live_bulk(live_shell):
    shell = live_shell
    assert shell.session.model is not None
    entities = [entity for entity in shell.session.model.entities.values() if entity.base_name == "AoSubmatrix"]
    assert entities, "Demo model must expose an AoSubmatrix entity"
    local_column = next(
        entity for entity in shell.session.model.entities.values() if entity.base_name == "AoLocalColumn"
    )
    name = next(attribute.name for attribute in local_column.attributes.values() if attribute.base_name == "name")
    independent = next(
        attribute.name for attribute in local_column.attributes.values() if attribute.base_name == "independent"
    )
    submatrix = next(relation.name for relation in local_column.relations.values() if relation.base_name == "submatrix")
    db = shell.namespace["db"]
    for entity in entities:
        identity = next(attribute.name for attribute in entity.attributes.values() if attribute.base_name == "id")
        count = next(
            (attribute.name for attribute in entity.attributes.values() if attribute.base_name == "number_of_rows"),
            None,
        )
        rows = db.find(
            {
                entity.name: {count: {"$gt": 0}} if count else {},
                "$attributes": {identity: 1},
                "$options": {"$rowlimit": 5},
            }
        )
        for iid in rows[identity]:
            columns = db.find(
                {
                    local_column.name: {submatrix: int(iid), independent: 1},
                    "$attributes": {name: 1},
                    "$options": {"$rowlimit": 1},
                }
            )
            if columns.empty:
                continue
            pattern = str(columns.iloc[0][name])
            shell.execute(
                f"samples = db.bulk({int(iid)}, column_patterns=[{pattern!r}], "
                "set_independent_as_index=False, values_limit=3, raise_on_partial_result=True)"
            )
            samples = shell.namespace["samples"]
            if not samples.empty:
                assert 0 < len(samples) <= 3
                assert shell.namespace["_"] is samples
                assert "unit_names" in samples.attrs
                assert pattern in samples.columns
                assert not samples.attrs.get("partial_result", False)
                return
    pytest.fail("No readable nonempty submatrix found within the bounded demo discovery query")
