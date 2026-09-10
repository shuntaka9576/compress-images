"""Exercise Windows Tk/TkDnD and real widget bindings on the CI desktop."""
import sys
import time

import pytest
from PIL import Image

from app import ImageCompressorApp, MODE_RENAME


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Tk integration")


def pump_until(app, condition, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Windows GUI did not reach the expected state")


@pytest.fixture
def gui():
    app = ImageCompressorApp()
    app.geometry("1400x1000")
    errors = []
    app.report_callback_exception = lambda *error: errors.append(error)
    app.update()
    try:
        yield app
    finally:
        app.thumbnail_cancel.set()
        app.preview_cancel_event.set()
        app.destroy()
    assert not errors, errors


def load_photos(app, tmp_path, count):
    folder = tmp_path / "写真 お台場"
    folder.mkdir()
    metadata = Image.Exif()
    metadata[36867] = "2025:10:17 11:17:00"
    first = folder / "写真 000.jpg"
    Image.new("RGB", (160, 120), "orange").save(first, exif=metadata)
    data = first.read_bytes()
    sources = [first]
    for index in range(1, count):
        source = folder / f"写真 {index:03}.jpg"
        source.write_bytes(data)
        sources.append(source)
    app.selected_sources = sources
    app.input_dir.set(str(folder))
    app.output_dir.set(str(folder / "converted"))
    app._refresh_preview()
    pump_until(app, lambda: bool(app.target_checks.buttons) and
               len(app.thumbnails) >= min(count, 2))
    return sources


def click_target(app, row):
    tree = app.preview_tree
    tree.see(row)
    app.update()
    x, y, width, height = tree.bbox(row, "checked")
    # Hit the actual overlay widget, not the application's toggle helper.
    widget = tree.winfo_containing(tree.winfo_rootx() + x + 12,
                                   tree.winfo_rooty() + y + height // 2)
    assert widget in app.target_checks.buttons
    widget.event_generate("<ButtonPress-1>", x=12, y=height // 2)
    widget.event_generate("<ButtonRelease-1>", x=12, y=height // 2)
    app.update()


def test_windows_check_click_preview_scroll_and_busy_state(gui, tmp_path):
    sources = load_photos(gui, tmp_path, 500)
    tree = gui.preview_tree
    rows = tree.get_children()
    click_target(gui, rows[0])
    assert tree.set(rows[0], "checked") == "対象外"
    assert "excluded" in tree.item(rows[0], "tags")
    assert len(gui._current_sources()) == 499
    assert len(tree.get_children()) == 500
    assert gui.photo_preview.path == sources[0].resolve()
    click_target(gui, rows[0])
    assert len(gui._current_sources()) == 500

    x, y, width, height = tree.bbox(rows[1], "#0")
    tree.event_generate("<ButtonPress-1>", x=x + 20, y=y + height // 2)
    tree.event_generate("<ButtonRelease-1>", x=x + 20, y=y + height // 2)
    gui.update()
    assert gui.photo_preview.path == sources[1].resolve()
    assert len(gui._current_sources()) == 500

    tree.yview_moveto(1)
    gui.update()
    click_target(gui, rows[-1])
    assert sources[-1].resolve() in gui.excluded_sources
    assert len(gui.target_checks.buttons) <= tree.winfo_height() // 66 + 2
    click_target(gui, rows[-1])
    gui._set_busy(True)
    gui.update()
    click_target(gui, rows[-1])
    assert len(gui._current_sources()) == 500
    gui._set_busy(False)
    assert all(source.exists() for source in sources)


def test_windows_unavailable_photo_and_native_help(gui, tmp_path):
    sources = load_photos(gui, tmp_path, 2)
    Image.new("RGB", (160, 120), "blue").save(sources[1])
    gui.operation_mode.set(MODE_RENAME)
    gui._refresh_preview()
    pump_until(gui, lambda: sources[1].resolve() in gui.unavailable_sources)
    row = gui.preview_items[sources[1].resolve()]
    click_target(gui, row)
    assert gui.preview_tree.set(row, "checked") == "選択不可"
    assert len(gui._current_sources()) == 1
    gui._show_help()
    gui.update()
    assert gui.help_window.winfo_exists()
    assert len(gui.help_window.notebook.tabs()) == 4
    gui.help_window.destroy()
