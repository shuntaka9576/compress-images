from pathlib import Path

from app import collect_dropped_images, format_file_size, snap_value


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
