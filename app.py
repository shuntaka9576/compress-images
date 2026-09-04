from __future__ import annotations

import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image
from tkinterdnd2 import DND_FILES, TkinterDnD

from compressor import (
    SUPPORTED_EXTENSIONS,
    ConversionOptions,
    ConversionResult,
    PreviewResult,
    compress_image,
    compress_many,
    find_images,
    preview_image,
)
from renamer import (
    COMPONENT_CUSTOM,
    COMPONENT_DATETIME,
    COMPONENT_MAKE,
    COMPONENT_MODEL,
    COMPONENT_SEQUENCE,
    JPEG_EXTENSIONS,
    CopyResult,
    ExifInfo,
    NamingPlanItem,
    build_naming_plan,
    copy_many,
    find_jpegs,
    render_filename,
)


MODE_COMPRESS = "compress"
MODE_RENAME = "rename"
COMPONENT_LABELS = {
    COMPONENT_DATETIME: "撮影日時（標準）",
    COMPONENT_SEQUENCE: "連番（必須）",
    COMPONENT_MAKE: "メーカー名",
    COMPONENT_MODEL: "機種名",
    COMPONENT_CUSTOM: "自由入力",
}


def collect_dropped_images(paths: list[Path]) -> list[Path]:
    """ドロップされたファイルとフォルダから、変換対象を重複なく集める。"""
    collected: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        candidates = find_images(path) if path.is_dir() else [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if (
                candidate.is_file()
                and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
                and resolved not in seen
            ):
                collected.append(candidate)
                seen.add(resolved)
    return collected


def format_file_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / 1024:.1f} KB"


