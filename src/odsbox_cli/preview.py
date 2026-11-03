"""Optional, bounded local DataFrame previews."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_complex_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_timedelta64_dtype,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from matplotlib.widgets import Button


def envelope(values: np.ndarray[Any, Any], max_points: int) -> np.ndarray[Any, Any]:
    """Return ordered row positions; bins with gaps become breaks, never bridges."""
    if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 6:
        raise ValueError("max_points must be an integer >= 6")
    size = len(values)
    if size <= max_points:
        return np.arange(size)
    bins = (max_points - 2) // 2
    width = (size - 2 + bins - 1) // bins
    middle = values[1:-1]
    padded = np.full(bins * width, np.nan)
    padded[: len(middle)] = middle
    blocks = padded.reshape(bins, width)
    starts = np.arange(bins) * width
    lengths = np.clip(len(middle) - starts, 0, width)
    valid = np.arange(width)[None, :] < lengths[:, None]
    finite = np.isfinite(blocks)
    complete = np.all(finite | ~valid, axis=1)
    low = np.argmin(np.where(finite & valid, blocks, np.inf), axis=1)
    high = np.argmax(np.where(finite & valid, blocks, -np.inf), axis=1)
    # A missing sample represents the whole bin conservatively, avoiding invented lines.
    gap = np.argmax(valid & ~finite, axis=1)
    low = np.where(complete, low, gap)
    high = np.where(complete, high, gap)
    positions = np.stack((np.minimum(low, high), np.maximum(low, high)), axis=1)
    positions += starts[:, None] + 1
    positions = positions[lengths > 0].reshape(-1)
    return np.unique(np.concatenate(([0], positions, [size - 1])))


def _numeric(dtype: Any) -> bool:
    return bool(is_numeric_dtype(dtype) and not is_bool_dtype(dtype) and not is_complex_dtype(dtype))


def _axis(values: pd.Index | pd.Series[Any]) -> bool:
    return bool(_numeric(values.dtype) or is_datetime64_any_dtype(values.dtype) or is_timedelta64_dtype(values.dtype))


class TablePage:
    """Keep only the visible cell strings; retain a reference to the original frame."""

    def __init__(self, frame: pd.DataFrame, columns: list[Any]) -> None:
        self.frame = frame
        self.columns = columns
        self.row = 0
        self.column = 0

    def move(self, rows: int = 0, columns: int = 0) -> None:
        self.row = max(0, min(self.row + rows * 50, ((len(self.frame) - 1) // 50) * 50))
        self.column = max(0, min(self.column + columns * 8, ((len(self.columns) - 1) // 8) * 8))

    def content(self) -> tuple[list[str], list[list[str]], str]:
        chosen = self.columns[self.column : self.column + 8]
        page = self.frame.iloc[self.row : self.row + 50].loc[:, chosen]

        def cell(value: object) -> str:
            text = format(value, ".6g") if isinstance(value, (float, np.floating)) else str(value)
            text = text.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            return text if len(text) <= 40 else text[:37] + "..."

        labels = ["index", *(cell(label) for label in chosen)]
        cells = [[cell(index), *(cell(value) for value in row)] for index, *row in page.itertuples(name=None)]
        caption = (
            f"Rows {self.row + 1}-{self.row + len(page)} / {len(self.frame)}; "
            f"columns {self.column + 1}-{self.column + len(chosen)} / {len(self.columns)}. "
            "Read-only; <=40 chars/cell, floats: 6 significant digits."
        )
        return labels, cells, caption


class Gui:
    def __init__(self, namespace: Mapping[str, object], output: Callable[[str], None]) -> None:
        self.namespace = namespace
        self.output = output
        self.interactive = False
        self._figures: list[Figure] = []
        self._buttons: dict[Figure, list[Button]] = {}

    @staticmethod
    def _pyplot() -> Any:
        try:
            import matplotlib.pyplot as plt
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.split(".")[0] == "matplotlib":
                raise ValueError(
                    'GUI previews require the plot extra: uv sync --extra plot or uv tool install "odsbox-cli[plot]"'
                ) from exc
            raise
        return plt

    def _frame(self, frame: pd.DataFrame | None) -> pd.DataFrame:
        candidate = self.namespace.get("_") if frame is None else frame
        if not isinstance(candidate, pd.DataFrame):
            raise ValueError("Provide a DataFrame or first load one into _")
        if candidate.empty:
            raise ValueError("Cannot preview an empty DataFrame")
        if not candidate.columns.is_unique:
            raise ValueError("Preview requires unique column labels; rename duplicate columns first")
        return candidate

    @staticmethod
    def _columns(frame: pd.DataFrame, columns: Sequence[Any] | None) -> list[Any]:
        if isinstance(columns, (str, bytes)):
            raise ValueError("columns must be a sequence of column labels, not a string")
        chosen = list(frame.columns if columns is None else columns)
        if not chosen or len(set(chosen)) != len(chosen):
            raise ValueError("Select at least one column, with no duplicates")
        missing = [label for label in chosen if label not in frame.columns]
        if missing:
            raise ValueError(f"Unknown columns: {missing}")
        return chosen

    def _prepare(self, save: str | Path | None) -> Any:
        plt = self._pyplot()
        if save is None:
            if not self.interactive:
                raise ValueError("Interactive previews require the CLI terminal; use save='preview.png' for scripts")
            from matplotlib.backends.registry import backend_registry

            _, gui = backend_registry.resolve_backend(plt.get_backend())  # type: ignore[no-untyped-call]
            if gui not in {"tk", "qt", "gtk3", "gtk4", "wx", "macosx"}:
                raise ValueError(
                    "No supported interactive matplotlib backend; "
                    "enable a desktop GUI backend or use save='preview.png'"
                )
        return plt

    def _finish(self, figure: Figure, save: str | Path | None, plt: Any) -> None:
        if save is not None:
            figure.savefig(save)
            self.output(f"Saved preview to {save}")
            plt.close(figure)
            return
        self._figures.append(figure)
        figure.canvas.mpl_connect("close_event", lambda event: self._forget(figure))
        figure.show()
        figure.canvas.draw_idle()

    @staticmethod
    def _subplots(plt: Any, save: str | Path | None, **options: Any) -> tuple[Figure, Any]:
        if save is None:
            try:
                figure, axes = plt.subplots(**options)
                return figure, axes
            except ImportError as exc:
                raise ValueError(
                    "Cannot initialize the GUI backend; install its toolkit or use save='preview.png'"
                ) from exc
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        figure = Figure(figsize=options.pop("figsize"))
        FigureCanvasAgg(figure)
        return figure, figure.subplots(**options)

    def _forget(self, figure: Figure) -> None:
        if figure in self._figures:
            self._figures.remove(figure)
        self._buttons.pop(figure, None)

    def plot(
        self,
        frame: pd.DataFrame | None = None,
        *,
        columns: Sequence[Any] | None = None,
        x: Any = None,
        max_points: int = 2000,
        save: str | Path | None = None,
    ) -> None:
        frame = self._frame(frame)
        envelope(np.empty(0), max_points)
        if columns is None:
            numeric = [label for label in frame.columns if label != x and _numeric(frame[label].dtype)]
            chosen = numeric[:8]
            if len(numeric) > 8:
                self.output(f"Plotting first 8 of {len(numeric)} numeric signals; use columns= to select others.")
            if not chosen:
                raise ValueError("No real numeric signal columns to plot")
        else:
            chosen = self._columns(frame, columns)
            if any(not _numeric(frame[label].dtype) for label in chosen):
                raise ValueError("Plot columns must be real numeric signals (not boolean, complex or text)")
        if x is None:
            axis: pd.Index | pd.Series[Any] = frame.index
            if not _axis(axis):
                axis = pd.RangeIndex(len(frame))
                self.output("Nonnumeric index: using row positions for x.")
            x_label = str(frame.index.name or "index") if axis is frame.index else "row"
        else:
            self._columns(frame, [x])
            axis = frame[x]
            if not _axis(axis):
                raise ValueError("x must be a numeric, datetime or timedelta column")
            x_label = str(x)
        if is_timedelta64_dtype(axis.dtype):
            axis = axis.dt.total_seconds() if isinstance(axis, pd.Series) else pd.TimedeltaIndex(axis).total_seconds()
            x_label += " [s]"
        x_values = axis.to_numpy()
        invalid_x = pd.isna(x_values)
        if _numeric(axis.dtype):
            x_values = axis.to_numpy(dtype=float, na_value=np.nan)
            invalid_x = ~np.isfinite(x_values)
        plt = self._prepare(save)
        figure = None
        try:
            figure, axes = self._subplots(
                plt,
                save,
                nrows=len(chosen),
                ncols=1,
                sharex=True,
                squeeze=False,
                figsize=(11, 2.2 * len(chosen) + 1),
            )
            units = frame.attrs.get("unit_names", {})
            for label, axes_row in zip(chosen, axes):
                values = frame[label].to_numpy(dtype=float, na_value=np.nan, copy=True)
                values[invalid_x | ~np.isfinite(values)] = np.nan
                positions = envelope(values, max_points)
                # Invalid x cannot be rendered, but the corresponding NaN still breaks the line.
                selected_x = x_values[positions].copy()
                if np.any(invalid_x[positions]):
                    valid_x = np.flatnonzero(~invalid_x)
                    if not len(valid_x):
                        raise ValueError("x has no finite coordinates")
                    selected_x[invalid_x[positions]] = x_values[valid_x[0]]
                axes_row[0].plot(
                    selected_x, values[positions], linewidth=0.8, marker="." if len(positions) == 1 else None
                )
                unit = units.get(label, "") if isinstance(units, dict) else ""
                axes_row[0].set_ylabel(f"{label} [{unit}]" if unit else str(label), parse_math=False, usetex=False)
                axes_row[0].grid(True, alpha=0.3)
            axes[-1, 0].set_xlabel(x_label, parse_math=False, usetex=False)
            partial = "; PARTIAL RESULT" if frame.attrs.get("partial_result", False) else ""
            figure.suptitle(f"Preview: {len(frame)} rows; <= {max_points} points/signal{partial}")
            figure.tight_layout()
            self._finish(figure, save, plt)
        except BaseException:
            if figure is not None:
                self._forget(figure)
                plt.close(figure)
            raise

    def table(
        self, frame: pd.DataFrame | None = None, *, columns: Sequence[Any] | None = None, save: str | Path | None = None
    ) -> None:
        frame = self._frame(frame)
        page = TablePage(frame, self._columns(frame, columns))
        plt = self._prepare(save)
        figure = None
        try:
            figure, axes = self._subplots(plt, save, figsize=(14, 12))
            figure.subplots_adjust(bottom=0.12, top=0.94)

            def render() -> None:
                axes.clear()
                axes.axis("off")
                labels, cells, caption = page.content()
                width = min(40, max(8, 145 // len(labels)))

                for index, label in enumerate(labels):
                    values = [label, "-" * min(width, len(label)), *(row[index] for row in cells)]
                    text = "\n".join(value if len(value) <= width else value[: width - 3] + "..." for value in values)
                    axes.text(
                        index / len(labels),
                        1,
                        text,
                        transform=axes.transAxes,
                        va="top",
                        fontsize=8,
                        fontfamily="monospace",
                        linespacing=1.2,
                        parse_math=False,
                        usetex=False,
                    )
                partial = " PARTIAL RESULT." if frame.attrs.get("partial_result", False) else ""
                axes.set_title(caption + partial, fontsize=9)
                for button, available in zip(
                    buttons,
                    [page.row > 0, page.row + 50 < len(frame), page.column > 0, page.column + 8 < len(page.columns)],
                ):
                    button.set_active(available)
                    button.ax.set_alpha(1 if available else 0.3)
                if save is None:
                    figure.canvas.draw_idle()

            buttons: list[Button] = []
            if save is None:
                from matplotlib.widgets import Button

                for index, (text, rows, cols) in enumerate(
                    [("Previous rows", -1, 0), ("Next rows", 1, 0), ("Previous columns", 0, -1), ("Next columns", 0, 1)]
                ):
                    button = Button(figure.add_axes((0.08 + index * 0.23, 0.035, 0.2, 0.04)), text)

                    def move(event: object, rows: int = rows, cols: int = cols) -> None:
                        page.move(rows, cols)
                        render()

                    button.on_clicked(move)
                    buttons.append(button)
                self._buttons[figure] = buttons
            render()
            self._finish(figure, save, plt)
        except BaseException:
            if figure is not None:
                self._forget(figure)
                plt.close(figure)
            raise

    def pump(self) -> None:
        for figure in self._figures[:]:
            figure.canvas.flush_events()

    @property
    def has_windows(self) -> bool:
        return bool(self._figures)

    def close(self) -> None:
        if self._figures:
            plt = self._pyplot()
            for figure in self._figures[:]:
                plt.close(figure)
                self._forget(figure)
