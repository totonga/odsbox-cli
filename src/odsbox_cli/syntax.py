"""A tolerant lexer shared by relaxed query compilation and completion."""

from __future__ import annotations

import ast
import codeop
import io
import re
import token as token_types
import tokenize
from dataclasses import dataclass, field

KEY = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\Z")


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    kind: str


def tokens(text: str) -> list[Token]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    result: list[Token] = []
    f_start: int | None = None
    f_depth = 0
    try:
        for item in tokenize.generate_tokens(io.StringIO(text).readline):
            start = offsets[min(item.start[0] - 1, len(offsets) - 1)] + item.start[1]
            end = offsets[min(item.end[0] - 1, len(offsets) - 1)] + item.end[1]
            if item.type in {token_types.FSTRING_START, token_types.TSTRING_START}:
                if f_depth == 0:
                    f_start = start
                f_depth += 1
            if f_depth:
                if item.type in {token_types.FSTRING_END, token_types.TSTRING_END}:
                    f_depth -= 1
                    if f_depth == 0 and f_start is not None:
                        result.append(Token(text[f_start:end], f_start, end, "string"))
                        f_start = None
                continue
            if item.type == tokenize.ERRORTOKEN and item.string in "'\"":
                result.append(Token(text[start:], start, len(text), "string"))
                break
            if (
                item.type
                in {
                    tokenize.COMMENT,
                    tokenize.NL,
                    tokenize.NEWLINE,
                    tokenize.INDENT,
                    tokenize.DEDENT,
                    tokenize.ENDMARKER,
                }
                or not item.string.strip()
            ):
                continue
            kind = "string" if item.type == tokenize.STRING else "name" if item.type == tokenize.NAME else "op"
            result.append(Token(item.string, start, end, kind))
    except (tokenize.TokenError, IndentationError) as exc:
        # Incomplete buffers are normal during completion; compilation reports real errors.
        if f_start is not None:
            result.append(Token(text[f_start:], f_start, len(text), "string"))
        elif isinstance(exc, tokenize.TokenError) and "string" in str(exc.args[0]):
            row, column = exc.args[1]
            start = offsets[min(row - 1, len(offsets) - 1)] + max(0, column - 1)
            if start < len(text) and text[start] in "'\"":
                result.append(Token(text[start:], start, len(text), "string"))
    return result


@dataclass
class Frame:
    opener: str
    query: bool
    path: list[str] = field(default_factory=list)
    key_start: int = 0
    key: str | None = None
    entity: str | None = None
    root: bool = False


def key_text(items: list[Token]) -> str | None:
    if any(left.end != right.start for left, right in zip(items, items[1:])):
        return None
    raw = "".join(t.text for t in items)
    if KEY.fullmatch(raw):
        return raw
    if len(items) == 1 and items[0].kind == "string":
        try:
            value = ast.literal_eval(raw)
        except ValueError, SyntaxError:
            return None
        return value if isinstance(value, str) else None
    return None


def scan(text: str) -> tuple[list[Token], list[Frame], list[tuple[int, int, str]]]:
    items = tokens(text)
    stack: list[Frame] = []
    edits: list[tuple[int, int, str]] = []
    for i, token in enumerate(items):
        value = token.text
        parent = stack[-1] if stack else None
        if value in ("(", "[", "{"):
            root = value == "{" and i >= 4 and [t.text for t in items[i - 4 : i]] == ["db", ".", "find", "("]
            nested = parent is not None and parent.query and parent.opener in ("{", "[")
            path = list(parent.path) if parent else []
            if nested and parent is not None and parent.key:
                path.append(parent.key)
            stack.append(Frame(value, root or nested, path if not root else [], i + 1, root=root))
        elif value in (")", "]", "}"):
            if stack and stack[-1].opener == {")": "(", "]": "[", "}": "{"}[value]:
                stack.pop()
        elif parent and parent.query and parent.opener == "{":
            if value == ":" and parent.key is None:
                key_items = items[parent.key_start : i]
                parent.key = key_text(key_items)
                if parent.key and not parent.key.startswith("$") and parent.entity is None:
                    parent.entity = parent.key
                raw = "".join(t.text for t in key_items)
                if key_items and parent.key is not None and KEY.fullmatch(raw):
                    edits.append((key_items[0].start, key_items[-1].end, repr(raw)))
            elif value == ",":
                parent.key_start, parent.key = i + 1, None
        if value in {"true", "false", "null"} and any(f.query for f in stack) and (i == 0 or items[i - 1].text != "."):
            edits.append((token.start, token.end, {"true": "True", "false": "False", "null": "None"}[value]))
    return items, stack, edits


def normalize(text: str) -> str:
    _, _, edits = scan(text)
    # Key replacement owns any constant-like token inside that key.
    accepted: list[tuple[int, int, str]] = []
    for start, end, replacement in sorted(edits, key=lambda e: (e[0], -e[1])):
        if accepted and start < accepted[-1][1]:
            continue
        accepted.append((start, end, replacement))
    for start, end, replacement in reversed(accepted):
        text = text[:start] + replacement + text[end:]
    return text


def compile_input(text: str, *, filename: str = "<odsbox>", first_line: int = 1) -> ast.Module | None:
    source = "\n" * (first_line - 1) + normalize(text)
    try:
        compiled = codeop.compile_command(source, filename=filename, symbol="exec")
    except SyntaxError:
        # A partial relaxed key is not valid Python until its ':' is typed.
        if scan(text)[1] and not text.endswith("\n\n"):
            return None
        raise
    if compiled is None:
        if text.endswith("\n\n"):
            raise SyntaxError("Incomplete input", (filename, first_line, 1, None))
        return None
    return ast.parse(source, filename=filename, mode="exec")
