from datetime import datetime
from pathlib import Path

from PIL import Image

from renamer import (
    COMPONENT_CUSTOM,
    COMPONENT_DATE,
    COMPONENT_DATETIME,
    COMPONENT_MAKE,
    COMPONENT_MODEL,
    COMPONENT_SEQUENCE,
    COMPONENT_TIME,
    DATE_FORMAT_COMPACT,
    DATE_FORMAT_HYPHEN,
    DATE_FORMAT_JAPANESE,
    DATE_FORMAT_V4,
    ExifInfo,
    build_naming_plan,
    copy_many,
    find_jpegs,
    read_exif_info,
    render_filename,
    resolve_suffix,
    sanitize_suffix,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "Jpegrm-GUI-test-data"


def create_jpeg(
    path: Path,
    *,
    taken_at: str | None = "2025:10:17 11:17:00",
    make: str = "SONY",
    model: str = "ZV-E10M2",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if taken_at is not None:
        exif[36867] = taken_at
    if make:
        exif[271] = make
    if model:
        exif[272] = model
    Image.new("RGB", (32, 24), "#5281a8").save(path, "JPEG", exif=exif)


def test_read_exif_info_reads_date_make_and_model(tmp_path: Path) -> None:
    source = tmp_path / "IMG_0001.JPG"
    create_jpeg(source, make="Canon", model="EOS R5")

    info = read_exif_info(source)

    assert info.taken_at == datetime(2025, 10, 17, 11, 17)
    assert info.make == "Canon"
    assert info.model == "EOS R5"


def test_suffix_is_v4_compatible_and_accepts_japanese() -> None:
    info = ExifInfo(
        taken_at=datetime(2025, 10, 17, 11, 17),
        make="SONY",
        model="ZV E10M2",
    )

    assert sanitize_suffix(' 横浜中華街 山下公園<>:"/\\|?*! ') == (
        "-横浜中華街-山下公園-"
    )
    assert resolve_suffix("%make_%model", info) == "SONY_ZV-E10M2"


def test_filename_builder_default_matches_v4() -> None:
    info = ExifInfo(
        taken_at=datetime(2025, 10, 17, 11, 17),
        make="SONY",
        model="ZV-E10M2",
    )

    assert render_filename(info, 0) == "2025_10_17_1117_00.jpg"


def test_filename_builder_supports_date_formats_and_component_order() -> None:
    info = ExifInfo(
        taken_at=datetime(2025, 10, 17, 11, 17),
        make="SONY",
        model="ZV-E10M2",
    )
    components = (
        COMPONENT_CUSTOM,
        COMPONENT_DATE,
        COMPONENT_MAKE,
        COMPONENT_MODEL,
        COMPONENT_TIME,
        COMPONENT_SEQUENCE,
    )

    expected_dates = {
        DATE_FORMAT_V4: "2025_10_17",
        DATE_FORMAT_COMPACT: "20251017",
        DATE_FORMAT_HYPHEN: "2025-10-17",
        DATE_FORMAT_JAPANESE: "2025年10月17日",
    }
    for date_format, expected_date in expected_dates.items():
        assert render_filename(
            info,
            3,
            components,
            "横浜中華街山下公園",
            date_format,
        ) == (
            f"横浜中華街山下公園_{expected_date}_SONY_ZV-E10M2_1117_03.jpg"
        )


def test_build_plan_shows_free_text_name_and_sequence(tmp_path: Path) -> None:
    first = tmp_path / "IMG_0001.jpg"
    second = tmp_path / "IMG_0002.jpg"
    create_jpeg(first)
    create_jpeg(second)

    plan = build_naming_plan(
        [second, first],
        tmp_path / "converted",
        "横浜中華街山下公園",
    )

    assert [item.new_name for item in plan] == [
        "2025_10_17_1117_00_横浜中華街山下公園.jpg",
        "2025_10_17_1117_01_横浜中華街山下公園.jpg",
    ]


def test_build_plan_avoids_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "IMG_0001.jpg"
    create_jpeg(source)
    output = tmp_path / "converted"
    output.mkdir()
    (output / "2025_10_17_1117_00.jpg").write_bytes(b"existing")

    plan = build_naming_plan([source], output)

    assert plan[0].new_name == "2025_10_17_1117_01.jpg"


def test_missing_date_is_shown_as_skipped(tmp_path: Path) -> None:
    source = tmp_path / "no-date.jpg"
    create_jpeg(source, taken_at=None)

    plan = build_naming_plan([source], tmp_path / "converted")

    assert plan[0].destination is None
    assert plan[0].status == "スキップ：EXIF撮影日時がありません"


def test_recursive_plan_preserves_subfolder_tree(tmp_path: Path) -> None:
    source_root = tmp_path / "photos"
    source = source_root / "trip" / "IMG_0001.jpg"
    create_jpeg(source)
    output = source_root / "converted"

    sources = find_jpegs(source_root, recursive=True, excluded_dirs=[output])
    plan = build_naming_plan(
        sources,
        output,
        source_root=source_root,
        preserve_tree=True,
    )

    assert plan[0].destination == output / "trip" / "2025_10_17_1117_00.jpg"


def test_recursive_search_excludes_converted_folder(tmp_path: Path) -> None:
    source = tmp_path / "trip" / "IMG_0001.jpg"
    converted = tmp_path / "converted"
    already_copied = converted / "old.jpg"
    create_jpeg(source)
    create_jpeg(already_copied)

    assert find_jpegs(tmp_path, recursive=True, excluded_dirs=[converted]) == [source]


def test_recursive_copy_keeps_all_nested_directories(tmp_path: Path) -> None:
    source_root = FIXTURE_ROOT / "04_サブフォルダ走査"
    output = tmp_path / "converted"
    sources = find_jpegs(source_root, recursive=True)
    plan = build_naming_plan(
        sources,
        output,
        source_root=source_root,
        preserve_tree=True,
    )

    results, errors = copy_many(plan)

    assert errors == []
    assert len(results) == 4
    assert sorted(
        result.destination.relative_to(output) for result in results
    ) == sorted(
        [
            Path("横浜/2025_10_17_1420_00.jpg"),
            Path("横浜/2025_10_17_1420_01.jpg"),
            Path("鎌倉/2025_10_17_1420_02.jpg"),
            Path("鎌倉/さらに下/2025_10_17_1421_00.jpg"),
        ]
    )
    assert all(source.exists() for source in sources)


def test_copy_many_keeps_original_and_copies_bytes_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "IMG_0001.jpg"
    create_jpeg(source)
    original_data = source.read_bytes()
    plan = build_naming_plan([source], tmp_path / "converted", "%model")

    results, errors = copy_many(plan)

    assert errors == []
    assert source.exists()
    assert source.read_bytes() == original_data
    assert results[0].destination.read_bytes() == original_data
    assert results[0].destination.name == "2025_10_17_1117_00_ZV-E10M2.jpg"


def test_committed_gui_test_data_covers_user_scenarios() -> None:
    basic = FIXTURE_ROOT / "01_基本_自由入力サフィックス"
    basic_plan = build_naming_plan(
        find_jpegs(basic),
        basic / "preview-only",
        filename_components=(
            COMPONENT_CUSTOM,
            COMPONENT_DATETIME,
            COMPONENT_SEQUENCE,
        ),
        custom_text="横浜中華街山下公園",
    )
    assert [item.new_name for item in basic_plan] == [
        "横浜中華街山下公園_2025_10_17_1117_00.jpg",
        "横浜中華街山下公園_2025_10_17_1117_01.jpg",
        "横浜中華街山下公園_2025_10_17_1118_00.jpg",
    ]

    skipped = FIXTURE_ROOT / "03_スキップ理由の確認"
    skipped_plan = build_naming_plan(find_jpegs(skipped), skipped / "preview-only")
    assert sum(item.destination is None for item in skipped_plan) == 3
    assert sum(item.destination is not None for item in skipped_plan) == 1

    recursive = FIXTURE_ROOT / "04_サブフォルダ走査"
    recursive_output = recursive / "converted"
    recursive_plan = build_naming_plan(
        find_jpegs(recursive, recursive=True, excluded_dirs=[recursive_output]),
        recursive_output,
        source_root=recursive,
        preserve_tree=True,
    )
    assert [item.destination.relative_to(recursive_output) for item in recursive_plan] == [
        Path("横浜/2025_10_17_1420_00.jpg"),
        Path("横浜/2025_10_17_1420_01.jpg"),
        Path("鎌倉/2025_10_17_1420_02.jpg"),
        Path("鎌倉/さらに下/2025_10_17_1421_00.jpg"),
    ]

    collision = FIXTURE_ROOT / "05_既存ファイル衝突回避"
    collision_plan = build_naming_plan(
        find_jpegs(collision), collision / "converted"
    )
    assert collision_plan[0].new_name == "2025_12_24_1830_01.jpg"
