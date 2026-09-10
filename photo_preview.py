"""Read-only photo previews; decoding runs away from the Tk event loop."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageOps, ImageTk


def load_photo(path: Path, bounds: tuple[int, int]) -> Image.Image:
    with Image.open(path) as original:
        # JPEG can decode at 1/2, 1/4 or 1/8 size. Resize before rotating so a
        # thumbnail never needs a second full-resolution camera image in memory.
        orientation = original.getexif().get(274, 1)
        raw_bounds = bounds[::-1] if orientation in (5, 6, 7, 8) else bounds
        original.draft("RGB", raw_bounds)
        original.thumbnail(raw_bounds, Image.Resampling.LANCZOS)
        ImageOps.exif_transpose(original, in_place=True)
        return original.convert("RGB")


class PhotoPreview(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, padding=(10, 0, 0, 0))
        self.filename = ttk.Label(self, text="写真をクリックすると大きく表示", wraplength=290)
        self.filename.pack(fill="x", pady=(0, 6))
        self.detail = ttk.Label(self, text="", wraplength=290, foreground="#576574")
        self.detail.pack(fill="x", pady=(0, 4))
        self.canvas = tk.Canvas(self, background="#eef1f4", highlightthickness=0, width=290, height=220)
        self.canvas.pack(fill="both", expand=True)
        ttk.Label(self, text="チェックを外した写真も見られます", wraplength=290).pack(fill="x", pady=(6, 0))
        self.path: Path | None = None
        self.bitmap: Image.Image | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.generation = 0
        self.message = "写真を選択してください"
        self.requests: queue.Queue = queue.Queue(maxsize=1)
        self.results: queue.Queue = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.canvas.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Destroy>", self._destroyed)
        threading.Thread(target=self._worker, daemon=True).start()
        self.timer = self.after(80, self._poll)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self.closed.set()
            self.after_cancel(self.timer)

    def show(self, path: Path | None, *, force: bool = False) -> None:
        if path == self.path and not force:
            return
        self.path = path
        self.generation += 1
        self.bitmap = None
        self.filename.configure(text=path.name if path else "写真をクリックすると大きく表示")
        self.message = "読み込み中…" if path else "写真を選択してください"
        self._draw()
        if path:
            try:
                self.requests.get_nowait()
            except queue.Empty:
                pass
            self.requests.put_nowait((self.generation, path))

    def _worker(self) -> None:
        while not self.closed.is_set():
            try:
                generation, path = self.requests.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                result = load_photo(path, (1400, 1400))
            except Exception:
                result = None
            try:
                self.results.get_nowait()
            except queue.Empty:
                pass
            self.results.put_nowait((generation, result))

    def _poll(self) -> None:
        try:
            generation, bitmap = self.results.get_nowait()
            if generation == self.generation:
                self.bitmap = bitmap
                self.message = "写真を読み込めませんでした" if bitmap is None else ""
                self._draw()
        except queue.Empty:
            pass
        self.timer = self.after(80, self._poll)

    def _draw(self) -> None:
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.delete("all")
        if self.bitmap:
            fitted = ImageOps.contain(self.bitmap, (max(1, width - 12), max(1, height - 12)))
            self.photo = ImageTk.PhotoImage(fitted, master=self)
            self.canvas.create_image(width / 2, height / 2, image=self.photo)
        else:
            self.photo = None
            self.canvas.create_text(width / 2, height / 2, text=self.message, width=max(1, width - 20), fill="#576574")
