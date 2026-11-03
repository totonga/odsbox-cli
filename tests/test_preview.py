import builtins
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from odsbox_cli.preview import Gui, TablePage, envelope


@pytest.fixture
def gui():
    import matplotlib

    matplotlib.use("Agg", force=True)
    instance = Gui({}, Mock())
    yield instance
    instance.close()
    import matplotlib.pyplot as plt

    plt.close("all")


@pytest.mark.parametrize("size,budget", [(0, 6), (5, 6), (10, 6), (101, 7), (100003, 2000)])
def test_envelope_budget_spikes_and_order(size, budget):
    values = np.zeros(size)
    if size > 10:
        values[4], values[-5] = 100, -100
    positions = envelope(values, budget)
    assert len(positions) <= budget
    assert np.all(np.diff(positions) > 0)
    if size:
        assert positions[0] == 0 and positions[-1] == size - 1
    if size > 10:
        assert 4 in positions and size - 5 in positions
    if size <= budget:
        np.testing.assert_array_equal(positions, np.arange(size))


@pytest.mark.parametrize("budget", [0, 5, True, 2.5, "2000"])
def test_envelope_invalid_budget(budget):
    with pytest.raises(ValueError, match="max_points"):
        envelope(np.arange(20), budget)


def test_envelope_missing_breaks():
    values = np.ones(10000)
    values[500:502] = np.nan
    values[6000] = np.inf
    clean = np.where(np.isfinite(values), values, np.nan)
    positions = envelope(clean, 50)
    assert np.isnan(clean[positions]).sum() >= 2
    assert len(positions) <= 50
    assert len(envelope(np.full(10000, np.nan), 50)) <= 50


def test_plot_save_and_nonmutation(gui, tmp_path):
    import matplotlib.pyplot as plt

    frame = pd.DataFrame(
        {"signal": pd.array([1, None, 100, 4], dtype="Int64"), "other": [2, 4, 6, 8]},
        index=pd.date_range("2020", periods=4),
    )
    frame.attrs = {"unit_names": {"signal": "V"}, "partial_result": True}
    original = frame.copy(deep=True)
    gui.namespace = {"_": frame}
    path = tmp_path / "plot.png"
    captured = []
    with patch.object(gui, "_finish", side_effect=lambda figure, save, plt: captured.append(figure)):
        assert gui.plot(columns=["signal"], save=path) is None
    figure = captured[0]
    assert "V" in figure.axes[0].get_ylabel()
    assert "PARTIAL RESULT" in figure._suptitle.get_text()
    assert len(figure.axes[0].lines[0].get_xdata()) == 4
    plt.close(figure)
    gui.plot(save=path)
    assert path.stat().st_size > 1000
    assert not gui.has_windows
    assert gui.namespace["_"] is frame
    pd.testing.assert_frame_equal(frame, original)
    assert frame.attrs == original.attrs


def test_plot_selection_axis_and_ceiling(gui, tmp_path):
    frame = pd.DataFrame({f"s{i}": np.arange(10000, dtype=float) for i in range(10)})
    frame["text"] = "x"
    frame["boolean"] = True
    frame.index = ["label"] * len(frame)
    captured = []
    with patch.object(gui, "_finish", side_effect=lambda figure, save, plt: captured.append(figure)):
        gui.plot(frame, save=tmp_path / "plot.png", max_points=60)
    assert len(captured[0].axes) == 8
    assert all(len(axes.lines[0].get_xdata()) <= 60 for axes in captured[0].axes)
    assert any("first 8" in call.args[0] for call in gui.output.call_args_list)
    assert any("row positions" in call.args[0] for call in gui.output.call_args_list)
    gui.plot(frame, x="s0", columns=["s1"], save=tmp_path / "x.png")
    frame["time"] = pd.to_timedelta(np.arange(len(frame)), unit="s")
    gui.plot(frame, x="time", columns=["s1"], save=tmp_path / "time.png")
    frame.index = pd.TimedeltaIndex(frame["time"])
    gui.plot(frame, columns=["s1"], save=tmp_path / "index.png")


@pytest.mark.parametrize(
    "frame,kwargs,message",
    [
        (None, {}, "DataFrame"),
        (pd.DataFrame(), {}, "empty"),
        (pd.DataFrame({"text": ["a"]}), {}, "numeric"),
        (pd.DataFrame({"x": [1]}), {"columns": ["missing"]}, "Unknown"),
        (pd.DataFrame({"x": [1]}), {"columns": "x"}, "sequence"),
        (pd.DataFrame({"x": [1]}), {"columns": []}, "at least"),
        (pd.DataFrame({"x": [1]}), {"columns": ["x", "x"]}, "duplicates"),
        (pd.DataFrame({"x": ["a"], "y": [2]}), {"x": "x"}, "numeric"),
        (pd.DataFrame({"x": ["a"]}), {"columns": ["x"]}, "numeric"),
        (pd.DataFrame([[1, 2]], columns=["x", "x"]), {}, "unique"),
        (pd.DataFrame({"x": [1], "time": [np.nan]}), {"x": "time", "columns": ["x"]}, "finite"),
    ],
)
def test_invalid_plot(gui, tmp_path, frame, kwargs, message):
    with pytest.raises(ValueError, match=message):
        gui.plot(frame, save=tmp_path / "bad.png", **kwargs)


