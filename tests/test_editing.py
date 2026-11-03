import pytest

from odsbox_cli.editing import PAIRS, closing_mate


@pytest.mark.parametrize("opener,mate", PAIRS.items())
@pytest.mark.parametrize(
    "text",
    [
        "|",
        "db.find|",
        "x = |",
        "x = |)",
        "x = |]",
        "x = |}",
        "x = |,",
        "x = |:",
        "x = |;",
        "x = | ",
        "x = |\n",
        "db.find({name: |})",
    ],
)
def test_safe_boundaries(opener, mate, text):
    cursor = text.index("|")
    text = text.replace("|", "")
    if opener in "'\"" and text[:cursor].endswith("find"):
        assert closing_mate(text, cursor, opener) == ""
    else:
        assert closing_mate(text, cursor, opener) == mate


@pytest.mark.parametrize(
    "source",
    [
        "x = 'hello |world'",
        'x = "hello |world"',
        "x = '|",
        'x = "|',
        'x = """hello\n|',
        "x = '''hello\n|",
        "# note |",
        "x = 1 # note |",
        'x = f"value {|}"',
        'x = f"{|',
        'x = r"hello |',
        'x = b"hello |',
        'x = t"template {|}"',
        "x = |word",
        "x = na|me",
    ],
)
@pytest.mark.parametrize("opener", PAIRS)
def test_literal_contexts(source, opener):
    cursor = source.index("|")
    assert closing_mate(source.replace("|", ""), cursor, opener) == ""


@pytest.mark.parametrize("prefix", ["r", "b", "u", "f", "t", "fr", "rf", "br", "rb", "tr", "rt", "R", "F"])
def test_string_prefixes(prefix):
    source = "x = " + prefix
    assert closing_mate(source, len(source), '"') == '"'


@pytest.mark.parametrize(
    "source", ["use ", "connections import ", "x = 'done' + ", "# old comment\n", 'x = """done"""\n']
)
def test_quotes_after_complete_context(source):
    assert closing_mate(source, len(source), "'") == "'"


def test_escaped_quotes_apostrophes_and_invalid_inputs():
    assert closing_mate("use OBrien", 10, "'") == ""
    assert closing_mate("\\", 1, '"') == ""
    assert closing_mate("\\\\", 2, '"') == '"'
    assert closing_mate("", 0, ")") == ""
    assert closing_mate("", -1, "(") == ""
    assert closing_mate("", 1, "(") == ""
    assert closing_mate("x = ([", 6, "{") == "}"
    assert closing_mate("x = (\n  ", 8, "[") == "]"
