import threading
from pathlib import Path
from types import MethodType, SimpleNamespace

from app import (
    ImageCompressorApp,
    collect_dropped_images,
    format_file_size,
    snap_value,
)
from renamer import find_jpegs


class StubVariable:
    def __init__(self, value: object) -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class StubWidget:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def configure(self, **options: object) -> None:
        self.options.update(options)


class StubTree(StubWidget):
    def __init__(self) -> None:
        super().__init__()
        self.items = ["old-preview"]

    def get_children(self) -> tuple[str, ...]:
        return tuple(self.items)

    def delete(self, item: str) -> None:
        self.items.remove(item)


def test_collect_dropped_images_accepts_folders_files_and_removes_duplicates(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "photos"
    folder.mkdir()
    heic = folder / "IMG_0001.HEIC"
    heic.write_bytes(b"test")
    (folder / "memo.txt").write_text("ignore")
    png = tmp_path / "sample.png"
    png.write_bytes(b"test")

    assert collect_dropped_images([folder, heic, png]) == [heic, png]


def test_collect_dropped_images_ignores_unsupported_files(tmp_path: Path) -> None:
    unsupported = tmp_path / "memo.txt"
    unsupported.write_text("ignore")

    assert collect_dropped_images([unsupported]) == []


def test_format_file_size_uses_mb_for_large_photos() -> None:
    assert format_file_size(2_082_653) == "1.99 MB"
    assert format_file_size(153_162) == "149.6 KB"


def test_snap_value_uses_five_point_steps_and_keeps_bounds() -> None:
    assert snap_value(22.4, 5, 5, 100) == 20
    assert snap_value(22.5, 5, 5, 100) == 25
    assert snap_value(22.6, 5, 5, 100) == 25
    assert snap_value(98.0, 5, 5, 100) == 100
    assert snap_value(27.0, 5, 30, 95) == 30


def test_turning_recursive_off_clears_nested_only_preview(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "photo.jpg"
    nested.parent.mkdir()
    nested.write_bytes(b"jpeg")
    recursive = StubVariable(False)
    cancelled_after_ids: list[str] = []
    preview_tree = StubTree()
    start_button = StubWidget()
    drop_zone = StubWidget()
    progress = StubWidget()
    preview_status = StubVariable("")
    status = StubVariable("")
    fake_app = SimpleNamespace(
        naming_plan_key="old-key",
        preview_refresh_after_id="refresh-1",
        preview_cancel_event=threading.Event(),
        preview_generation=4,
        naming_plan=["old-plan"],
        preview_items={nested: "old-preview"},
        preview_tree=preview_tree,
        start_button=start_button,
        direct_button=StubWidget(),
        target_count=StubVariable(""),
        drop_zone=drop_zone,
        progress=progress,
        preview_status=preview_status,
        status=status,
        input_dir=StubVariable(str(tmp_path)),
        rename_recursive=recursive,
        after_cancel=cancelled_after_ids.append,
        _is_rename_mode=lambda: True,
        _clear_preview_photos=lambda: None,
        _current_sources=lambda: find_jpegs(
            tmp_path, recursive=bool(recursive.get())
        ),
    )
    fake_app._available_sources = fake_app._current_sources
    fake_app._empty_rename_folder_message = MethodType(
        ImageCompressorApp._empty_rename_folder_message, fake_app
    )
    fake_app._show_empty_rename_folder = MethodType(
        ImageCompressorApp._show_empty_rename_folder, fake_app
    )

    ImageCompressorApp._naming_option_changed(fake_app)

    assert cancelled_after_ids == ["refresh-1"]
    assert fake_app.preview_refresh_after_id is None
    assert fake_app.preview_cancel_event.is_set()
    assert fake_app.preview_generation == 5
    assert fake_app.naming_plan == []
    assert fake_app.naming_plan_key is None
    assert fake_app.preview_items == {}
    assert preview_tree.items == []
    assert start_button.options["state"] == "disabled"
    assert progress.options["value"] == 0
    assert "直下にJPEGがありません" in str(preview_status.get())
    assert "子フォルダ" in str(preview_status.get())
    assert status.get() == preview_status.get()


def test_direct_conversion_cancel_does_not_start_worker(tmp_path, monkeypatch):
    from app import ConversionOptions
    source = tmp_path / "お台場.jpg"
    source.write_bytes(b"original")
    confirmations = []
    fake = SimpleNamespace(
        busy=False,
        worker=None,
        preview_items={source.resolve(): "row"},
        preview_refresh_after_id=None,
        _current_sources=lambda: [source],
        _is_rename_mode=lambda: False,
        _parse_options=lambda: ConversionOptions(),
        _confirm_direct=lambda *args: confirmations.append(args) or False,
    )
    ImageCompressorApp._start_direct(fake)
    assert fake.worker is None
    assert source.read_bytes() == b"original"
    assert confirmations[0][0] == [(f"{source.name}  ［{source.parent}］", source.name)]


def test_direct_conversion_requires_review_when_folder_contents_change(tmp_path, monkeypatch):
    selected = tmp_path / "selected.jpg"
    added_later = tmp_path / "added-later.jpg"
    refreshed = []
    notices = []
    monkeypatch.setattr("app.messagebox.showinfo", lambda *args: notices.append(args))
    fake = SimpleNamespace(
        busy=False,
        worker=None,
        preview_items={selected.resolve(): "row"},
        _current_sources=lambda: [selected, added_later],
        _refresh_preview=lambda **kwargs: refreshed.append(True),
    )
    ImageCompressorApp._start_direct(fake)
    assert refreshed == [True]
    assert notices
    assert fake.worker is None


def test_unchecking_keeps_row_and_can_restore_target(tmp_path):
    first, second = tmp_path / "first.jpg", tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    rows = {"first-row": first.resolve(), "second-row": second.resolve()}
    fake = SimpleNamespace(
        busy=False, row_paths=rows.copy(), excluded_sources=set(), unavailable_sources={},
        _available_sources=lambda: [first, second], _checks_changed=lambda: None,
    )
    ImageCompressorApp._toggle_row(fake, "first-row")
    assert ImageCompressorApp._current_sources(fake) == [second]
    assert fake.row_paths == rows
    ImageCompressorApp._toggle_row(fake, "first-row")
    assert ImageCompressorApp._current_sources(fake) == [first, second]
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_unavailable_and_busy_rows_cannot_be_checked(tmp_path):
    source = tmp_path / "photo.jpg"
    fake = SimpleNamespace(busy=False, row_paths={"row": source}, excluded_sources=set(),
                           unavailable_sources={source: "撮影日時なし"})
    ImageCompressorApp._toggle_row(fake, "row")
    assert fake.excluded_sources == set()
    fake.unavailable_sources.clear()
    fake.busy = True
    ImageCompressorApp._toggle_row(fake, "row")
    assert fake.excluded_sources == set()


def test_direct_confirmation_only_includes_checked_sources(tmp_path):
    sources = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    confirmations = []
    fake = SimpleNamespace(
        busy=False, worker=None, preview_refresh_after_id=None,
        preview_items={p: str(i) for i, p in enumerate(sources)},
        _current_sources=lambda: sources[:1], _is_rename_mode=lambda: False,
        _parse_options=lambda: __import__("app").ConversionOptions(),
        _confirm_direct=lambda *args: confirmations.append(args) or False,
    )
    ImageCompressorApp._start_direct(fake)
    assert len(confirmations[0][0]) == 1
    assert "a.jpg" in confirmations[0][0][0][0]


def test_check_all_and_clear_all_preserve_available_rows(tmp_path):
    sources = [tmp_path / "a.jpg", tmp_path / "b.jpg"]
    fake = SimpleNamespace(busy=False, preview_items=dict.fromkeys(sources),
                           excluded_sources=set(), _checks_changed=lambda: None)
    ImageCompressorApp._check_all(fake, False)
    assert fake.excluded_sources == set(sources)
    ImageCompressorApp._check_all(fake, True)
    assert fake.excluded_sources == set()
    assert list(fake.preview_items) == sources


def test_thumbnail_click_only_views_and_checkbox_click_toggles():
    toggled, selected = [], []
    fake = SimpleNamespace(preview_tree=SimpleNamespace(
        identify_row=lambda y: "row", identify_column=lambda x: "#0" if x < 82 else "#1",
        focus=lambda row: None, selection_set=selected.append,
    ), _toggle_row=toggled.append)
    assert ImageCompressorApp._click_check(fake, SimpleNamespace(x=40, y=50)) is None
    assert toggled == []
    assert ImageCompressorApp._click_check(fake, SimpleNamespace(x=110, y=50)) == "break"
    assert toggled == ["row"]
    assert selected == ["row"]


def test_photo_info_does_not_decode_pixels_or_calculate_sizes(tmp_path, monkeypatch):
    import queue
    from PIL import Image
    source = tmp_path/'photo.jpg'
    Image.new('RGB', (1200, 900)).save(source)
    def forbidden(*args, **kwargs):
        raise AssertionError('Header listing must not decode or encode image pixels')
    monkeypatch.setattr(Image.Image, 'load', forbidden)
    monkeypatch.setattr('app.preview_image', forbidden)
    fake = SimpleNamespace(events=queue.Queue())
    ImageCompressorApp._photo_info_worker(fake, 1, [source], threading.Event())
    assert fake.events.get_nowait() == ('photo_info', (1, source, (1200, 900)))


def test_focusing_unchanged_setting_does_not_restart_background_work():
    calls = []
    variable = StubVariable('20')
    slider = SimpleNamespace(get=lambda: 20, set=lambda value: None)
    fake = SimpleNamespace(_schedule_preview_refresh=lambda: calls.append(True))
    ImageCompressorApp._commit_manual_setting(fake, variable, slider, 5, 100)
    assert calls == []
    variable.set('30')
    ImageCompressorApp._commit_manual_setting(fake, variable, slider, 5, 100)
    assert calls == [True]


def test_thumbnail_loading_prioritizes_visible_rows(tmp_path, monkeypatch):
    import queue
    order = []
    monkeypatch.setattr('app.load_photo', lambda path, bounds: order.append(path) or 'bitmap')
    sources = {str(i): tmp_path/f'{i}.jpg' for i in range(500)}
    fake = SimpleNamespace(events=queue.Queue(), thumbnail_priority=('498', '499'))
    ImageCompressorApp._thumbnail_worker(fake, 1, sources, threading.Event())
    assert order[:2] == [sources['498'], sources['499']]
    assert len(order) == 500
    assert len(set(order)) == 500
