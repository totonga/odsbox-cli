"""Basic input-only styles; never changes or evaluates source."""

from __future__ import annotations

import io
import keyword
import os
import re
import tokenize
from collections.abc import Callable

from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style

from odsbox_cli.syntax import scan, tokens

INPUT_STYLE = Style.from_dict(
    {
        "command": "ansicyan bold",
        "key": "ansicyan",
        "keyword": "ansimagenta",
        "string": "ansigreen",
        "number": "ansiyellow",
        "comment": "ansibrightblack italic",
        "punctuation": "ansibrightblack",
    }
)


class InputLexer(Lexer):
    def lex_document(self, document: Document) -> Callable[[int], StyleAndTextTuples]:
        text = document.text
        styles = [""] * len(text)
        if "NO_COLOR" not in os.environ:

            def paint(start: int, end: int, style: str) -> None:
                styles[start:end] = [f"class:{style}"] * (end - start)

            offsets = [0]
            for line in text.splitlines(keepends=True):
                offsets.append(offsets[-1] + len(line))
            try:
                for item in tokenize.generate_tokens(io.StringIO(text).readline):
                    start = offsets[min(item.start[0] - 1, len(offsets) - 1)] + item.start[1]
                    end = offsets[min(item.end[0] - 1, len(offsets) - 1)] + item.end[1]
                    style = {
                        tokenize.COMMENT: "comment",
                        tokenize.NUMBER: "number",
                        tokenize.OP: "punctuation",
                    }.get(item.type)
                    if item.type == tokenize.NAME and (
                        keyword.iskeyword(item.string) or item.string in {"true", "false", "null"}
                    ):
                        style = "keyword"
                    if style:
                        paint(start, end, style)
            except tokenize.TokenError as exc:
                if "multi-line string" in str(exc.args[0]):
                    row, column = exc.args[1]
                    paint(offsets[row - 1] + column, len(text), "string")
            except IndentationError:
                pass  # Incomplete editing buffers are not syntax errors to the lexer.
            for start, end, replacement in scan(text)[2]:
                paint(start, end, "key" if replacement.startswith(("'", '"')) else "keyword")
            for source_token in tokens(text):
                if source_token.kind == "string":
                    paint(source_token.start, source_token.end, "string")
            # A tokenizer stops at an incomplete string; never color its text as commands.
            match = re.match(r"\s*(use|connections|help)(?=\s|$)|\s*(exit|quit|disconnect)\s*$", text)
            if match:
                name = match[1] or match[2]
                start = text.index(name)
                paint(start, start + len(name), "command")

        lines: list[StyleAndTextTuples] = []
        position = 0
        for line in text.split("\n"):
            fragments: StyleAndTextTuples = []
            for i, character in enumerate(line):
                style = styles[position + i]
                if fragments and fragments[-1][0] == style:
                    fragments[-1] = (style, fragments[-1][1] + character)
                else:
                    fragments.append((style, character))
            lines.append(fragments)
            position += len(line) + 1
        return lambda number: lines[number] if 0 <= number < len(lines) else []
