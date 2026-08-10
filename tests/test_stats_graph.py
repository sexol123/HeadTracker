import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication

from ui.stats_graph import StatsGraph, WINDOW_SEC
from ui.main_window import MainWindow
from i18n import t

app = QApplication([])


def _make_graph(now=1000.0):
    g = StatsGraph()
    g._clock = lambda: now
    return g


def test_samples_and_trimming():
    g = _make_graph()
    for i in range(40):
        g._clock = lambda i=i: 1000.0 + i * 0.2
        g.add_sample(30.0, 33.3, 8.0)
    assert g.sample_count() == 40  # 8 s of history fits the 10 s window
    # Advance clock past the window -> old samples trimmed
    g._clock = lambda: 1000.0 + 40 * 0.2 + WINDOW_SEC + 0.01
    g.add_sample(30.0, 33.3, 8.0)
    assert g.sample_count() < 40
    assert g.sample_count() > 0
    print("PASS: samples buffered and trimmed to the 10 s window")


def test_markers_and_clear():
    g = _make_graph()
    g.add_marker("start")
    g.add_marker("reconnect")
    g.add_sample(30.0, 33.3, 8.0)
    assert len(g._markers) == 2
    g.clear()
    assert g.sample_count() == 0
    assert g._markers == []
    assert g._max_fps == 0.0
    print("PASS: markers recorded, clear() resets everything")


def test_paint_does_not_crash():
    g = _make_graph()
    g.resize(320, 140)
    g.add_sample(30.0, 33.3, 8.0)
    g.add_sample(29.0, 34.0, 9.0)
    g.add_marker("start")
    from PySide6.QtGui import QPixmap
    pix = QPixmap(320, 140)
    g.render(pix)
    assert not pix.isNull()
    g.clear()
    g.render(pix)
    print("PASS: graph renders with and without data")


def test_ui_integration():
    win = MainWindow(Profile())
    assert isinstance(win.stats_graph, StatsGraph)
    win._on_worker_stats((30.0, 33.3, 8.0))
    win._on_worker_stats((29.0, 34.0, 9.0))
    assert win.stats_graph.sample_count() == 2
    win._on_worker_event_marker("reconnect")
    assert len(win.stats_graph._markers) == 1
    win._stop_tracking()
    assert win.stats_graph.sample_count() == 0
    assert win.stats_graph._markers == []
    print("PASS: main window routes stats/events into the graph, stop clears it")


def test_ui_title_i18n():
    win = MainWindow(Profile())
    assert win._perf_graph_title.text() == t("perf_graph")
    print("PASS: performance graph title localized")


from config import Profile  # noqa: E402

if __name__ == "__main__":
    test_samples_and_trimming()
    test_markers_and_clear()
    test_paint_does_not_crash()
    test_ui_integration()
    test_ui_title_i18n()
    print("STATS GRAPH TESTS PASSED")
