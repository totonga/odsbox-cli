import pandas as pd
import pytest
from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document

from odsbox_cli.completion import CompletionBuffer, InspectorCompleter, SpanCompletion


def candidates(model, source, namespace=None, cursor=None):
    completer = InspectorCompleter(lambda: model, lambda: ["Test server"], namespace or {})
    return list(completer.get_completions(Document(source, cursor), CompleteEvent()))


@pytest.mark.parametrize(
    "source,expected",
    [
        ("use Tes", "Test server"),
        ('use "Tes', "Test server"),
        ("help quer", "queries"),
        ("help reco", "reconnect"),
        ("db.rec", "db.reconnect()"),
        ("db.script", "db.script_starter("),
        ("help script", "script_starter"),
        ("gui.pl", "gui.plot("),
        ("gui.ta", "gui.table("),
        ("connections imp", "import"),
        ("db.find({AoMea", "AoMeasurement"),
        ("db.find({Measurement: {Na", "Name"),
        ("db.find({Measurement: {test.Na", "test.Name"),
        ("db.find({Measurement: {}, $att", "$attributes"),
        ("db.find({Measurement: {}, $attributes: {Na", "Name"),
        ("db.find({Measurement: {}, $attributes: {test: {Na", "Name"),
        ("db.find({Measurement: {}, $orderby: {Na", "Name"),
        ("db.find({Measurement: {}, $groupby: {Na", "Name"),
        ("db.find({Measurement: {}, $options: {$row", "$rowlimit"),
        ("db.find({Measurement: {Id: {$g", "$gte"),
        ("db.find({Measurement: {Status: 'Re", "Ready"),
        ("db.find({Measurement: {Status: {$eq: 'Re", "Ready"),
        ("db.find({Measurement: {Status: {$in: ['Re", "Ready"),
        ('db.model.find("AoMea', "AoMeasurement"),
        ("db.model.relations(AoMea", "'AoMeasurement'"),
        ("db.find({Measurement: {\n# comment\nNa", "Name"),
        ("db.find({Measurement: {test: {parent: {Na", "Name"),
    ],
)
def test_contexts(model, source, expected):
    found = candidates(model, source)
    assert expected in [c.text for c in found], [(c.text, c.display_meta_text) for c in found]


def test_local_completion(model):
    namespace = {"runs": pd.DataFrame({"name": ["x"], "id": [1]})}
    for source in ('runs["na', 'runs[["na', 'runs[["id", "na', 'runs.sort_values("na'):
        assert "name" in [c.text for c in candidates(model, source, namespace)]
    assert "runs" in [c.text for c in candidates(None, "ru", namespace)]
    assert "db.find(" in [c.text for c in candidates(None, "")]
    assert candidates(None, "db.find({Ao") == []
    assert candidates(model, 'other["na') == []
    assert candidates(model, "db.find({Measurement: {unknown.Na") == []
    assert candidates(model, "db.find({Measurement: {Name: 'anything") == []
    assert "runs" in [c.text for c in candidates(None, "gui.plot(ru", namespace)]
    assert "runs" in [c.text for c in candidates(None, "gui.table(ru", namespace)]


def test_ambiguous(model):
    model.entities["Other"].CopyFrom(model.entities["Measurement"])
    model.entities["Other"].name = "Other"
    found = candidates(model, "db.find({AoMea")
    assert any("ambiguous" in c.display_meta_text for c in found)
    assert candidates(model, "db.find({AoMeasurement: {Na") == []
    assert candidates(model, "db.find({Measurement: {Na")


def test_completion_span(model):
    source = "db.find({Measurement: {Naxe: 1}})"
    cursor = source.index("Naxe") + 2
    result = next(c for c in candidates(model, source, cursor=cursor) if c.text == "Name")
    buffer = CompletionBuffer()
    buffer.document = Document(source, cursor)
    buffer._set_completions([result])
    buffer.go_to_completion(0)
    assert buffer.text == "db.find({Measurement: {Name: 1}})"
    buffer.cancel_completion()
    assert buffer.text == source
    buffer.apply_completion(result)
    assert buffer.text == "db.find({Measurement: {Name: 1}})"
    buffer.apply_completion(Completion("X", start_position=0))
    assert "NameX" in buffer.text
    buffer.go_to_completion(None)


def test_generic_completion_buffer():
    buffer = CompletionBuffer()
    buffer.document = Document("ab")
    buffer._set_completions([Completion("abc", -2)])
    buffer.go_to_completion(0)
    assert buffer.text == "abc"
    buffer.cancel_completion()
    assert buffer.text == "ab"
    buffer._set_completions([SpanCompletion("again", 0, 2, 2)])
    assert buffer.complete_state is not None
    buffer.apply_completion(buffer.complete_state.completions[0])
    assert buffer.text == "again"


def test_special_keys(model):
    attribute = model.entities["Measurement"].attributes["space key"]
    attribute.name = "space key"
    found = candidates(model, "db.find({Measurement: {spa")
    assert "'space key'" in [c.text for c in found]
    quoted = candidates(model, 'db.find({Measurement: {"Na')
    assert "Name" in [c.text for c in quoted]
    spaced = candidates(model, 'db.find({Measurement: {"space k')
    assert "space key" in [c.text for c in spaced]
    model.entities["Special Entity"].name = "Special Entity"
    assert "Special Entity" in [c.text for c in candidates(model, 'db.model.find("Special E')]


def test_no_descriptor_evaluation(model):
    class DangerousFrame(pd.DataFrame):
        @property
        def columns(self) -> pd.Index:
            raise AssertionError("descriptor evaluated")

        @columns.setter
        def columns(self, value: object) -> None:
            raise AssertionError("descriptor assigned")

    frame = DangerousFrame()
    assert candidates(model, 'danger["x', {"danger": frame}) == []


def test_completion_error():
    def broken():
        raise ValueError("metadata failed")

    provider = InspectorCompleter(broken, lambda: [], {})
    with pytest.warns(UserWarning, match="Autocomplete failed"):
        assert list(provider.get_completions(Document("db.find({"), CompleteEvent())) == []


def test_offline_syntax_completion():
    assert "$attributes" in [c.text for c in candidates(None, "db.find({$att")]
    assert "$rowlimit" in [c.text for c in candidates(None, "db.find({$options: {$row")]


def test_options_before_entity(model):
    assert "$rowlimit" in [c.text for c in candidates(model, "db.find({$options: {$row")]
    assert candidates(model, "db.find({$attributes: {arbitrary") == []


def test_explicit_name_wins_alias(model):
    model.entities["Base"].name = "AoMeasurement"
    model.entities["Base"].base_name = "Different"
    found = [c for c in candidates(model, "db.find({AoMea") if c.text == "AoMeasurement"]
    assert len(found) == 1
    assert found[0].display_meta_text.startswith("entity (")
