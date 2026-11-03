"""Local, context-aware completion. Never executes user expressions."""

from __future__ import annotations

import inspect
import re
import warnings
from collections.abc import Callable, Iterable, Mapping

import pandas as pd
from odsbox.proto import ods_pb2 as ods
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from odsbox_cli.database import Database
from odsbox_cli.help import TOPICS
from odsbox_cli.syntax import KEY, key_text, scan, tokens

ROOT = ["$attributes", "$orderby", "$groupby", "$options"]
FILTER = [
    "$eq",
    "$neq",
    "$lt",
    "$lte",
    "$gt",
    "$gte",
    "$in",
    "$notinset",
    "$like",
    "$notlike",
    "$null",
    "$notnull",
    "$between",
    "$and",
    "$or",
    "$not",
    "$unit",
    "$options",
    "$nested",
]
AGGREGATE = [
    "$none",
    "$count",
    "$dcount",
    "$min",
    "$max",
    "$avg",
    "$stddev",
    "$sum",
    "$distinct",
    "$point",
    "$ia",
    "$unit",
]
OPTIONS = ["$rowlimit", "$rowskip", "$seqlimit", "$seqskip"]
COMMANDS = [
    "use ",
    "connections ",
    "disconnect",
    "help ",
    "exit",
    "db.find(",
    "db.bulk(",
    "db.reconnect()",
    "db.script_starter(",
    "gui.plot(",
    "gui.table(",
    "db.model.find(",
    "db.model.relations(",
]


class SpanCompletion(Completion):
    def __init__(self, text: str, start: int, end: int, cursor: int, metadata: str = "") -> None:
        super().__init__(text, start_position=start - cursor, display_meta=metadata)
        self.end = end


class CompletionBuffer(Buffer):
    """Apply the same full-token edit for menu previews, acceptance and cancellation."""

    def go_to_completion(self, index: int | None) -> None:
        state = self.complete_state
        if state is None:
            return
        state.go_to_index(index)
        original = state.original_document
        candidate = state.current_completion
        if isinstance(candidate, SpanCompletion):
            start = original.cursor_position + candidate.start_position
            text = original.text[:start] + candidate.text + original.text[candidate.end :]
            self.document = Document(text, start + len(candidate.text))
        else:
            text, position = state.new_text_and_position()
            self.document = Document(text, position)
        self.complete_state = state

    def apply_completion(self, completion: Completion) -> None:
        if self.complete_state:
            self.go_to_completion(None)
        if isinstance(completion, SpanCompletion):
            start = self.cursor_position + completion.start_position
            self.complete_state = None
            self.document = Document(
                self.text[:start] + completion.text + self.text[completion.end :], start + len(completion.text)
            )
        else:
            super().apply_completion(completion)


