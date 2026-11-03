import pytest
from prompt_toolkit.document import Document

from odsbox_cli.highlighting import InputLexer


@pytest.mark.parametrize(
    "source",
    [
        "use Lab",
        "db.find({AoMeasurement: {name: 'run', id: 42, active: true}})",
        "# note\nx = (\n1 + 2",
        "x = 'unfinished",
        'x = """unfinished\ntext',
        'x = f"value {1 + 2}"',
        "db.find({$attributes: {test.name: 1}})",
    ],
)
def test_lexer_preserves_source(source, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    render = InputLexer().lex_document(Document(source))
    assert "\n".join("".join(fragment[1] for fragment in render(i)) for i in range(len(source.split("\n")))) == source
    assert render(1000) == []
    assert any(fragment[0] for i in range(len(source.split("\n"))) for fragment in render(i))


def test_styles_and_no_color(monkeypatch):
    source = "db.find({AoMeasurement: {id: 42, flag: true, name: 'text'}}) # comment"
    monkeypatch.delenv("NO_COLOR", raising=False)
    fragments = InputLexer().lex_document(Document(source))(0)
    assert ("class:key", "AoMeasurement") in fragments
    assert ("class:keyword", "true") in fragments
    assert ("class:number", "42") in fragments
    assert ("class:string", "'text'") in fragments
    assert ("class:comment", "# comment") in fragments
    monkeypatch.setenv("NO_COLOR", "")
    assert InputLexer().lex_document(Document(source))(0) == [("", source)]
