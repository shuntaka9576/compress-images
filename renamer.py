from __future__ import annotations

import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from PIL import Image, UnidentifiedImageError


JPEG_EXTENSIONS = {".jpg", ".jpeg"}
COMPONENT_DATETIME = "datetime"  # 旧GUI内部形式との互換用
COMPONENT_DATE = "date"
COMPONENT_TIME = "time"
COMPONENT_SEQUENCE = "sequence"
COMPONENT_MAKE = "make"
COMPONENT_MODEL = "model"
COMPONENT_CUSTOM = "custom"
DEFAULT_COMPONENTS = (COMPONENT_DATE, COMPONENT_TIME, COMPONENT_SEQUENCE)
DATE_FORMAT_V4 = "yyyy_mm_dd"
DATE_FORMAT_COMPACT = "yyyymmdd"
DATE_FORMAT_HYPHEN = "yyyy-mm-dd"
DATE_FORMAT_JAPANESE = "yyyy年mm月dd日"

_DATE_TIME = 306
_MAKE = 271
_MODEL = 272
_EXIF_IFD = 34665
_DATE_TIME_ORIGINAL = 36867
_DATE_TIME_DIGITIZED = 36868


@dataclass(frozen=True)
class ExifInfo:
    taken_at: datetime
    make: str = ""
    model: str = ""


@dataclass(frozen=True)
class NamingPlanItem:
    source: Path
    destination: Path | None
    status: str
    exif: ExifInfo | None = None

    @property
    def new_name(self) -> str:
        return self.destination.name if self.destination is not None else "-"


@dataclass(frozen=True)
class CopyResult:
    source: Path
    destination: Path
    output_bytes: int


def find_jpegs(
    input_dir: Path,
    recursive: bool = False,
    excluded_dirs: Iterable[Path] = (),
) -> list[Path]:
    """対象フォルダからJPEGを集める。出力先などは走査対象から除外できる。"""
    excluded = {path.resolve() for path in excluded_dirs}
    candidates = input_dir.rglob("*") if recursive else input_dir.iterdir()
    files: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if any(parent == resolved or parent in resolved.parents for parent in excluded):
            continue
        if path.is_file() and path.suffix.lower() in JPEG_EXTENSIONS:
            files.append(path)
    return sorted(files, key=lambda path: str(path).casefold())


def _clean_exif_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip().strip("\x00").strip()


def _exif_value(exif: Image.Exif, tag: int) -> object | None:
    value = exif.get(tag)
    if value is not None:
        return value
    try:
        nested = exif.get_ifd(_EXIF_IFD)
    except (KeyError, TypeError, ValueError):
        return None
    return nested.get(tag)


def read_exif_info(path: Path) -> ExifInfo:
    """Jpegrm V4と同じ優先順位で撮影日時・メーカー・機種名を読む。"""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("JPEGを読み込めません") from error

    if not exif:
        raise ValueError("EXIF情報がありません")

    taken_at: datetime | None = None
    for tag in (_DATE_TIME_ORIGINAL, _DATE_TIME_DIGITIZED, _DATE_TIME):
        raw = _clean_exif_text(_exif_value(exif, tag))
        if not raw:
            continue
        try:
            taken_at = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
            break
        except ValueError:
            continue
    if taken_at is None:
        raise ValueError("EXIF撮影日時がありません")

    return ExifInfo(
        taken_at=taken_at,
        make=_clean_exif_text(_exif_value(exif, _MAKE)),
        model=_clean_exif_text(_exif_value(exif, _MODEL)),
    )


def sanitize_suffix(value: str) -> str:
    """Jpegrm V4互換で、ファイル名に安全なサフィックスへ整える。"""
    cleaned: list[str] = []
    for character in value.replace(" ", "-"):
        category = unicodedata.category(character)
        if (
            character in {"-", "_"}
            or category.startswith("L")
            or category == "Nd"
            or category.startswith("M")
        ):
            cleaned.append(character)
    return "".join(cleaned)


def resolve_suffix(template: str, info: ExifInfo) -> str:
    return sanitize_suffix(
        template.replace("%make", info.make).replace("%model", info.model)
    )


def _component_value(
    component: str,
    info: ExifInfo,
    sequence_number: int,
    custom_text: str,
    date_format: str,
) -> str:
    if component == COMPONENT_DATETIME:
        return info.taken_at.strftime("%Y_%m_%d_%H%M")
    if component == COMPONENT_DATE:
        formats = {
            DATE_FORMAT_V4: "%Y_%m_%d",
            DATE_FORMAT_COMPACT: "%Y%m%d",
            DATE_FORMAT_HYPHEN: "%Y-%m-%d",
            DATE_FORMAT_JAPANESE: "%Y年%m月%d日",
        }
        try:
            return info.taken_at.strftime(formats[date_format])
        except KeyError as error:
            raise ValueError(f"未対応の日付形式です: {date_format}") from error
    if component == COMPONENT_TIME:
        return info.taken_at.strftime("%H%M")
    if component == COMPONENT_SEQUENCE:
        return f"{sequence_number:02d}"
    if component == COMPONENT_MAKE:
        return sanitize_suffix(info.make)
    if component == COMPONENT_MODEL:
        return sanitize_suffix(info.model)
    if component == COMPONENT_CUSTOM:
        return sanitize_suffix(custom_text)
    raise ValueError(f"未対応のファイル名部品です: {component}")


