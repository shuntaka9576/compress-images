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
        drop_zone=drop_zone,
        progress=progress,
        preview_status=preview_status,
        status=status,
        input_dir=StubVariable(str(tmp_path)),
        rename_recursive=recursive,
        after_cancel=cancelled_after_ids.append,
        _is_rename_mode=lambda: True,
        _current_sources=lambda: find_jpegs(
            tmp_path, recursive=bool(recursive.get())
        ),
    )
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
