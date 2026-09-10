import os
from pathlib import Path

import pytest
from PIL import Image

import compressor
from compressor import ConversionOptions, compress_image, compress_many
from renamer import build_naming_plan, copy_many


def photo(path: Path, *, exif: bool = True) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = Image.Exif()
    if exif:
        metadata[36867] = "2025:10:17 11:17:00"
    Image.new("RGB", (100, 80), "orange").save(path, exif=metadata)
    return path.read_bytes()


def test_jpeg_overwrite_preserves_filename_timestamp_and_unselected_photo(tmp_path):
    selected = tmp_path / "お台場.JPEG"
    photo(selected)
    os.utime(selected, (1000000000, 1000000000))
    unselected = tmp_path / "渋谷.jpg"
    original = photo(unselected)
    result = compress_image(selected, tmp_path / "ignored", ConversionOptions(), in_place=True)
    assert result.destination == selected
    assert selected.stat().st_mtime == 1000000000
    assert unselected.read_bytes() == original
    assert not (tmp_path / "ignored").exists()
    with Image.open(selected) as image:
        assert image.size == (20, 16)
        assert not image.getexif()


def test_non_jpeg_is_replaced_only_after_jpeg_saved(tmp_path):
    source = tmp_path / "お台場.png"
    photo(source)
    result = compress_image(source, tmp_path / "converted", ConversionOptions(), in_place=True)
    assert not source.exists()
    assert result.destination == tmp_path / "お台場.jpg"
    with Image.open(result.destination) as image:
        assert image.format == "JPEG"
        assert image.size == (20, 16)
    assert not (tmp_path / "converted").exists()


def test_collision_leaves_both_original_files_unchanged(tmp_path):
    source = tmp_path / "photo.png"
    original = photo(source)
    existing = tmp_path / "photo.jpg"
    existing_bytes = photo(existing)
    with pytest.raises(FileExistsError):
        compress_image(source, tmp_path, ConversionOptions(), in_place=True)
    assert source.read_bytes() == original
    assert existing.read_bytes() == existing_bytes


def test_late_collision_does_not_overwrite_destination(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    original = photo(source)
    destination = source.with_suffix(".jpg")
    prepare = compressor._prepare_image

    def competing_writer(*args):
        result = prepare(*args)
        destination.write_bytes(b"another photo")
        return result

    monkeypatch.setattr(compressor, "_prepare_image", competing_writer)
    with pytest.raises(FileExistsError):
        compress_image(source, tmp_path, ConversionOptions(), in_place=True)
    assert source.read_bytes() == original
    assert destination.read_bytes() == b"another photo"
    assert len(list(tmp_path.iterdir())) == 2


def test_failed_jpeg_replace_keeps_original_and_cleans_temporary(tmp_path, monkeypatch):
    source = tmp_path / "photo.jpg"
    original = photo(source)

    def fail(*_args):
        raise OSError("disk failure")

    monkeypatch.setattr(compressor.os, "replace", fail)
    with pytest.raises(OSError):
        compress_image(source, tmp_path, ConversionOptions(), in_place=True)
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


def test_failed_exclusive_write_removes_only_partial_output(tmp_path, monkeypatch):
    import shutil
    source = tmp_path / "photo.png"
    original = photo(source)

    def fail(_source, destination):
        destination.write(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfileobj", fail)
    with pytest.raises(OSError):
        compress_image(source, tmp_path, ConversionOptions(), in_place=True)
    assert source.read_bytes() == original
    assert list(tmp_path.iterdir()) == [source]


def test_cancel_stops_before_next_original_is_changed(tmp_path):
    sources = [tmp_path / f"{number}.jpg" for number in range(3)]
    originals = [photo(source) for source in sources]
    completed = []
    results, errors = compress_many(sources, tmp_path, ConversionOptions(),
        on_result=completed.append, should_cancel=lambda: bool(completed), in_place=True)
    assert len(results) == 1
    assert not errors
    assert [p.read_bytes() for p in sources[1:]] == originals[1:]


def test_direct_rename_preserves_bytes_exif_and_folder(tmp_path):
    sources = [tmp_path / "2025" / "photo.jpg", tmp_path / "2026" / "photo.jpg"]
    originals = [photo(source) for source in sources]
    plan = build_naming_plan(sources, tmp_path / "ignored", in_place=True)
    results, errors = copy_many(plan, in_place=True)
    assert not errors
    assert len(results) == 2
    for result, original in zip(results, originals):
        assert not result.source.exists()
        assert result.destination.parent == result.source.parent
        assert result.destination.read_bytes() == original
    assert not (tmp_path / "ignored").exists()


def test_direct_rename_is_noop_for_existing_correct_name(tmp_path):
    source = tmp_path / "2025_10_17_1117_00.jpg"
    original = photo(source)
    plan = build_naming_plan([source], tmp_path, in_place=True)
    assert plan[0].destination == source
    results, errors = copy_many(plan, in_place=True)
    assert len(results) == 1
    assert not errors
    assert source.read_bytes() == original


def test_rename_collision_after_confirmation_preserves_both_files(tmp_path):
    source = tmp_path / "photo.jpg"
    original = photo(source)
    plan = build_naming_plan([source], tmp_path, in_place=True)
    destination = plan[0].destination
    destination.write_bytes(b"another photo")
    results, errors = copy_many(plan, in_place=True)
    assert not results
    assert len(errors) == 1
    assert source.read_bytes() == original
    assert destination.read_bytes() == b"another photo"


def test_rename_skips_missing_exif_and_avoids_existing_name(tmp_path):
    selected = tmp_path / "photo.jpg"
    photo(selected)
    existing = tmp_path / "2025_10_17_1117_00.jpg"
    original = photo(existing)
    missing_exif = tmp_path / "no-exif.jpg"
    missing_original = photo(missing_exif, exif=False)
    plan = build_naming_plan([selected, missing_exif], tmp_path, in_place=True)
    results, errors = copy_many(plan, in_place=True)
    assert not errors
    assert len(results) == 1
    assert results[0].destination.name == "2025_10_17_1117_01.jpg"
    assert existing.read_bytes() == original
    assert missing_exif.read_bytes() == missing_original


def test_failed_rename_copy_keeps_source(tmp_path, monkeypatch):
    import shutil
    source = tmp_path / "photo.jpg"
    original = photo(source)
    plan = build_naming_plan([source], tmp_path, in_place=True)

    def fail(*args):
        raise OSError("write failed")

    monkeypatch.setattr(shutil, "copyfileobj", fail)
    results, errors = copy_many(plan, in_place=True)
    assert not results
    assert len(errors) == 1
    assert source.read_bytes() == original
    assert not plan[0].destination.exists()
