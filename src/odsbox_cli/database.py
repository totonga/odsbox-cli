"""Read-only convenience API and connection lifecycle."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
from odsbox import ConI
from odsbox.model_cache import ModelCache
from odsbox.proto import ods_pb2 as ods

from odsbox_cli.connections import Config, Registry, connect
from odsbox_cli.script_starter import generate, query_snapshot


class Session:
    def __init__(self, registry: Registry, factory: Callable[[Config], ConI] = connect) -> None:
        self.registry = registry
        self.factory = factory
        self.name: str | None = None
        self.model: ods.Model | None = None
        self.connection: ConI | None = None
        self.config: Config | None = None
        self.last_query: str | None = None
        self.query_export_error: str | None = None

    def use(self, name: str) -> None:
        config = deepcopy(self.registry.get(name))
        snapshot = deepcopy(config)
        replacement = self.factory(config)
        try:
            model = replacement.model()
        except BaseException:
            self._cleanup(replacement)
            raise
        old = self.connection
        self.connection, self.model, self.name = replacement, model, name
        self.config = snapshot
        self.last_query, self.query_export_error = None, None
        if old is not None:
            self._cleanup(old)

    @staticmethod
    def _cleanup(connection: ConI) -> None:
        try:
            connection.logout()
        except Exception as exc:
            warnings.warn(f"Session logout failed: {type(exc).__name__}", stacklevel=2)

    def disconnect(self) -> None:
        old = self.connection
        self.connection, self.model, self.name = None, None, None
        self.config, self.last_query, self.query_export_error = None, None, None
        if old is not None:
            self._cleanup(old)

    def reconnect(self) -> None:
        if self.name is None:
            raise ValueError("Not connected; use <server name> first")
        self.use(self.name)

    def require(self) -> ConI:
        if self.connection is None:
            raise ValueError("Not connected; use <server name> first")
        return self.connection


class Model:
    def __init__(self, session: Session, remember: Callable[[pd.DataFrame], None]) -> None:
        self._session = session
        self._remember = remember

    def find(self, name: str | None = None) -> pd.DataFrame:
        cache = ModelCache(self._session.require().model())
        if name is None:
            columns = ["aid", "name", "base_name"]
            rows = [{"aid": e.aid, "name": e.name, "base_name": e.base_name} for e in cache.model().entities.values()]
        else:
            columns = ["id", "name", "base_name", "data_type", "enumeration", "unit_id", "obligatory", "unique"]
            rows = [
                {
                    "id": a.id,
                    "name": a.name,
                    "base_name": a.base_name,
                    "data_type": ods.DataTypeEnum.Name(a.data_type),
                    "enumeration": a.enumeration,
                    "unit_id": a.unit_id,
                    "obligatory": a.obligatory,
                    "unique": a.unique,
                }
                for a in cache.entity(name).attributes.values()
            ]
        result = pd.DataFrame(rows, columns=columns)
        self._remember(result)
        return result

    def relations(self, name: str) -> pd.DataFrame:
        entity = ModelCache(self._session.require().model()).entity(name)
        columns = ["name", "base_name", "target", "target_aid", "range_min", "range_max", "inverse_name"]
        result = pd.DataFrame(
            [
                {
                    "name": r.name,
                    "base_name": r.base_name,
                    "target": r.entity_name,
                    "target_aid": r.entity_aid,
                    "range_min": r.range_min,
                    "range_max": r.range_max,
                    "inverse_name": r.inverse_name,
                }
                for r in entity.relations.values()
            ],
            columns=columns,
        )
        self._remember(result)
        return result


class Database:
    def __init__(self, session: Session, remember: Callable[[pd.DataFrame], None]) -> None:
        self._session = session
        self._remember = remember
        self.model = Model(session, remember)

    def reconnect(self) -> None:
        """Establish a fresh session for the selected server using normal authentication."""
        self._session.reconnect()

    def find(self, query: dict[str, Any] | str) -> pd.DataFrame:
        try:
            snapshot, error = query_snapshot(query), None
        except (TypeError, ValueError, RecursionError) as exc:
            snapshot, error = None, f"Saved query is not JSON-portable ({type(exc).__name__}): {exc}"
        result = self._session.require().query(query)
        self._session.last_query, self._session.query_export_error = snapshot, error
        self._remember(result)
        return result

    def script_starter(self, parent: str | Path, *, open_folder: bool = True) -> Path:
        """Create a timestamped independent uv project without exporting credentials."""
        self._session.require()
        config = self._session.config
        if config is None:
            raise ValueError("No connection settings captured; use <server name> first")
        if self._session.query_export_error is not None:
            raise ValueError(self._session.query_export_error)
        return generate(config, self._session.last_query, parent, open_folder=open_folder)

    def bulk(
        self,
        submatrix_iid: int,
        column_patterns: list[str] | None = None,
        column_patterns_case_insensitive: bool = False,
        date_as_timestamp: bool = True,
        set_independent_as_index: bool = True,
        values_start: int = 0,
        values_limit: int = 0,
        *,
        raise_on_partial_result: bool = False,
        valid_flag: int | bool | None = None,
    ) -> pd.DataFrame:
        """Read a submatrix through odsbox.bulk.data_read, retaining its metadata.

        Patterns support * and ?; values_limit=0 reads all remaining samples.
        valid_flag is forwarded unchanged (upstream maps both booleans to mask 15).
        Set raise_on_partial_result=True to require a complete server response.
        """
        result = self._session.require().bulk.data_read(
            submatrix_iid,
            column_patterns,
            column_patterns_case_insensitive,
            date_as_timestamp,
            set_independent_as_index,
            values_start,
            values_limit,
            raise_on_partial_result=raise_on_partial_result,
            valid_flag=valid_flag,
        )
        self._remember(result)
        if result.attrs.get("partial_result", False):
            warnings.warn(
                "Bulk read returned a partial result. Use raise_on_partial_result=True to require completeness.",
                stacklevel=2,
            )
        return result