def _entity(model: ods.Model, name: str) -> ods.Model.Entity | None:
    exact = [e for e in model.entities.values() if e.name.casefold() == name.casefold()]
    matches = exact or [e for e in model.entities.values() if e.base_name.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


def _path_entity(entity: ods.Model.Entity, parts: list[str], model: ods.Model) -> ods.Model.Entity | None:
    current = entity
    for part in parts:
        relation = next(
            (r for r in current.relations.values() if part.casefold() in (r.name.casefold(), r.base_name.casefold())),
            None,
        )
        if relation is None:
            return None
        target = model.entities.get(relation.entity_name)
        if target is None:
            return None
        current = target
    return current


class InspectorCompleter(Completer):
    def __init__(
        self,
        model: Callable[[], ods.Model | None],
        servers: Callable[[], list[str]],
        namespace: Mapping[str, object],
    ) -> None:
        self.model = model
        self.servers = servers
        self.namespace = namespace

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        try:
            yield from self._candidates(document)
        except Exception as exc:
            warnings.warn(f"Autocomplete failed ({type(exc).__name__})", stacklevel=2)

    def _bulk_candidates(self, document: Document, start: int, end: int) -> list[Completion] | None:
        items = tokens(document.text_before_cursor)
        stack: list[int] = []
        bulk_start: int | None = None
        for index, item in enumerate(items):
            if item.text in ("(", "[", "{"):
                stack.append(index)
                if [part.text for part in items[max(0, index - 3) : index + 1]] == ["db", ".", "bulk", "("]:
                    bulk_start = index
            elif item.text in (")", "]", "}") and stack:
                closed = stack.pop()
                if closed == bulk_start:
                    bulk_start = None
        if bulk_start is None:
            return None
        if not stack or stack[-1] != bulk_start:
            return []
        arguments = items[bulk_start + 1 :]
        segments: list[list[str]] = [[]]
        depth = 0
        for item in arguments:
            if item.text == "," and depth == 0:
                segments.append([])
            else:
                segments[-1].append(item.text)
                if item.text in ("(", "[", "{"):
                    depth += 1
                elif item.text in (")", "]", "}"):
                    depth -= 1
        current = segments[-1]
        prefix = document.text[start : document.cursor_position]
        if current and current != [prefix]:
            return []
        parameters = list(inspect.signature(Database.bulk).parameters.values())[1:]
        used: set[str] = set()
        positional = 0
        for segment in segments[:-1]:
            if len(segment) > 1 and segment[1] == "=":
                used.add(segment[0])
            elif segment:
                if segment[0] in ("*", "**"):
                    return []
                positional += 1
        used.update(parameter.name for parameter in parameters[:positional])
        suffix = tokens(document.text[end:])
        depth = 0
        for index, item in enumerate(suffix):
            if item.text in (")", "]", "}"):
                if depth == 0:
                    break
                depth -= 1
            elif item.text in ("(", "[", "{"):
                depth += 1
            elif depth == 0 and index + 1 < len(suffix) and suffix[index + 1].text == "=":
                used.add(item.text)
        equals = bool(re.match(r"\s*=", document.text[end:]))
        return [
            SpanCompletion(
                parameter.name + ("" if equals else "="), start, end, document.cursor_position, "bulk parameter"
            )
            for parameter in parameters
            if parameter.name not in used and parameter.name.startswith(prefix)
        ]

    def _candidates(self, document: Document) -> Iterable[Completion]:
        before, cursor = document.text_before_cursor, document.cursor_position
        start = cursor
        while start and re.match(r"[\w$.*]", document.text[start - 1]):
            start -= 1
        end = cursor
        while end < len(document.text) and re.match(r"[\w$.*]", document.text[end]):
            end += 1
        prefix = document.text[start:cursor]
        bulk = self._bulk_candidates(document, start, end)
        if bulk is not None:
            yield from bulk
            return
        quoted = start > 0 and document.text[start - 1] in "'\""
        for token in tokens(document.text):
            if token.kind == "string" and token.start < cursor <= token.end:
                if document.text[token.start] in "'\"":
                    start = token.start + 1
                    end = token.end
                    quote = document.text[token.start]
                    if token.end > start and document.text[token.end - 1] == quote:
                        end -= 1
                    prefix = document.text[start:cursor]
                    quoted = True
                break
        candidates: list[tuple[str, str]] = []
        key_position = False
        literal_value = False
        model = self.model()
        if re.match(r"^\s*use\s", before):
            match = re.match(r"^\s*use\s+(['\"]?)(.*)", before, re.S)
            if match:
                prefix = match[2]
                start = match.start(2)
                end = len(document.text.rstrip("'\""))
                quoted = bool(match[1])
                candidates = [(s, "server") for s in self.servers()]
        elif before.startswith("help "):
            candidates = [(t, "help topic") for t in TOPICS]
        elif before.startswith("connections "):
            candidates = [(c, "connection command") for c in ("list", "import", "import-pilot")]
        elif re.search(r"""db\.model\.(?:find|relations)\(\s*(?:['"][^'"]*|[\w$]*)$""", before):
            candidates = self._entities(model)
            literal_value = True
        else:
            items, frames, _ = scan(before)
            query_frames = [f for f in frames if f.query]
            roots = [i for i, frame in enumerate(query_frames) if frame.root]
            if roots:
                query_frames = query_frames[roots[-1] :]
            if query_frames and model is None and query_frames[-1].key is None:
                options = query_frames[-1].path == ["$options"]
                candidates = [(c, "query syntax") for c in (OPTIONS if options else ROOT)]
                key_position = True
            if query_frames and model is not None:
                frame = query_frames[-1]
                path = list(frame.path)
                root_frame = query_frames[0]
                root_name = root_frame.entity
                if root_name is None:
                    if frame is root_frame:
                        candidates = self._entities(model) + [(c, "query clause") for c in ROOT]
                    elif frame.path == ["$options"]:
                        candidates = [(c, "option") for c in OPTIONS]
                    key_position = True
                else:
                    entity = _entity(model, root_name)
                    if entity is not None:
                        path = [p for p in path if p != root_name and not p.startswith("$")]
                        value_key = frame.key if frame.key and not frame.key.startswith("$") else None
                        key_position = frame.opener == "{" and frame.key is None
                        if key_position and frame is root_frame:
                            candidates = [(c, "query clause") for c in ROOT]
                        elif key_position:
                            partial_items = items[frame.key_start :]
                            if partial_items:
                                prefix_raw = key_text(partial_items)
                                if prefix_raw is not None:
                                    prefix = prefix_raw
                            pieces = prefix.split(".")
                            target = _path_entity(entity, path + pieces[:-1], model)
                            if target is not None:
                                leading = ".".join(pieces[:-1])
                                leading = leading + "." if leading else ""
                                candidates = [
                                    (leading + a.name, f"attribute {ods.DataTypeEnum.Name(a.data_type)}")
                                    for a in target.attributes.values()
                                ] + [
                                    (leading + a.base_name, "base attribute")
                                    for a in target.attributes.values()
                                    if a.base_name and a.base_name != a.name
                                ]
                                candidates += [
                                    (leading + r.name, f"relation -> {r.entity_name}")
                                    for r in target.relations.values()
                                ]
                                candidates += [
                                    (leading + r.base_name, f"base relation -> {r.entity_name}")
                                    for r in target.relations.values()
                                    if r.base_name and r.base_name != r.name
                                ]
                            operators = ["$and", "$or", "$not"] if target is not None else FILTER
                            if frame.path == ["$options"]:
                                candidates = [(c, "option") for c in OPTIONS]
                            elif "$attributes" in frame.path:
                                candidates += [(c, "aggregate") for c in AGGREGATE]
                            elif "$orderby" not in frame.path and "$groupby" not in frame.path:
                                candidates += [(c, "operator") for c in operators]
                        else:
                            if value_key:
                                path += value_key.split(".")
                            if path:
                                owner = _path_entity(entity, path[:-1], model)
                                if owner is not None:
                                    attribute = next(
                                        (
                                            a
                                            for a in owner.attributes.values()
                                            if path[-1].casefold() in (a.name.casefold(), a.base_name.casefold())
                                        ),
                                        None,
                                    )
                                    if attribute and attribute.enumeration in model.enumerations:
                                        enum = model.enumerations[attribute.enumeration]
                                        candidates = [(label, "enum label") for label in enum.items]
                                        literal_value = True
            if not query_frames:
                match = re.search(
                    r"""(\w+)(?:\[\s*(?:\[(?:[^\[\]]*?,\s*)?)?|\.sort_values\(\s*)['"]([^'"]*)$""",
                    before,
                )
                if match:
                    value = self.namespace.get(match[1])
                    if type(value) is pd.DataFrame:
                        prefix = match[2]
                        candidates = [(c, "DataFrame column") for c in value.columns if isinstance(c, str)]
                else:
                    candidates = [
                        (name, "DataFrame") for name, value in self.namespace.items() if type(value) is pd.DataFrame
                    ]
                    if not before.strip() or start == 0:
                        candidates += [(c, "command") for c in COMMANDS]
        seen: set[str] = set()
        for value, metadata in sorted(
            set(candidates), key=lambda c: (c[0].casefold(), not c[1].startswith("entity ("), c[1])
        ):
            if not value.casefold().startswith(prefix.casefold()):
                continue
            if value in seen:
                continue
            seen.add(value)
            inserted = value
            if quoted:
                quote = document.text[start - 1]
                inserted = value.replace("\\", "\\\\").replace(quote, "\\" + quote)
            elif (key_position and not KEY.fullmatch(value)) or literal_value:
                inserted = repr(value)
            yield SpanCompletion(inserted, start, end, cursor, metadata)

    @staticmethod
    def _entities(model: ods.Model | None) -> list[tuple[str, str]]:
        if model is None:
            return []
        candidates = [(e.name, f"entity ({e.base_name})") for e in model.entities.values()]
        bases: dict[str, list[str]] = {}
        for entity in model.entities.values():
            if entity.base_name:
                bases.setdefault(entity.base_name, []).append(entity.name)
        candidates += [
            (name, "base entity" if len(names) == 1 else "ambiguous: " + ", ".join(sorted(names)))
            for name, names in bases.items()
        ]
        return candidates
