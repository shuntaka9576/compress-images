from pathlib import Path

from PIL import Image

from compressor import (
    ConversionOptions,
    compress_image,
    find_images,
    preview_image,
    scaled_size,
)


def test_scaled_size_rounds_up_like_windows_photos() -> None:
    assert scaled_size((3024, 4032), 20) == (605, 807)


def test_scaled_size_preserves_aspect_ratio_without_stretching() -> None:
    for original in ((3024, 4032), (4032, 3024), (4000, 2250), (2250, 4000)):
        resized = scaled_size(original, 20)

        # 端数を整数ピクセルへ丸める分（1px未満）以外は、元の比率を変えない。
        width_scale = resized[0] / original[0]
        height_scale = resized[1] / original[1]
        assert abs(width_scale - height_scale) < 1 / min(original)


def test_defaults_match_the_manual_windows_photos_settings() -> None:
    options = ConversionOptions()

    assert options.scale_percent == 20
    assert options.jpeg_quality == 80
    assert options.target_kb is None


def test_fixed_quality_conversion(tmp_path: Path) -> None:
    source = tmp_path / "photo.png"
    output = tmp_path / "converted"
    Image.new("RGB", (3024, 4032), "#3a7c54").save(source)

    result = compress_image(
        source,
        output,
        ConversionOptions(scale_percent=20, jpeg_quality=80, target_kb=None),
    )

    assert result.destination.exists()
    assert result.output_size == (605, 807)
    assert result.quality == 80
    with Image.open(result.destination) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (605, 807)


def test_preview_matches_conversion_without_writing_output(tmp_path: Path) -> None:
    source = tmp_path / "photo.png"
    output = tmp_path / "converted"
    Image.effect_noise((1200, 1600), 80).convert("RGB").save(source)
    options = ConversionOptions(scale_percent=20, jpeg_quality=80, target_kb=150)

    preview = preview_image(source, options)
    assert not output.exists()
    result = compress_image(source, output, options)

    assert preview.original_size == result.original_size
    assert preview.output_size == result.output_size
    assert preview.output_bytes == result.output_bytes
    assert preview.quality == result.quality


def test_target_size_conversion(tmp_path: Path) -> None:
    source = tmp_path / "noise.png"
    output = tmp_path / "converted"
    noise = Image.effect_noise((1600, 1200), 100).convert("RGB")
    noise.save(source)

    result = compress_image(
        source,
        output,
        ConversionOptions(scale_percent=50, jpeg_quality=90, target_kb=50),
    )

    assert result.output_bytes <= 50 * 1024
    assert 25 <= result.quality <= 90


def test_heic_to_jpeg_conversion(tmp_path: Path) -> None:
    source = tmp_path / "IMG_0879.HEIC"
    output = tmp_path / "converted"
    Image.new("RGB", (3024, 4032), "#5d8062").save(source, format="HEIF", quality=80)

    result = compress_image(source, output, ConversionOptions())

    assert result.destination.suffix == ".jpg"
    assert result.output_size == (605, 807)
    assert result.output_bytes <= 150 * 1024
    with Image.open(result.destination) as converted:
        assert converted.format == "JPEG"


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "photo.png"
    output = tmp_path / "converted"
    Image.new("RGB", (100, 100), "red").save(source)

    first = compress_image(source, output, ConversionOptions(target_kb=None))
    second = compress_image(source, output, ConversionOptions(target_kb=None))

    assert first.destination.name == "photo.jpg"
    assert second.destination.name == "photo_2.jpg"


def test_find_images_ignores_unrelated_files(tmp_path: Path) -> None:
    for name in ["b.HEIC", "a.jpg", "memo.txt"]:
        (tmp_path / name).write_bytes(b"test")

    assert [path.name for path in find_images(tmp_path)] == ["a.jpg", "b.HEIC"]
