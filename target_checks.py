"""Target checkbox controls, recycled for the visible Treeview rows only."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from collections.abc import Callable
from PIL import Image, ImageDraw, ImageTk


class TargetChecks:
    def __init__(
        self, tree: ttk.Treeview, toggle: Callable[[str], None],
        is_busy: Callable[[], bool],
    ) -> None:
        self.tree = tree
        self.toggle = toggle
        self.is_busy = is_busy
        self.buttons: list[tk.Canvas] = []
        self.pending: str | None = None
        # Use a consistent, generously sized indicator on both Aqua and Windows.
        self.icons = []
        for checked, disabled in ((False, False), (True, False), (False, True), (True, True)):
            bitmap = Image.new("RGBA", (96, 80))
            draw = ImageDraw.Draw(bitmap)
            fill = "#a8b1bb" if disabled else "#1769d2"
            draw.rounded_rectangle((4, 4, 76, 76), radius=16,
                                   fill=fill if checked else "#ffffff",
                                   outline=fill if checked else "#8b98a7", width=5)
            if checked:
                draw.line((20, 40, 34, 54, 60, 26), fill="white", width=8, joint="curve")
            self.icons.append(ImageTk.PhotoImage(bitmap.resize((24, 20), Image.Resampling.LANCZOS), master=tree))
        for event in ("<Configure>", "<<TreeviewSelect>>", "<ButtonRelease-1>"):
            tree.bind(event, self.schedule, add=True)
        tree.bind("<Destroy>", self._destroy, add=True)

    def _destroy(self, event: tk.Event) -> None:
        if event.widget is self.tree and self.pending is not None:
            self.tree.after_cancel(self.pending)
            self.pending = None

    def schedule(self, _event: object = None) -> None:
        if self.pending is None:
            self.pending = self.tree.after_idle(self.refresh)

    def _activate(self, row: str) -> None:
        self.tree.focus_set()
        self.tree.focus(row)
        self.tree.selection_set(row)
        self.toggle(row)
        self.schedule()

    def refresh(self) -> None:
        self.pending = None
        # Probe screen positions instead of traversing all photos on each scroll.
        height = self.tree.winfo_height()
        rows = dict.fromkeys(
            self.tree.identify_row(y) for y in range(0, height, 16)
        )
        used = 0
        for row in rows:
            if not row:
                continue
            bounds = self.tree.bbox(row, "checked")
            if not bounds:
                continue
            x, y, width, row_height = bounds
            # Never cover the heading or an adjacent column at the viewport edge.
            if x < 0 or x + width > self.tree.winfo_width():
                continue
            if self.tree.identify_row(y + 1) != row:
                continue
            state = self.tree.set(row, "checked")
            if used == len(self.buttons):
                button = tk.Canvas(self.tree, takefocus=False, borderwidth=0, highlightthickness=0)
                button.create_image(8, 33, anchor="w", tags="indicator")
                button.create_text(40, 33, anchor="w", font="TkDefaultFont", tags="label")
                for sequence in ("<MouseWheel>", "<Shift-MouseWheel>"):
                    button.bind(sequence, lambda e, s=sequence: self.tree.event_generate(s, delta=e.delta))
                for sequence in ("<Button-4>", "<Button-5>"):
                    button.bind(sequence, lambda e, s=sequence: self.tree.event_generate(s))
                self.buttons.append(button)
            button = self.buttons[used]
            used += 1
            checked = state == "対象"
            unavailable = state == "選択不可"
            disabled = unavailable or self.is_busy()
            background = "#ffffff" if checked else "#f0f1f2"
            foreground = "#202830" if checked else "#666d75"
            icon = self.icons[(2 if disabled else 0) + int(checked)]
            button.configure(background=background)
            button.itemconfigure("indicator", image=icon)
            button.itemconfigure("label", text=state, fill="#8b939d" if disabled else foreground)
            button.coords("indicator", 8, row_height // 2)
            button.coords("label", 40, row_height // 2)
            button.bind("<Button-1>", lambda e, r=row, enabled=not disabled:
                        self._activate(r) if enabled else None)
            button.place(x=x, y=y, width=width, height=min(row_height, height - y))
        for button in self.buttons[used:]:
            button.place_forget()