def render_filename(
    info: ExifInfo,
    sequence_number: int,
    components: Sequence[str] = DEFAULT_COMPONENTS,
    custom_text: str = "",
    date_format: str = DATE_FORMAT_V4,
) -> str:
    """GUIで並べた部品から、空のEXIF値を除いてJPEG名を組み立てる。"""
    values = [
        _component_value(
            component,
            info,
            sequence_number,
            custom_text,
            date_format,
        )
        for component in components
    ]
    stem = "_".join(value for value in values if value)
    if not stem:
        raise ValueError("ファイル名に使える項目がありません")
    return f"{stem}.jpg"


def _destination_directory(
    source: Path,
    output_root: Path,
    source_root: Path | None,
    preserve_tree: bool,
) -> Path:
    if not preserve_tree or source_root is None:
        return output_root
    try:
        relative_parent = source.resolve().parent.relative_to(source_root.resolve())
    except ValueError:
        return output_root
    return output_root / relative_parent


def _path_key(path: Path) -> str:
    # Windowsはファイル名の大文字小文字を区別しない。Mac/Linuxでのプレビューも
    # Windowsと同じ安全側の衝突判定にそろえる。
    return str(path.absolute()).casefold()


def build_naming_plan(
    sources: Iterable[Path],
    output_root: Path,
    suffix_template: str = "",
    *,
    source_root: Path | None = None,
    preserve_tree: bool = False,
    filename_components: Sequence[str] | None = None,
    custom_text: str = "",
    date_format: str = DATE_FORMAT_V4,
    should_cancel: Callable[[], bool] | None = None,
) -> list[NamingPlanItem]:
    """EXIF名で安全にコピーする計画を作る。プレビュー時点では書き込まない。"""
    if (
        filename_components is not None
        and COMPONENT_SEQUENCE not in filename_components
    ):
        raise ValueError("連番はファイル名に必須です")
    plan: list[NamingPlanItem] = []
    next_numbers: dict[tuple[object, ...], int] = {}
    reserved: set[str] = set()

    for source in sorted(sources, key=lambda path: str(path).casefold()):
        if should_cancel and should_cancel():
            break
        try:
            info = read_exif_info(source)
        except ValueError as error:
            plan.append(
                NamingPlanItem(
                    source=source,
                    destination=None,
                    status=f"スキップ：{error}",
                )
            )
            continue

        destination_dir = _destination_directory(
            source, output_root, source_root, preserve_tree
        )
        base = info.taken_at.strftime("%Y_%m_%d_%H%M")
        suffix = resolve_suffix(suffix_template, info)
        if filename_components is None:
            # V4と同じく、再帰時もフォルダをまたいで同一時分・同一サフィックスの
            # 連番を進める。保存先には元のフォルダ構成を保つ。
            counter_key: tuple[object, ...] = (base, suffix)
        else:
            resolved_without_sequence = tuple(
                (
                    component,
                    _component_value(
                        component,
                        info,
                        0,
                        custom_text,
                        date_format,
                    ),
                )
                for component in filename_components
                if component != COMPONENT_SEQUENCE
            )
            counter_key = (tuple(filename_components), resolved_without_sequence)
        number = next_numbers.get(counter_key, 0)

        while True:
            if filename_components is not None:
                filename = render_filename(
                    info,
                    number,
                    filename_components,
                    custom_text,
                    date_format,
                )
            elif suffix:
                filename = f"{base}_{number:02d}_{suffix}.jpg"
            else:
                filename = f"{base}_{number:02d}.jpg"
            destination = destination_dir / filename
            destination_key = _path_key(destination)
            if destination_key not in reserved and not destination.exists():
                break
            number += 1

        next_numbers[counter_key] = number + 1
        reserved.add(destination_key)
        plan.append(
            NamingPlanItem(
                source=source,
                destination=destination,
                status="コピー予定",
                exif=info,
            )
        )

    return plan


def copy_planned_file(item: NamingPlanItem) -> CopyResult:
    if item.destination is None:
        raise ValueError("スキップ対象はコピーできません")

    destination = item.destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"同名ファイルが作成されています: {destination.name}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=".jpegrm-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        shutil.copy2(item.source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    return CopyResult(
        source=item.source,
        destination=destination,
        output_bytes=destination.stat().st_size,
    )


def copy_many(
    plan: Iterable[NamingPlanItem],
    on_result: Callable[[CopyResult], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[list[CopyResult], list[tuple[Path, Exception]]]:
    results: list[CopyResult] = []
    errors: list[tuple[Path, Exception]] = []
    for item in plan:
        if item.destination is None:
            continue
        if should_cancel and should_cancel():
            break
        try:
            result = copy_planned_file(item)
            results.append(result)
            if on_result:
                on_result(result)
        except Exception as error:  # ファイル単位で続行し、最後にまとめて表示する。
            errors.append((item.source, error))
    return results, errors
