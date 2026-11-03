"""Conservative delimiter pairing for typed terminal input."""

from __future__ import annotations

import io
import re
import token
import tokenize

PAIRS = {"(": ")", "[": "]", "{": "}", "'": "'", '"': '"'}
STRING_PREFIXES = {"r", "u", "b", "f", "t", "br", "rb", "fr", "rf", "tr", "rt"}


def closing_mate(text: str, cursor: int, opener: str) -> str:
    """Return a mate only outside comments/strings at a safe insertion boundary."""
    if opener not in PAIRS or not 0 <= cursor <= len(text):
        return ""
    if cursor < len(text) and not (text[cursor].isspace() or text[cursor] in ")]},:;"):
        return ""
    before = text[:cursor]
    slashes = len(before) - len(before.rstrip("\\"))
    if opener in "'\"" and slashes % 2:
        return ""
    if opener in "'\"":
        word = re.search(r"[\w]+\Z", before)
        if word and word[0].lower() not in STRING_PREFIXES:
            return ""
    formatted = 0
    try:
        for item in tokenize.generate_tokens(io.StringIO(before).readline):
            if item.type in {token.FSTRING_START, token.TSTRING_START}:
                formatted += 1
            elif item.type in {token.FSTRING_END, token.TSTRING_END}:
                formatted -= 1
            elif item.type == tokenize.ERRORTOKEN and item.string in "'\"":
                return ""
            elif item.type == tokenize.COMMENT and item.end[0] == before.count("\n") + 1:
                return ""
    except tokenize.TokenError as exc:
        if "string" in str(exc.args[0]):
            return ""
    except IndentationError, SyntaxError:
        return ""
    return "" if formatted else PAIRS[opener]
