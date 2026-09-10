from __future__ import annotations

import io
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener


register_heif_opener(thumbnails=False)

SUPPORTED_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class ConversionOptions:
    scale_percent: int = 20
    jpeg_quality: int = 80
    target_kb: int | None = None
    minimum_quality: int = 25

    def validate(self) -> None:
        if not 1 <= self.scale_percent <= 100:
            raise ValueError("縮小率は1～100%で指定してください。")
        if not 1 <= self.jpeg_quality <= 95:
            raise ValueError("JPEG品質は1～95で指定してください。")
        if not 1 <= self.minimum_quality <= self.jpeg_quality:
            raise ValueError("最低品質は1～JPEG品質の範囲で指定してください。")
        if self.target_kb is not None and self.target_kb < 10:
            raise ValueError("目標サイズは10KB以上で指定してください。")


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    destination: Path
    original_size: tuple[int, int]
    output_size: tuple[int, int]
    output_bytes: int
    quality: int


@dataclass(frozen=True)
class PreviewResult:
    source: Path
    original_size: tuple[int, int]
    input_bytes: int
    output_size: tuple[int, int]
    output_bytes: int
    quality: int


@dataclass(frozen=True)
class _PreparedImage:
    original_size: tuple[int, int]
    output_size: tuple[int, int]
    data: bytes
    quality: int


def find_images(input_dir: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda path: path.name.casefold(),
    )


def scaled_size(size: tuple[int, int], scale_percent: int) -> tuple[int, int]:
    width, height = size
    ratio = scale_percent / 100
    return max(1, math.ceil(width * ratio)), max(1, math.ceil(height * ratio))


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _encode_jpeg(
    image: Image.Image,
    quality: int,
    icc_profile: bytes | None,
) -> bytes:
    output = io.BytesIO()
    save_options: dict[str, object] = {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
        "progressive": True,
    }
    if icc_profile:
        save_options["icc_profile"] = icc_profile
    image.save(output, **save_options)
    return output.getvalue()


def _encode_for_target(
    image: Image.Image,
    target_bytes: int,
    maximum_quality: int,
    minimum_quality: int,
    icc_profile: bytes | None,
) -> tuple[bytes, int, Image.Image]:
    current = image

    # 最低品質でも収まらない写真は、少しずつ寸法を縮めて目標内に収める。
    for _ in range(12):
        minimum_data = _encode_jpeg(current, minimum_quality, icc_profile)
        if len(minimum_data) <= target_bytes:
            low, high = minimum_quality, maximum_quality
            best_data, best_quality = minimum_data, minimum_quality
            while low <= high:
                quality = (low + high) // 2
                data = _encode_jpeg(current, quality, icc_profile)
                if len(data) <= target_bytes:
                    best_data, best_quality = data, quality
                    low = quality + 1
                else:
                    high = quality - 1
            return best_data, best_quality, current

        next_size = (
            max(1, math.floor(current.width * 0.9)),
            max(1, math.floor(current.height * 0.9)),
        )
        if next_size == current.size:
            return minimum_data, minimum_quality, current
        current = current.resize(next_size, Image.Resampling.LANCZOS)

    data = _encode_jpeg(current, minimum_quality, icc_profile)
    return data, minimum_quality, current


def _available_destination(output_dir: Path, stem: str) -> Path:
    candidate = output_dir / f"{stem}.jpg"
    number = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}_{number}.jpg"
        number += 1
    return candidate


def _prepare_image(source: Path, options: ConversionOptions) -> _PreparedImage:
    options.validate()
    with Image.open(source) as opened:
        original_size = opened.size
        icc_profile = opened.info.get("icc_profile")
        # Compute the exact target before draft() changes the decoder dimensions.
        # Reducing before EXIF rotation avoids copying a full-size phone image.
        target_size = scaled_size(original_size, options.scale_percent)
        opened.draft("RGB", target_size)
        image = opened.resize(target_size, Image.Resampling.LANCZOS)
        ImageOps.exif_transpose(image, in_place=True)
        image = _to_rgb(image)

        if options.target_kb is None:
            quality = options.jpeg_quality
            data = _encode_jpeg(image, quality, icc_profile)
            output_size = image.size
        else:
            data, quality, encoded_image = _encode_for_target(
                image=image,
                target_bytes=options.target_kb * 1024,
                maximum_quality=options.jpeg_quality,
                minimum_quality=options.minimum_quality,
                icc_profile=icc_profile,
            )
            output_size = encoded_image.size

    return _PreparedImage(
        original_size=original_size,
        output_size=output_size,
        data=data,
        quality=quality,
    )


def preview_image(source: Path, options: ConversionOptions) -> PreviewResult:
    prepared = _prepare_image(source, options)
    return PreviewResult(
        source=source,
        original_size=prepared.original_size,
        input_bytes=source.stat().st_size,
        output_size=prepared.output_size,
        output_bytes=len(prepared.data),
        quality=prepared.quality,
    )


def compress_image(
    source: Path,
    output_dir: Path,
    options: ConversionOptions,
    *,
    in_place: bool = False,
) -> ConversionResult:
    if in_place and source.is_symlink():
        raise ValueError("リンクされた写真は上書きできません。")
    destination = in_place_destination(source) if in_place else None
    if in_place and destination != source and destination.exists():
        raise FileExistsError(f"同名のJPEGがあるため変更しません: {destination.name}")
    source_stat = source.stat()
    prepared = _prepare_image(source, options)
    if in_place:
        output_dir = source.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = destination or _available_destination(output_dir, source.stem)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".jpg", dir=output_dir, delete=False
        ) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(prepared.data)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.utime(temp_path, (source_stat.st_atime, source_stat.st_mtime))
        if in_place and destination != source:
            # 排他的に保存するため、確認後に同名ファイルが増えても上書きしない。
            publish_exclusive(temp_path, destination)
            source.unlink()
        else:
            os.replace(temp_path, destination)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()

    return ConversionResult(
        source=source,
        destination=destination,
        original_size=prepared.original_size,
        output_size=prepared.output_size,
        output_bytes=len(prepared.data),
        quality=prepared.quality,
    )


def in_place_destination(source: Path) -> Path:
    """JPEGは拡張子も維持し、他形式だけ同じ場所の.jpgへ置き換える。"""
    return source if source.suffix.lower() in {".jpg", ".jpeg"} else source.with_suffix(".jpg")


def publish_exclusive(source: Path, destination: Path) -> None:
    """既存ファイルを上書きせずコピーする。失敗時は未完成の出力だけ消す。"""
    import shutil

    created = False
    try:
        with destination.open("xb") as output:
            created = True
            with source.open("rb") as original:
                shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(source, destination)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def compress_many(
    sources: Iterable[Path],
    output_dir: Path,
    options: ConversionOptions,
    on_result: Callable[[ConversionResult], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    *,
    in_place: bool = False,
) -> tuple[list[ConversionResult], list[tuple[Path, Exception]]]:
    results: list[ConversionResult] = []
    errors: list[tuple[Path, Exception]] = []
    for source in sources:
        if should_cancel and should_cancel():
            break
        try:
            result = compress_image(source, output_dir, options, in_place=in_place)
            results.append(result)
            if on_result:
                on_result(result)
        except Exception as error:  # ファイル単位で継続し、最後にまとめて表示する。
            errors.append((source, error))
    return results, errors
