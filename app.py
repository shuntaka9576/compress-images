from __future__ import annotations

import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
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
    """凍結済みアプリ内のHEIC/JPEGライブラリを、GUIを開かずに確認する。"""
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
    return 0


class ImageCompressorApp(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("写真まとめて圧縮")
        self.geometry("900x760")
        self.minsize(820, 680)
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
        self.scale_percent = tk.StringVar(value="20")
        self.target_enabled = tk.BooleanVar(value=False)
        self.target_kb = tk.StringVar(value="150")
        self.jpeg_quality = tk.StringVar(value="80")
        self.status = tk.StringVar(value="変換する写真が入ったフォルダを選んでください。")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.selected_sources: list[Path] | None = None
        self.preview_generation = 0
        self.preview_cancel_event = threading.Event()
        self.preview_worker: threading.Thread | None = None
        self.preview_items: dict[Path, str] = {}
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
        self.after(100, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        title = ttk.Label(outer, text="写真まとめて圧縮", font=("Yu Gothic UI", 18, "bold"))
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

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

        preview_toolbar = ttk.Frame(preview_frame)
        preview_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(preview_toolbar, textvariable=self.preview_status).pack(side="left")
        self.preview_button = ttk.Button(
            preview_toolbar, text="サイズを再計算", command=self._refresh_preview
        )
        self.preview_button.pack(side="right")

        columns = ("filename", "current_px", "current_size", "new_px", "new_size")
        self.preview_tree = ttk.Treeview(
            preview_frame, columns=columns, show="headings", height=8
        )
        headings = {
            "filename": "ファイル名",
            "current_px": "現在のピクセル",
            "current_size": "現在の容量",
            "new_px": "変換後のピクセル",
            "new_size": "変換後の予想容量",
        }
        widths = {
            "filename": 210,
            "current_px": 120,
            "current_size": 100,
            "new_px": 130,
            "new_size": 145,
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
            return [source for source in self.selected_sources if source.is_file()]
        input_dir = Path(self.input_dir.get())
        return find_images(input_dir) if input_dir.is_dir() else []

    def _refresh_preview(self, show_error: bool = True) -> None:
        if self.worker and self.worker.is_alive():
            return
        sources = self._current_sources()
        if not sources:
            if show_error:
                messagebox.showinfo("写真なし", "先に写真またはフォルダを選んでください。")
            return
        try:
            options = self._parse_options()
        except ValueError as error:
            if show_error:
                messagebox.showerror("設定エラー", str(error))
            return

        self.preview_cancel_event.set()
        self.preview_cancel_event = threading.Event()
        self.preview_generation += 1
        generation = self.preview_generation
        self.preview_completed = 0
        self.preview_items.clear()
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        for source in sources:
            input_size = format_file_size(source.stat().st_size)
            item = self.preview_tree.insert(
                "",
                "end",
                values=(source.name, "計算中…", input_size, "計算中…", "計算中…"),
            )
            self.preview_items[source.resolve()] = item

        self.preview_status.set(f"0 / {len(sources)} 枚のサイズを計算中…")
        self.preview_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
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
        sources = collect_dropped_images(paths)
        if not sources:
            messagebox.showinfo(
                "写真なし",
                "対応する写真が見つかりませんでした。\nHEIC、JPEG、PNGなどをドロップしてください。",
            )
            return "copy"

        only_directory = len(paths) == 1 and paths[0].is_dir()
        if only_directory:
            input_dir = paths[0]
            self.selected_sources = None
            self.input_dir.set(str(input_dir))
            self.output_dir.set(str(input_dir / "converted"))
        else:
            self.selected_sources = sources
            self.input_dir.set(f"{len(sources)}枚の写真を選択")
            self.output_dir.set(str(sources[0].parent / "converted"))

        self.drop_zone.configure(text=f"{len(sources)}枚の写真を受け付けました\n追加し直す場合は、もう一度ドロップ")
        self.status.set(f"{len(sources)}枚の写真を変換できます。設定を確認してください。")
        self._refresh_preview(show_error=False)
        return "copy"

    def _choose_input(self) -> None:
        selected = filedialog.askdirectory(title="元の写真フォルダを選択")
        if selected:
            self.selected_sources = None
            self.input_dir.set(selected)
            sources = find_images(Path(selected))
            self.output_dir.set(str(Path(selected) / "converted"))
            self.drop_zone.configure(
                text=f"{len(sources)}枚の写真を受け付けました\n追加し直す場合は、もう一度ドロップ"
            )
            self.status.set(f"{len(sources)}枚の写真を変換できます。設定を確認してください。")
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
            messagebox.showerror(
                "写真未選択", "写真またはフォルダをドロップしてください。"
            )
            return
        if not self.output_dir.get():
            messagebox.showerror("フォルダ未選択", "保存先フォルダを選択してください。")
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