def snap_value(value: float, step: int, minimum: int, maximum: int) -> int:
    """スライダー値を操作しやすい刻みへ丸める。"""
    snapped = int((value + step / 2) // step) * step
    return max(minimum, min(maximum, snapped))


def bundled_resource(relative_path: str) -> Path:
    """開発中と単体アプリ内のどちらでも同じ素材を参照する。"""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def run_self_test() -> int:
    """凍結済みアプリ内の画像変換・EXIF命名を、GUIを開かずに確認する。"""
    with tempfile.TemporaryDirectory(prefix="image-compressor-") as temporary:
        root = Path(temporary)
        source = root / "self-test.HEIC"
        Image.new("RGB", (3024, 4032), "#5d8062").save(
            source, format="HEIF", quality=80
        )
        result = compress_image(source, root / "converted", ConversionOptions())
        if not result.destination.exists():
            return 1
        if result.output_size != (605, 807):
            return 1
        if result.output_bytes > 150 * 1024:
            return 1
        rename_source = root / "IMG_0001.jpg"
        exif = Image.Exif()
        exif[36867] = "2025:10:17 11:17:00"
        exif[272] = "ZV-E10M2"
        Image.new("RGB", (64, 48), "#526f92").save(
            rename_source, format="JPEG", exif=exif
        )
        plan = build_naming_plan([rename_source], root / "renamed", "%model")
        rename_results, rename_errors = copy_many(plan)
        if rename_errors or len(rename_results) != 1:
            return 1
        if rename_results[0].destination.name != (
            "2025_10_17_1117_00_ZV-E10M2.jpg"
        ):
            return 1
        if not rename_source.exists():
            return 1
    return 0


class ImageCompressorApp(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("写真まとめて整理")
        self.geometry("980x880")
        self.minsize(900, 740)
        # macOSは.app内のICNSをDockアイコンとして使う。実行中にiconphotoで
        # 上書きするとLaunchServicesの表示が不安定になるため、Windows/Linuxのみ設定する。
        self.window_icon: tk.PhotoImage | None = None
        if sys.platform != "darwin":
            try:
                self.window_icon = tk.PhotoImage(
                    file=bundled_resource("assets/app-icon.png")
                )
                self.iconphoto(True, self.window_icon)
            except tk.TclError:
                pass

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.operation_mode = tk.StringVar(value=MODE_COMPRESS)
        self.scale_percent = tk.StringVar(value="20")
        self.target_enabled = tk.BooleanVar(value=False)
        self.target_kb = tk.StringVar(value="150")
        self.jpeg_quality = tk.StringVar(value="80")
        self.filename_components = [
            COMPONENT_DATETIME,
            COMPONENT_SEQUENCE,
        ]
        self.selected_component = tk.StringVar(value=COMPONENT_DATETIME)
        self.component_drag_name: str | None = None
        self.component_widgets: dict[str, tk.Label] = {}
        self.component_separators: list[tk.Label] = []
        self.custom_suffix = tk.StringVar()
        self.filename_example = tk.StringVar()
        self.rename_recursive = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="変換する写真が入ったフォルダを選んでください。")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.selected_sources: list[Path] | None = None
        self.preview_generation = 0
        self.preview_cancel_event = threading.Event()
        self.preview_worker: threading.Thread | None = None
        self.preview_items: dict[Path, str] = {}
        self.naming_plan: list[NamingPlanItem] = []
        self.naming_plan_key: tuple[object, ...] | None = None
        self.preview_completed = 0
        self.preview_status = tk.StringVar(value="写真を選ぶと、サイズを計算します。")
        self.preview_refresh_after_id: str | None = None

        self._build_ui()
        for variable in (
            self.scale_percent,
            self.target_enabled,
            self.target_kb,
            self.jpeg_quality,
        ):
            variable.trace_add("write", self._mark_preview_stale)
        self.custom_suffix.trace_add("write", self._filename_text_changed)
        self.output_dir.trace_add("write", self._output_directory_changed)
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        title = ttk.Label(outer, text="写真まとめて整理", font=("Yu Gothic UI", 18, "bold"))
        title.grid(row=0, column=0, sticky="w", pady=(0, 12))

        mode_row = ttk.Frame(outer)
        mode_row.grid(row=0, column=1, columnspan=2, sticky="e", pady=(0, 12))
        ttk.Label(mode_row, text="処理内容").pack(side="left", padx=(0, 6))
        ttk.Radiobutton(
            mode_row,
            text="圧縮・JPEG変換",
            variable=self.operation_mode,
            value=MODE_COMPRESS,
            command=self._on_mode_changed,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_row,
            text="撮影日時で名前を整理",
            variable=self.operation_mode,
            value=MODE_RENAME,
            command=self._on_mode_changed,
        ).pack(side="left", padx=(10, 0))

        self.drop_zone = tk.Label(
            outer,
            text="ここに写真またはフォルダをドロップ\nHEICを複数まとめて選べます",
            font=("Yu Gothic UI", 11, "bold"),
            foreground="#176b92",
            background="#eaf6fc",
            borderwidth=2,
            relief="groove",
            cursor="hand2",
            height=4,
        )
        self.drop_zone.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.drop_zone.drop_target_register(DND_FILES)
        self.drop_zone.dnd_bind("<<DropEnter>>", self._on_drop_enter)
        self.drop_zone.dnd_bind("<<DropLeave>>", self._on_drop_leave)
        self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)

        ttk.Label(outer, text="選択した写真").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(outer, textvariable=self.input_dir).grid(
            row=2, column=1, sticky="ew", padx=10, pady=6
        )
        ttk.Button(outer, text="フォルダ選択…", command=self._choose_input).grid(row=2, column=2)

        ttk.Label(outer, text="保存先フォルダ").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(outer, textvariable=self.output_dir).grid(
            row=3, column=1, sticky="ew", padx=10, pady=6
        )
        ttk.Button(outer, text="選択…", command=self._choose_output).grid(row=3, column=2)

        settings = ttk.LabelFrame(outer, text="圧縮設定", padding=14)
        settings.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 10))
        settings.columnconfigure(1, weight=1)
        self.compression_settings = settings

        ttk.Label(settings, text="画像サイズ").grid(row=0, column=0, sticky="w", pady=7)
        scale_row = ttk.Frame(settings)
        scale_row.grid(row=0, column=1, sticky="ew", padx=12)
        scale_row.columnconfigure(0, weight=1)
        self.scale_slider = ttk.Scale(
            scale_row,
            from_=5,
            to=100,
            orient="horizontal",
            command=self._on_scale_slide,
        )
        self.scale_slider.set(20)
        self.scale_slider.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        scale_entry = ttk.Entry(scale_row, width=5, textvariable=self.scale_percent, justify="right")
        scale_entry.grid(row=0, column=1)
        ttk.Label(scale_row, text="%").grid(row=0, column=2, padx=(4, 0))
        scale_hint = ttk.Frame(scale_row)
        scale_hint.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Label(scale_hint, text="小さく・軽く", foreground="#666666").pack(
            side="left"
        )
        ttk.Label(scale_hint, text="大きく・鮮明", foreground="#666666").pack(
            side="right"
        )
        scale_entry.bind(
            "<Return>",
            lambda _event: self._commit_manual_setting(
                self.scale_percent, self.scale_slider, 5, 100
            ),
        )
        scale_entry.bind(
            "<FocusOut>",
            lambda _event: self._commit_manual_setting(
                self.scale_percent, self.scale_slider, 5, 100
            ),
        )
        self.scale_slider.bind("<ButtonRelease-1>", self._commit_slider_setting)
        self.scale_slider.bind(
            "<Left>",
            lambda _event: self._nudge_slider(
                self.scale_percent, self.scale_slider, -5, 5, 100
            ),
        )
        self.scale_slider.bind(
            "<Right>",
            lambda _event: self._nudge_slider(
                self.scale_percent, self.scale_slider, 5, 5, 100
            ),
        )

        ttk.Label(settings, text="JPEG品質の上限").grid(row=1, column=0, sticky="w", pady=7)
        quality_row = ttk.Frame(settings)
        quality_row.grid(row=1, column=1, sticky="ew", padx=12)
        quality_row.columnconfigure(0, weight=1)
        self.quality_slider = ttk.Scale(
            quality_row,
            from_=30,
            to=95,
            orient="horizontal",
            command=self._on_quality_slide,
        )
        self.quality_slider.set(80)
        self.quality_slider.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        quality_entry = ttk.Entry(
            quality_row, width=5, textvariable=self.jpeg_quality, justify="right"
        )
        quality_entry.grid(row=0, column=1)
        ttk.Label(quality_row, text="/ 95").grid(row=0, column=2, padx=(4, 0))
        quality_hint = ttk.Frame(quality_row)
        quality_hint.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Label(quality_hint, text="軽量", foreground="#666666").pack(side="left")
        ttk.Label(quality_hint, text="高画質", foreground="#666666").pack(side="right")
        quality_entry.bind(
            "<Return>",
            lambda _event: self._commit_manual_setting(
                self.jpeg_quality, self.quality_slider, 30, 95
            ),
        )
        quality_entry.bind(
            "<FocusOut>",
            lambda _event: self._commit_manual_setting(
                self.jpeg_quality, self.quality_slider, 30, 95
            ),
        )
        self.quality_slider.bind("<ButtonRelease-1>", self._commit_slider_setting)
        self.quality_slider.bind(
            "<Left>",
            lambda _event: self._nudge_slider(
                self.jpeg_quality, self.quality_slider, -5, 30, 95
            ),
        )
        self.quality_slider.bind(
            "<Right>",
            lambda _event: self._nudge_slider(
                self.jpeg_quality, self.quality_slider, 5, 30, 95
            ),
        )

        target_check = ttk.Checkbutton(
            settings,
            text="ファイル容量を指定する（任意）",
            variable=self.target_enabled,
            command=self._toggle_target,
        )
        target_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 5))

        self.target_label = ttk.Label(settings, text="目標サイズ")
        self.target_label.grid(row=3, column=0, sticky="w", pady=7)
        self.target_row = ttk.Frame(settings)
        self.target_row.grid(row=3, column=1, sticky="w", padx=12)
        self.target_input = ttk.Entry(
            self.target_row,
            width=7,
            textvariable=self.target_kb,
            justify="right",
            state="disabled",
        )
        self.target_input.pack(side="left")
        ttk.Label(self.target_row, text="KB以下").pack(side="left", padx=6)
        self.target_input.bind("<Return>", self._commit_target_setting)
        self.target_input.bind("<FocusOut>", self._commit_target_setting)
        self.target_label.grid_remove()
        self.target_row.grid_remove()

        note = ttk.Label(
            settings,
            text="元画像は変更しません。向きを補正し、位置情報などの撮影情報はJPEGに含めません。",
            foreground="#555555",
        )
        note.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))

        rename_settings = ttk.LabelFrame(outer, text="ファイル名の設定", padding=14)
        rename_settings.grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=(12, 10)
        )
        rename_settings.columnconfigure(1, weight=1)
        self.rename_settings = rename_settings
        ttk.Label(
            rename_settings,
            text="新しいファイル名を、左から順に組み立てます",
            font=("Yu Gothic UI", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(2, 7))
        self.component_strip = tk.Frame(
            rename_settings,
            background="#f5f8fa",
            highlightbackground="#b9cbd6",
            highlightthickness=1,
            padx=8,
            pady=8,
        )
        self.component_strip.grid(row=1, column=0, columnspan=2, sticky="ew")

        component_actions = ttk.Frame(rename_settings)
        component_actions.grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(7, 4)
        )
        ttk.Label(
            component_actions,
            text="部品をクリックして選択。ドラッグでも移動できます。",
            foreground="#555555",
        ).pack(side="left")
        ttk.Button(
            component_actions,
            text="← 左へ",
            command=lambda: self._move_component(-1),
        ).pack(side="left", padx=(14, 4))
        ttk.Button(
            component_actions,
            text="右へ →",
            command=lambda: self._move_component(1),
        ).pack(side="left", padx=4)
        ttk.Button(
            component_actions, text="選択した部品を外す", command=self._remove_component
        ).pack(side="left", padx=(4, 0))

        ttk.Label(rename_settings, text="部品を追加").grid(
            row=3, column=0, sticky="w", pady=6
        )
        add_buttons = ttk.Frame(rename_settings)
        add_buttons.grid(row=3, column=1, sticky="w", padx=(12, 0), pady=4)
        for component, label in (
            (COMPONENT_MAKE, "＋ メーカー名"),
            (COMPONENT_MODEL, "＋ 機種名"),
            (COMPONENT_CUSTOM, "＋ 自由入力"),
        ):
            ttk.Button(
                add_buttons,
                text=label,
                command=lambda value=component: self._add_component(value),
            ).pack(side="left", padx=(0, 5))

        self.custom_suffix_label = ttk.Label(rename_settings, text="自由入力")
        self.custom_suffix_label.grid(row=4, column=0, sticky="w", pady=6)
        self.custom_suffix_input = ttk.Entry(
            rename_settings, textvariable=self.custom_suffix
        )
        self.custom_suffix_input.grid(
            row=4, column=1, sticky="ew", padx=(12, 0), pady=4
        )
        self.custom_suffix_label.grid_remove()
        self.custom_suffix_input.grid_remove()

        ttk.Label(
            rename_settings,
            textvariable=self.filename_example,
            foreground="#176b92",
            font=("Yu Gothic UI", 10, "bold"),
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 7))
        ttk.Checkbutton(
            rename_settings,
            text="サブフォルダも含める",
            variable=self.rename_recursive,
            command=self._naming_option_changed,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 4))
        ttk.Label(
            rename_settings,
            text=(
                "元のJPEGは変更しません。新しい名前で converted へコピーします。"
                "サブフォルダを含める場合は、フォルダ構成も保ちます。"
            ),
            foreground="#555555",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
        rename_settings.grid_remove()
        self._layout_component_chips()
        self._update_filename_example()

        action_row = ttk.Frame(outer)
        action_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=10)
        self.start_button = ttk.Button(action_row, text="まとめて変換", command=self._start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            action_row, text="中止", command=self.cancel_event.set, state="disabled"
        )
        self.cancel_button.pack(side="left", padx=8)
        self.open_button = ttk.Button(
            action_row, text="保存先を開く", command=self._open_output, state="disabled"
        )
        self.open_button.pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        ttk.Label(outer, textvariable=self.status).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )

        preview_frame = ttk.LabelFrame(outer, text="画像サイズのプレビュー", padding=8)
        preview_frame.grid(row=8, column=0, columnspan=3, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        self.preview_frame = preview_frame

        preview_toolbar = ttk.Frame(preview_frame)
        preview_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(preview_toolbar, textvariable=self.preview_status).pack(side="left")
        self.preview_button = ttk.Button(
            preview_toolbar, text="サイズを再計算", command=self._refresh_preview
        )
        self.preview_button.pack(side="right")

        columns = (
            "filename",
            "current_px",
            "current_size",
            "new_px",
            "new_size",
            "new_name",
            "result",
        )
        self.preview_tree = ttk.Treeview(
            preview_frame, columns=columns, show="headings", height=3
        )
        headings = {
            "filename": "ファイル名",
            "current_px": "現在のピクセル",
            "current_size": "現在の容量",
            "new_px": "変換後のピクセル",
            "new_size": "変換後の予想容量",
            "new_name": "新しいファイル名",
            "result": "判定・結果",
        }
        widths = {
            "filename": 210,
            "current_px": 120,
            "current_size": 100,
            "new_px": 130,
            "new_size": 145,
            "new_name": 300,
            "result": 180,
        }
        for column in columns:
            self.preview_tree.heading(column, text=headings[column])
            self.preview_tree.column(
                column,
                width=widths[column],
                minwidth=80,
                anchor="w" if column == "filename" else "center",
            )
        scrollbar = ttk.Scrollbar(
            preview_frame, orient="vertical", command=self.preview_tree.yview
        )
        self.preview_tree.configure(yscrollcommand=scrollbar.set)
        self.preview_tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        outer.rowconfigure(8, weight=1)
        self._configure_mode_ui()

    def _is_rename_mode(self) -> bool:
        return self.operation_mode.get() == MODE_RENAME

    def _configure_mode_ui(self) -> None:
        if self._is_rename_mode():
            self.compression_settings.grid_remove()
            self.rename_settings.grid()
            self.start_button.configure(text="名前を付けてコピー")
            self.preview_button.configure(text="名前を再確認")
            self.preview_frame.configure(text="ファイル名のプレビュー")
            self.preview_tree.configure(
                displaycolumns=("filename", "current_size", "new_name", "result")
            )
            self.preview_tree.column("filename", width=235, anchor="w")
            self.preview_tree.column("current_size", width=90, anchor="center")
            self.preview_tree.column("new_name", width=300, anchor="w")
            self.preview_tree.column("result", width=185, anchor="w")
            self.preview_status.set(
                "JPEGを選ぶと、EXIFを読み取って新しい名前を表示します。"
            )
        else:
            self.rename_settings.grid_remove()
            self.compression_settings.grid()
            self.start_button.configure(text="まとめて変換")
            self.preview_button.configure(text="サイズを再計算")
            self.preview_frame.configure(text="画像サイズのプレビュー")
            self.preview_tree.configure(
                displaycolumns=(
                    "filename",
                    "current_px",
                    "current_size",
                    "new_px",
                    "new_size",
                )
            )
            self.preview_status.set("写真を選ぶと、サイズを計算します。")

    def _on_mode_changed(self) -> None:
        self.preview_cancel_event.set()
        self.naming_plan = []
        self.naming_plan_key = None
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        self.preview_items.clear()
        self._configure_mode_ui()
        sources = self._current_sources()
        noun = "JPEG" if self._is_rename_mode() else "写真"
        if sources:
            self.drop_zone.configure(
                text=f"{len(sources)}枚の{noun}を受け付けました\n"
                "追加し直す場合は、もう一度ドロップ"
            )
            self.status.set(f"{len(sources)}枚を処理できます。設定を確認してください。")
            self._refresh_preview(show_error=False)
        else:
            input_value = self.input_dir.get().strip()
            if (
                self._is_rename_mode()
                and input_value
                and Path(input_value).is_dir()
            ):
                self._show_empty_rename_folder()
            else:
                self.drop_zone.configure(
                    text=(
                        "ここにJPEGまたはフォルダをドロップ\n"
                        "撮影日時から新しい名前を作ります"
                        if self._is_rename_mode()
                        else "ここに写真またはフォルダをドロップ\nHEICを複数まとめて選べます"
                    )
                )

    def _empty_rename_folder_message(self) -> str:
        if self.rename_recursive.get():
            return "サブフォルダを含めてもJPEGが見つかりません。"
        return (
            "選択フォルダ直下にJPEGがありません。"
            "画像が子フォルダにある場合は、"
            "「サブフォルダも含める」をONにしてください。"
        )

    def _show_empty_rename_folder(self) -> None:
        message = self._empty_rename_folder_message()
        self.drop_zone.configure(text="対象のJPEGは0枚です\n" + message)
        self.preview_status.set(message)
        self.status.set(message)
        self.start_button.configure(state="disabled")

    def _naming_option_changed(self, *_args: object) -> None:
        self.naming_plan_key = None
        if not self._is_rename_mode():
            return

        sources = self._current_sources()
        if sources:
            self.drop_zone.configure(
                text=f"{len(sources)}枚のJPEGを受け付けました\n"
                "追加し直す場合は、もう一度ドロップ"
            )
            self.preview_status.set("設定を変更中…自動で名前を再確認します。")
            self.start_button.configure(state="disabled")
            self._schedule_preview_refresh()
            return

        # 例: 直下にJPEGがないフォルダで「サブフォルダも含める」を
        # OFFに戻したとき。直前の再帰プレビューを残すと、対象があるように
        # 見えるためすぐに無効化する。
        if self.preview_refresh_after_id is not None:
            self.after_cancel(self.preview_refresh_after_id)
            self.preview_refresh_after_id = None
        self.preview_cancel_event.set()
        self.preview_generation += 1
        self.naming_plan = []
        self.preview_items.clear()
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        self.start_button.configure(state="disabled")
        self.progress.configure(value=0)

        input_value = self.input_dir.get().strip()
        if input_value and Path(input_value).is_dir():
            self._show_empty_rename_folder()
        else:
            message = "先にJPEGまたはフォルダを選んでください。"
            self.preview_status.set(message)

    def _component_chip_text(self, component: str) -> str:
        samples = {
            COMPONENT_DATETIME: "2025_10_17_1117",
            COMPONENT_SEQUENCE: "00",
            COMPONENT_MAKE: "SONY",
            COMPONENT_MODEL: "ZV-E10M2",
            COMPONENT_CUSTOM: self.custom_suffix.get().strip() or "入力文字",
        }
        sample = samples[component].replace("\n", " ")
        if len(sample) > 16:
            sample = sample[:15] + "…"
        return f"{COMPONENT_LABELS[component]}\n{sample}"

    def _layout_component_chips(self) -> None:
        for separator in self.component_separators:
            separator.destroy()
        self.component_separators.clear()
        for widget in self.component_widgets.values():
            widget.grid_forget()

        selected = self.selected_component.get()
        for index, component in enumerate(self.filename_components):
            widget = self.component_widgets.get(component)
            if widget is None:
                widget = tk.Label(
                    self.component_strip,
                    font=("Yu Gothic UI", 8, "bold"),
                    relief="solid",
                    borderwidth=1,
                    padx=8,
                    pady=4,
                    cursor="hand2",
                    takefocus=True,
                )
                widget.bind(
                    "<ButtonPress-1>",
                    lambda event, value=component: self._component_drag_start(
                        event, value
                    ),
                )
                widget.bind("<B1-Motion>", self._component_drag_motion)
                widget.bind("<ButtonRelease-1>", self._component_drag_end)
                widget.bind(
                    "<Left>", lambda _event: self._move_component(-1)
                )
                widget.bind(
                    "<Right>", lambda _event: self._move_component(1)
                )
                self.component_widgets[component] = widget
            is_selected = component == selected
            widget.configure(
                text=self._component_chip_text(component),
                background="#159bd7" if is_selected else "#ffffff",
                foreground="#ffffff" if is_selected else "#123b5d",
                highlightbackground="#159bd7" if is_selected else "#b9cbd6",
            )
            widget.grid(row=0, column=index * 2, sticky="w")
            plus = tk.Label(
                self.component_strip,
                text="＋",
                background="#f5f8fa",
                foreground="#687786",
                padx=3,
            )
            plus.grid(row=0, column=index * 2 + 1)
            self.component_separators.append(plus)

        extension = tk.Label(
            self.component_strip,
            text=".jpg",
            font=("Yu Gothic UI", 9, "bold"),
            background="#e5ebef",
            foreground="#263746",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=10,
        )
        extension.grid(row=0, column=len(self.filename_components) * 2, sticky="w")
        self.component_separators.append(extension)

    def _selected_component_index(self) -> int | None:
        selected = self.selected_component.get()
        if selected not in self.filename_components:
            return None
        return self.filename_components.index(selected)

    def _add_component(self, component: str) -> None:
        if component in self.filename_components:
            pass
        else:
            self.filename_components.append(component)
        self.selected_component.set(component)
        self._filename_settings_changed()
        if component == COMPONENT_CUSTOM:
            self.custom_suffix_input.focus_set()

    def _remove_component(self) -> None:
        index = self._selected_component_index()
        if index is None:
            return
        component = self.filename_components[index]
        if component in {COMPONENT_DATETIME, COMPONENT_SEQUENCE}:
            self.status.set("撮影日時と連番は必須です。順番は変更できます。")
            self.bell()
            return
        self.filename_components.pop(index)
        new_index = min(index, len(self.filename_components) - 1)
        self.selected_component.set(self.filename_components[new_index])
        self._filename_settings_changed()

    def _move_component(self, offset: int) -> None:
        index = self._selected_component_index()
        if index is None:
            return
        destination = max(0, min(len(self.filename_components) - 1, index + offset))
        if destination == index:
            return
        component = self.filename_components.pop(index)
        self.filename_components.insert(destination, component)
        self._filename_settings_changed()

    def _component_drag_start(self, _event: object, component: str) -> None:
        self.component_drag_name = component
        self.selected_component.set(component)
        self._layout_component_chips()
        widget = self.component_widgets[component]
        widget.focus_set()

    def _component_drag_motion(self, event: object) -> None:
        if self.component_drag_name not in self.filename_components:
            return
        pointer_x = int(getattr(event, "x_root", 0))
        centers = [
            self.component_widgets[component].winfo_rootx()
            + self.component_widgets[component].winfo_width() / 2
            for component in self.filename_components
        ]
        destination = min(
            range(len(centers)), key=lambda index: abs(pointer_x - centers[index])
        )
        current = self.filename_components.index(self.component_drag_name)
        if destination == current:
            return
        component = self.filename_components.pop(current)
        self.filename_components.insert(destination, component)
        self._filename_settings_changed()

    def _component_drag_end(self, _event: object) -> None:
        self.component_drag_name = None

    def _sync_custom_input(self) -> None:
        if COMPONENT_CUSTOM in self.filename_components:
            self.custom_suffix_label.grid()
            self.custom_suffix_input.grid()
        else:
            self.custom_suffix_label.grid_remove()
            self.custom_suffix_input.grid_remove()

    def _update_filename_example(self) -> None:
        sample = ExifInfo(
            taken_at=datetime(2025, 10, 17, 11, 17),
            make="SONY",
            model="ZV-E10M2",
        )
        filename = render_filename(
            sample,
            0,
            self.filename_components,
            self.custom_suffix.get(),
        )
        hint = (
            "  （自由入力に文字を入れてください）"
            if COMPONENT_CUSTOM in self.filename_components
            and not self.custom_suffix.get().strip()
            else ""
        )
        self.filename_example.set(
            f"仕上がり例　IMG_1001.JPG  →  {filename}{hint}"
        )

    def _filename_settings_changed(self, *_args: object) -> None:
        self._sync_custom_input()
        self._layout_component_chips()
        self._update_filename_example()
        self._naming_option_changed()

    def _filename_text_changed(self, *_args: object) -> None:
        self._update_filename_example()
        if COMPONENT_CUSTOM in self.filename_components:
            self._naming_option_changed()

    def _output_directory_changed(self, *_args: object) -> None:
        if self._is_rename_mode():
            self._naming_option_changed()

    def _naming_key(
        self, sources: list[Path], output_dir: Path
    ) -> tuple[object, ...]:
        return (
            tuple(str(source.resolve()) for source in sources),
            str(output_dir.absolute()),
            tuple(self.filename_components),
            self.custom_suffix.get(),
            self.rename_recursive.get(),
            str(Path(self.input_dir.get()).absolute()),
        )

    def _source_label(self, source: Path) -> str:
        input_path = Path(self.input_dir.get())
        if input_path.is_dir():
            try:
                return str(source.resolve().relative_to(input_path.resolve()))
            except ValueError:
                pass
        return source.name

    def _mark_preview_stale(self, *_args: object) -> None:
        if self.preview_items:
            self.preview_status.set("設定を変更中…操作を終えると自動で再計算します。")

    def _on_scale_slide(self, value: str) -> None:
        self.scale_percent.set(str(snap_value(float(value), 5, 5, 100)))

    def _on_quality_slide(self, value: str) -> None:
        self.jpeg_quality.set(str(snap_value(float(value), 5, 30, 95)))

    def _commit_slider_setting(self, _event: object | None = None) -> None:
        self.scale_slider.set(int(self.scale_percent.get()))
        self.quality_slider.set(int(self.jpeg_quality.get()))
        self._schedule_preview_refresh()

    def _nudge_slider(
        self,
        variable: tk.StringVar,
        slider: ttk.Scale,
        amount: int,
        minimum: int,
        maximum: int,
    ) -> str:
        value = max(minimum, min(maximum, int(variable.get()) + amount))
        variable.set(str(value))
        slider.set(value)
        self._schedule_preview_refresh()
        return "break"

    def _commit_manual_setting(
        self,
        variable: tk.StringVar,
        slider: ttk.Scale,
        minimum: int,
        maximum: int,
    ) -> None:
        try:
            value = int(variable.get())
        except ValueError:
            value = round(float(slider.get()))
        value = max(minimum, min(maximum, value))
        variable.set(str(value))
        slider.set(value)
        self._schedule_preview_refresh()

    def _commit_target_setting(self, _event: object | None = None) -> None:
        try:
            value = int(self.target_kb.get())
        except ValueError:
            value = 150
        self.target_kb.set(str(max(10, min(10000, value))))
        self._schedule_preview_refresh()

    def _schedule_preview_refresh(self) -> None:
        if not self._current_sources():
            return
        if self.preview_refresh_after_id is not None:
            self.after_cancel(self.preview_refresh_after_id)
        self.preview_refresh_after_id = self.after(350, self._run_scheduled_preview)

    def _run_scheduled_preview(self) -> None:
        self.preview_refresh_after_id = None
        self._refresh_preview(show_error=False)

    def _current_sources(self) -> list[Path]:
        if self.selected_sources is not None:
            sources = [source for source in self.selected_sources if source.is_file()]
            if self._is_rename_mode():
                return [
                    source
                    for source in sources
                    if source.suffix.lower() in JPEG_EXTENSIONS
                ]
            return sources
        input_value = self.input_dir.get().strip()
        if not input_value:
            return []
        input_dir = Path(input_value)
        if not input_dir.is_dir():
            return []
        if self._is_rename_mode():
            excluded: list[Path] = []
            if self.output_dir.get().strip():
                excluded.append(Path(self.output_dir.get()))
            return find_jpegs(
                input_dir,
                recursive=self.rename_recursive.get(),
                excluded_dirs=excluded,
            )
        return find_images(input_dir)

    def _refresh_preview(self, show_error: bool = True) -> None:
        if self.preview_refresh_after_id is not None:
            self.after_cancel(self.preview_refresh_after_id)
            self.preview_refresh_after_id = None
        if self.worker and self.worker.is_alive():
            return
        sources = self._current_sources()
        if not sources:
            if show_error:
                input_value = self.input_dir.get().strip()
                if (
                    self._is_rename_mode()
                    and input_value
                    and Path(input_value).is_dir()
                ):
                    messagebox.showinfo(
                        "JPEGなし", self._empty_rename_folder_message()
                    )
                else:
                    messagebox.showinfo(
                        "写真なし", "先に写真またはフォルダを選んでください。"
                    )
            return
        options: ConversionOptions | None = None
        if not self._is_rename_mode():
            try:
                options = self._parse_options()
            except ValueError as error:
                if show_error:
                    messagebox.showerror("設定エラー", str(error))
                return
        elif not self.output_dir.get().strip():
            if show_error:
                messagebox.showerror("フォルダ未選択", "保存先フォルダを選択してください。")
            return

        self.preview_cancel_event.set()
        self.preview_cancel_event = threading.Event()
        self.preview_generation += 1
        generation = self.preview_generation
        self.preview_completed = 0
        self.preview_items.clear()
        self.naming_plan = []
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        for source in sources:
            input_size = format_file_size(source.stat().st_size)
            if self._is_rename_mode():
                values = (
                    self._source_label(source),
                    "",
                    input_size,
                    "",
                    "",
                    "EXIF読取中…",
                    "確認中…",
                )
            else:
                values = (
                    source.name,
                    "計算中…",
                    input_size,
                    "計算中…",
                    "計算中…",
                    "",
                    "",
                )
            item = self.preview_tree.insert("", "end", values=values)
            self.preview_items[source.resolve()] = item

        action = "名前を確認" if self._is_rename_mode() else "サイズを計算"
        self.preview_status.set(f"0 / {len(sources)} 枚の{action}中…")
        self.preview_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        if self._is_rename_mode():
            output_dir = Path(self.output_dir.get())
            input_path = Path(self.input_dir.get())
            source_root = (
                input_path
                if self.selected_sources is None and input_path.is_dir()
                else None
            )
            preserve_tree = self.rename_recursive.get() and source_root is not None
            naming_key = self._naming_key(sources, output_dir)
            self.preview_worker = threading.Thread(
                target=self._naming_preview_worker,
                args=(
                    generation,
                    sources,
                    output_dir,
                    source_root,
                    preserve_tree,
                    tuple(self.filename_components),
                    self.custom_suffix.get(),
                    naming_key,
                    self.preview_cancel_event,
                ),
                daemon=True,
            )
        else:
            assert options is not None
            self.preview_worker = threading.Thread(
                target=self._preview_worker,
                args=(generation, sources, options, self.preview_cancel_event),
                daemon=True,
            )
        self.preview_worker.start()

    def _preview_worker(
        self,
        generation: int,
        sources: list[Path],
        options: ConversionOptions,
        cancel_event: threading.Event,
    ) -> None:
        for source in sources:
            if cancel_event.is_set():
                break
            try:
                result = preview_image(source, options)
                self.events.put(("preview", (generation, result)))
            except Exception as error:
                self.events.put(("preview_error", (generation, source, error)))
        self.events.put(("preview_done", (generation, len(sources), cancel_event.is_set())))

    def _naming_preview_worker(
        self,
        generation: int,
        sources: list[Path],
        output_dir: Path,
        source_root: Path | None,
        preserve_tree: bool,
        filename_components: tuple[str, ...],
        custom_text: str,
        naming_key: tuple[object, ...],
        cancel_event: threading.Event,
    ) -> None:
        plan = build_naming_plan(
            sources,
            output_dir,
            source_root=source_root,
            preserve_tree=preserve_tree,
            filename_components=filename_components,
            custom_text=custom_text,
            should_cancel=cancel_event.is_set,
        )
        self.events.put(
            (
                "naming_preview_done",
                (generation, plan, naming_key, cancel_event.is_set()),
            )
        )

    def _on_drop_enter(self, event: object) -> str:
        self.drop_zone.configure(background="#d6f0fb", relief="solid")
        return "copy"

    def _on_drop_leave(self, event: object) -> str:
        self.drop_zone.configure(background="#eaf6fc", relief="groove")
        return "copy"

    def _on_drop(self, event: object) -> str:
        self._on_drop_leave(event)
        raw_data = getattr(event, "data", "")
        paths = [Path(value) for value in self.tk.splitlist(raw_data)]
        only_directory = len(paths) == 1 and paths[0].is_dir()
        if only_directory:
            input_dir = paths[0]
            self.selected_sources = None
            self.input_dir.set(str(input_dir))
            self.output_dir.set(str(input_dir / "converted"))
        else:
            selected = collect_dropped_images(paths)
            self.selected_sources = selected
            if selected:
                self.input_dir.set(f"{len(selected)}枚の写真を選択")
                self.output_dir.set(str(selected[0].parent / "converted"))

        sources = self._current_sources()
        if not sources:
            if only_directory and self._is_rename_mode():
                self._show_empty_rename_folder()
                return "copy"
            target = "JPEG" if self._is_rename_mode() else "HEIC、JPEG、PNGなど"
            messagebox.showinfo(
                "写真なし",
                f"対応する写真が見つかりませんでした。\n{target}をドロップしてください。",
            )
            return "copy"

        noun = "JPEG" if self._is_rename_mode() else "写真"
        self.drop_zone.configure(
            text=f"{len(sources)}枚の{noun}を受け付けました\n"
            "追加し直す場合は、もう一度ドロップ"
        )
        action = "名前を整理" if self._is_rename_mode() else "変換"
        self.status.set(f"{len(sources)}枚の写真を{action}できます。設定を確認してください。")
        self._refresh_preview(show_error=False)
        return "copy"

    def _choose_input(self) -> None:
        selected = filedialog.askdirectory(title="元の写真フォルダを選択")
        if selected:
            self.selected_sources = None
            self.input_dir.set(selected)
            self.output_dir.set(str(Path(selected) / "converted"))
            sources = self._current_sources()
            noun = "JPEG" if self._is_rename_mode() else "写真"
            if not sources and self._is_rename_mode():
                self._show_empty_rename_folder()
            else:
                self.drop_zone.configure(
                    text=f"{len(sources)}枚の{noun}を受け付けました\n"
                    "追加し直す場合は、もう一度ドロップ"
                )
                self.status.set(
                    f"{len(sources)}枚を処理できます。設定を確認してください。"
                )
                self._refresh_preview(show_error=False)

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="保存先フォルダを選択")
        if selected:
            self.output_dir.set(selected)

    def _toggle_target(self) -> None:
        if self.target_enabled.get():
            self.target_label.grid()
            self.target_row.grid()
            self.target_input.configure(state="normal")
        else:
            self.target_input.configure(state="disabled")
            self.target_label.grid_remove()
            self.target_row.grid_remove()
        self._schedule_preview_refresh()

    def _parse_options(self) -> ConversionOptions:
        try:
            target_kb = int(self.target_kb.get()) if self.target_enabled.get() else None
            options = ConversionOptions(
                scale_percent=int(self.scale_percent.get()),
                jpeg_quality=int(self.jpeg_quality.get()),
                target_kb=target_kb,
            )
            options.validate()
            return options
        except ValueError as error:
            raise ValueError(f"設定値を確認してください。\n{error}") from error

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        output_dir = Path(self.output_dir.get())
        sources = self._current_sources()
        if not sources:
            input_value = self.input_dir.get().strip()
            if (
                self._is_rename_mode()
                and input_value
                and Path(input_value).is_dir()
            ):
                messagebox.showinfo(
                    "JPEGなし", self._empty_rename_folder_message()
                )
            else:
                messagebox.showerror(
                    "写真未選択", "写真またはフォルダをドロップしてください。"
                )
            return
        if not self.output_dir.get():
            messagebox.showerror("フォルダ未選択", "保存先フォルダを選択してください。")
            return
        if self._is_rename_mode():
            self._start_naming(sources, output_dir)
            return
        try:
            options = self._parse_options()
        except ValueError as error:
            messagebox.showerror("設定エラー", str(error))
            return

        if not sources:
            messagebox.showinfo("写真なし", "対応する写真が見つかりませんでした。")
            return

        self.cancel_event.clear()
        self.progress.configure(maximum=len(sources), value=0)
        self.start_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.status.set(f"0 / {len(sources)} 枚を変換済み")

        self.worker = threading.Thread(
            target=self._convert_worker,
            args=(sources, output_dir, options),
            daemon=True,
        )
        self.worker.start()

    def _start_naming(self, sources: list[Path], output_dir: Path) -> None:
        naming_key = self._naming_key(sources, output_dir)
        if self.naming_plan_key != naming_key:
            self._refresh_preview(show_error=False)
            messagebox.showinfo(
                "プレビューを更新中",
                "最新の設定でファイル名を確認しています。\n"
                "一覧の確認が終わってから、もう一度実行してください。",
            )
            return

        eligible = [item for item in self.naming_plan if item.destination is not None]
        skipped = len(self.naming_plan) - len(eligible)
        if not eligible:
            messagebox.showinfo(
                "コピー対象なし",
                "EXIF撮影日時のあるJPEGが見つかりませんでした。\n"
                "一覧のスキップ理由を確認してください。",
            )
            return

        recursive_note = (
            "\nサブフォルダの構成は保存先にも引き継ぎます。"
            if self.rename_recursive.get()
            else ""
        )
        if not messagebox.askokcancel(
            "コピー内容の確認",
            f"プレビューのとおり {len(eligible)}枚を新しい名前でコピーします。\n"
            f"スキップ: {skipped}枚\n"
            f"保存先: {output_dir}\n\n"
            f"元のJPEGは変更しません。{recursive_note}",
        ):
            return

        self.cancel_event.clear()
        self.progress.configure(maximum=len(eligible), value=0)
        self.start_button.configure(state="disabled")
        self.preview_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.status.set(f"0 / {len(eligible)} 枚をコピー済み")
        self.worker = threading.Thread(
            target=self._naming_worker,
            args=(self.naming_plan.copy(), output_dir, len(eligible), skipped),
            daemon=True,
        )
        self.worker.start()

    def _convert_worker(
        self,
        sources: list[Path],
        output_dir: Path,
        options: ConversionOptions,
    ) -> None:
        def on_result(result: ConversionResult) -> None:
            self.events.put(("result", result))

        results, errors = compress_many(
            sources,
            output_dir,
            options,
            on_result=on_result,
            should_cancel=self.cancel_event.is_set,
        )
        self.events.put(("done", (len(sources), results, errors, output_dir)))

    def _naming_worker(
        self,
        plan: list[NamingPlanItem],
        output_dir: Path,
        eligible_count: int,
        skipped_count: int,
    ) -> None:
        def on_result(result: CopyResult) -> None:
            self.events.put(("naming_result", result))

        results, errors = copy_many(
            plan,
            on_result=on_result,
            should_cancel=self.cancel_event.is_set,
        )
        self.events.put(
            (
                "naming_done",
                (eligible_count, skipped_count, results, errors, output_dir),
            )
        )

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "result":
                    result = payload
                    assert isinstance(result, ConversionResult)
                    self.progress.step()
                    size_kb = result.output_bytes / 1024
                    self.status.set(
                        f"{int(self.progress['value'])} / {int(self.progress['maximum'])} 枚を変換済み"
                    )
                    item = self.preview_items.get(result.source.resolve())
                    if item:
                        values = list(self.preview_tree.item(item, "values"))
                        values[3] = f"{result.output_size[0]}x{result.output_size[1]}"
                        values[4] = f"{size_kb:.1f} KB（完了）"
                        self.preview_tree.item(item, values=values)
                elif kind == "done":
                    total, results, errors, output_dir = payload
                    self._finish(total, results, errors, output_dir)
                elif kind == "naming_result":
                    result = payload
                    assert isinstance(result, CopyResult)
                    self.progress.step()
                    self.status.set(
                        f"{int(self.progress['value'])} / "
                        f"{int(self.progress['maximum'])} 枚をコピー済み"
                    )
                    item = self.preview_items.get(result.source.resolve())
                    if item:
                        values = list(self.preview_tree.item(item, "values"))
                        values[6] = "コピー完了"
                        self.preview_tree.item(item, values=values)
                elif kind == "naming_done":
                    eligible, skipped, results, errors, output_dir = payload
                    self._finish_naming(
                        eligible, skipped, results, errors, output_dir
                    )
                elif kind == "preview":
                    generation, result = payload
                    if generation != self.preview_generation:
                        continue
                    assert isinstance(result, PreviewResult)
                    item = self.preview_items.get(result.source.resolve())
                    if item:
                        self.preview_tree.item(
                            item,
                            values=(
                                result.source.name,
                                f"{result.original_size[0]}x{result.original_size[1]}",
                                format_file_size(result.input_bytes),
                                f"{result.output_size[0]}x{result.output_size[1]}",
                                f"{result.output_bytes / 1024:.1f} KB（品質{result.quality}）",
                            ),
                        )
                    self.preview_completed += 1
                    self.preview_status.set(
                        f"{self.preview_completed} / {len(self.preview_items)} 枚のサイズを計算中…"
                    )
                elif kind == "preview_error":
                    generation, source, error = payload
                    if generation != self.preview_generation:
                        continue
                    item = self.preview_items.get(source.resolve())
                    if item:
                        values = list(self.preview_tree.item(item, "values"))
                        values[3] = "-"
                        values[4] = f"読込エラー: {error}"
                        self.preview_tree.item(item, values=values)
                    self.preview_completed += 1
                elif kind == "preview_done":
                    generation, total, cancelled = payload
                    if generation != self.preview_generation:
                        continue
                    self.preview_button.configure(state="normal")
                    self.start_button.configure(state="normal")
                    if cancelled:
                        self.preview_status.set("サイズ計算を中止しました。")
                    else:
                        self.preview_status.set(
                            f"{total}枚の予想サイズを計算しました。"
                        )
                elif kind == "naming_preview_done":
                    generation, plan, naming_key, cancelled = payload
                    if generation != self.preview_generation:
                        continue
                    self.naming_plan = plan
                    self.naming_plan_key = naming_key if not cancelled else None
                    copy_count = 0
                    skip_count = 0
                    output_dir = Path(self.output_dir.get())
                    for plan_item in plan:
                        assert isinstance(plan_item, NamingPlanItem)
                        item = self.preview_items.get(plan_item.source.resolve())
                        if plan_item.destination is None:
                            skip_count += 1
                            new_name = "-"
                        else:
                            copy_count += 1
                            try:
                                new_name = str(
                                    plan_item.destination.relative_to(output_dir)
                                )
                            except ValueError:
                                new_name = plan_item.new_name
                        if item:
                            values = list(self.preview_tree.item(item, "values"))
                            values[5] = new_name
                            values[6] = plan_item.status
                            self.preview_tree.item(item, values=values)
                    self.preview_button.configure(state="normal")
                    self.start_button.configure(
                        state="normal" if copy_count and not cancelled else "disabled"
                    )
                    if cancelled:
                        self.preview_status.set("ファイル名の確認を中止しました。")
                    else:
                        self.preview_status.set(
                            f"{copy_count}枚をコピー予定、{skip_count}枚をスキップします。"
                        )
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _finish(
        self,
        total: int,
        results: list[ConversionResult],
        errors: list[tuple[Path, Exception]],
        output_dir: Path,
    ) -> None:
        self.start_button.configure(state="normal")
        self.preview_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.open_button.configure(state="normal" if output_dir.exists() else "disabled")
        cancelled = self.cancel_event.is_set() and len(results) + len(errors) < total
        if errors:
            for path, error in errors:
                item = self.preview_items.get(path.resolve())
                if item:
                    values = list(self.preview_tree.item(item, "values"))
                    values[4] = f"変換エラー: {error}"
                    self.preview_tree.item(item, values=values)
        if cancelled:
            self.status.set(f"中止しました（成功 {len(results)} 枚、失敗 {len(errors)} 枚）")
        else:
            self.status.set(f"完了しました（成功 {len(results)} 枚、失敗 {len(errors)} 枚）")
            messagebox.showinfo(
                "変換完了",
                f"{len(results)}枚をJPEGに変換しました。\n保存先: {output_dir}",
            )

    def _finish_naming(
        self,
        eligible: int,
        skipped: int,
        results: list[CopyResult],
        errors: list[tuple[Path, Exception]],
        output_dir: Path,
    ) -> None:
        self.start_button.configure(state="normal")
        self.preview_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.open_button.configure(state="normal" if output_dir.exists() else "disabled")
        cancelled = self.cancel_event.is_set() and len(results) + len(errors) < eligible
        for path, error in errors:
            item = self.preview_items.get(path.resolve())
            if item:
                values = list(self.preview_tree.item(item, "values"))
                values[6] = f"コピーエラー: {error}"
                self.preview_tree.item(item, values=values)
        if cancelled:
            self.status.set(
                f"中止しました（コピー {len(results)} 枚、失敗 {len(errors)} 枚、"
                f"スキップ {skipped} 枚）"
            )
        else:
            self.status.set(
                f"完了しました（コピー {len(results)} 枚、失敗 {len(errors)} 枚、"
                f"スキップ {skipped} 枚）"
            )
            messagebox.showinfo(
                "ファイル名の整理完了",
                f"{len(results)}枚を新しい名前でコピーしました。\n"
                f"元のJPEGは変更していません。\n保存先: {output_dir}",
            )
        # 保存先の既存ファイルが増えたため、次回実行前に連番を再確認する。
        self.naming_plan_key = None
        self.after(100, lambda: self._refresh_preview(show_error=False))

    def _open_output(self) -> None:
        output_dir = Path(self.output_dir.get())
        if not output_dir.exists():
            return
        if sys.platform == "win32":
            os_startfile = getattr(__import__("os"), "startfile")
            os_startfile(output_dir)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(output_dir)], check=False)
        else:
            subprocess.run(["xdg-open", str(output_dir)], check=False)

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(run_self_test())
    ImageCompressorApp().mainloop()
