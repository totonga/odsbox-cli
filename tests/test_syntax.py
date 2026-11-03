import pytest

from odsbox_cli.syntax import compile_input, normalize, scan, tokens


@pytest.mark.parametrize(
    "source,query",
    [
        ("{AoMeasurement: {}}", {"AoMeasurement": {}}),
        (
            "{AoMeasurement: {id: 8 // 2,\n name: 'a'}, $options: {$rowlimit: 5}}",
            {"AoMeasurement": {"id": 4, "name": "a"}, "$options": {"$rowlimit": 5}},
        ),
        ("{AoMeasurement: {flag: true, x: false, y: null}}", {"AoMeasurement": {"flag": True, "x": False, "y": None}}),
        (
            "{AoMeasurement: {id: selected_id}, $attributes: {test.name: 1}}",
            {"AoMeasurement": {"id": 42}, "$attributes": {"test.name": 1}},
        ),
        (
            "{AoMeasurement: {$and: [{id: {$gte: 1}}, {name: 'x'}]}}",
            {"AoMeasurement": {"$and": [{"id": {"$gte": 1}}, {"name": "x"}]}},
        ),
        (
            "{'AoMeasurement': {'quoted key': 'escaped\\' value',},}",
            {"AoMeasurement": {"quoted key": "escaped' value"}},
        ),
        ("{AoMeasurement: {x: (lambda x: x + 1)(2), y: [1,2,3][1:]}}", {"AoMeasurement": {"x": 3, "y": [2, 3]}}),
    ],
)
def test_normalization(source, query):
    class DB:
        def find(self, value):
            return value

    namespace = {"db": DB(), "selected_id": 42}
    exec(compile(normalize("result = db.find(" + source + ")"), "<test>", "exec"), namespace)
    assert namespace["result"] == query


def test_no_rewrite_other_python():
    assert normalize('x = {"x": true}') == 'x = {"x": true}'
    assert normalize("db.find(query)") == "db.find(query)"
    assert normalize('print("db.find({key: true})")') == 'print("db.find({key: true})")'
    value = normalize("db.find({AoMeasurement: {x: obj.true, y: f'{selected_id}', z: fun({'x': 1})}})")
    assert "obj.true" in value and "f'{selected_id}'" in value and "fun({'x': 1})" in value
    assert tokens("# ignored") == []


def test_compilation():
    assert compile_input("db.find({AoMeasurement: {") is None
    assert compile_input("db.find({AoMea") is None
    assert compile_input("x = (") is None
    assert compile_input("x = 1")
    with pytest.raises(SyntaxError):
        compile_input("1 + * 2")
    with pytest.raises(SyntaxError):
        compile_input("db.find({broken\n\n")
    with pytest.raises(SyntaxError):
        compile_input("db.find({x: /* nope */ 2})")
    assert scan("db.find({x: # comment\n 2})")[1] == []


def test_python_string_lexing_and_key_boundaries():
    source = """db.find({Entity: {value: f'{obj['value']}', template: t'{obj['value']}'}})"""
    normalized = normalize(source)
    assert "f'{obj['value']}'" in normalized
    assert "t'{obj['value']}'" in normalized
    assert normalize("db.find({bad key: 1})") == "db.find({bad key: 1})"
    with pytest.raises(SyntaxError):
        compile_input("db.find({bad key: 1})")
    assert compile_input('db.find({Entity: {x: f"unfinished') is None