def test_backend_and_missing_extra(gui):
    frame = pd.DataFrame({"x": [1, 2]})
    with pytest.raises(ValueError, match="CLI terminal"):
        gui.plot(frame)
    gui.interactive = True
    with pytest.raises(ValueError, match="interactive matplotlib backend"):
        gui.table(frame)
    with (
        patch("matplotlib.backends.registry.backend_registry.resolve_backend", return_value=("webagg", "webagg")),
        pytest.raises(ValueError, match="desktop GUI backend"),
    ):
        gui.table(frame)
    original_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "matplotlib.pyplot":
            raise ModuleNotFoundError("missing matplotlib", name="matplotlib")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=missing), pytest.raises(ValueError, match="extra"):
        gui.plot(frame, save="unused.png")


def test_save_failure_cleans_figure(gui, tmp_path):
    import matplotlib.pyplot as plt

    frame = pd.DataFrame({"x": [1]})
    for method in (gui.plot, gui.table):
        with pytest.raises(FileNotFoundError):
            method(frame, save=tmp_path / "missing" / "plot.png")
        assert not gui.has_windows and not plt.get_fignums()


def test_gui_backend_initialization_failure(gui):
    gui.interactive = True
    with (
        patch("matplotlib.backends.registry.backend_registry.resolve_backend", return_value=("tkagg", "tk")),
        patch("matplotlib.pyplot.subplots", side_effect=ImportError("missing toolkit")),
        pytest.raises(ValueError, match="use save="),
    ):
        gui.plot(pd.DataFrame({"x": [1]}))
    assert not gui.has_windows


def test_missing_coordinates_and_literal_text(gui, tmp_path):
    frame = pd.DataFrame({"$bad_{": [1, 2, 3], "time": [0, np.inf, 2]})
    gui.plot(frame, x="time", columns=["$bad_{"], save=tmp_path / "plot.png")
    gui.table(
        pd.DataFrame({"$bad_{": ["$unclosed", r"$\nonexistentcommand$", 1.234567890123]}), save=tmp_path / "literal.png"
    )
    _, cells, _ = TablePage(pd.DataFrame({"x": [1.234567890123]}), ["x"]).content()
    assert cells[0][1] == "1.23457"


def test_save_does_not_create_gui_manager(gui, tmp_path):
    with patch("matplotlib.pyplot.subplots", side_effect=AssertionError("save created GUI manager")):
        gui.plot(pd.DataFrame({"x": [1]}), save=tmp_path / "plot.png")
        gui.table(pd.DataFrame({"x": [1]}), save=tmp_path / "table.png")


def test_table_pages_original_data_and_bounds():
    frame = pd.DataFrame({f"c{i}": range(123) for i in range(19)})
    page = TablePage(frame, list(frame.columns))
    labels, cells, caption = page.content()
    assert len(cells) == 50 and len(labels) == 9
    assert cells[0] == ["0"] * 9
    page.move(rows=1, columns=1)
    labels, cells, _ = page.content()
    assert labels[1:] == [f"c{i}" for i in range(8, 16)]
    assert cells[0][0] == "50"
    page.move(rows=100, columns=100)
    labels, cells, caption = page.content()
    assert len(cells) == 23 and len(labels) == 4
    assert "101-123 / 123" in caption and "17-19 / 19" in caption
    page.move(rows=-100, columns=-100)
    assert page.row == page.column == 0


def test_table_only_formats_visible_cells(gui, tmp_path):
    calls = []

    class Cell:
        def __str__(self):
            calls.append(1)
            return "a" * 100

    frame = pd.DataFrame({f"c{i}": [Cell()] * 10000 for i in range(20)})
    page = TablePage(frame, list(frame.columns))
    labels, cells, _ = page.content()
    assert len(calls) == 50 * 8
    assert cells[0][1].endswith("...") and len(cells[0][1]) == 40
    gui.table(pd.DataFrame({"text": ["a\nb", None, pd.NA]}), save=tmp_path / "table.png")
    assert (tmp_path / "table.png").stat().st_size > 1000
    assert not gui.has_windows


def test_managed_windows_and_table_buttons(gui):
    import matplotlib.pyplot as plt

    gui.interactive = True
    frame = pd.DataFrame({f"x{i}": range(55) for i in range(10)})
    unrelated = plt.figure()
    with (
        patch("matplotlib.backends.registry.backend_registry.resolve_backend", return_value=("tkagg", "tk")),
        patch("matplotlib.figure.Figure.show"),
    ):
        gui.table(frame)
        gui.plot(frame, columns=["x0"])
    assert len(gui._figures) == 2
    figure = gui._figures[0]
    buttons = gui._buttons[figure]
    assert not buttons[0].active and buttons[1].active and buttons[3].active
    buttons[1]._observers.process("clicked", None)
    buttons[3]._observers.process("clicked", None)
    assert buttons[0].active and not buttons[1].active
    assert "51-55" in figure.axes[0].get_title()
    assert "9-10" in figure.axes[0].get_title()
    gui.pump()
    gui.close()
    assert not gui.has_windows
    assert plt.fignum_exists(unrelated.number)
