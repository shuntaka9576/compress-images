from types import SimpleNamespace

from target_checks import TargetChecks


class Button:
    def __init__(self, *args, **kwargs):
        self.options = {}
        self.bindings = {}
        self.visible = False

    def bind(self, sequence, command):
        self.bindings[sequence] = command

    def create_image(self, *args, **kwargs):
        pass

    def create_text(self, *args, **kwargs):
        pass

    def coords(self, *args):
        pass

    def itemconfigure(self, tag, **kwargs):
        self.options.update(kwargs)

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def place(self, **kwargs):
        self.visible = True

    def place_forget(self):
        self.visible = False


def test_visible_controls_are_reused_when_scrolling_500_photos(monkeypatch):
    monkeypatch.setattr("target_checks.tk.Canvas", Button)
    viewport = {"start": 0, "count": 3}
    states = {"498": "対象外", "499": "選択不可"}
    checks = TargetChecks.__new__(TargetChecks)
    checks.icons = ["off", "on", "disabled-off", "disabled-on"]
    checks.buttons = []
    checks.pending = None
    checks.is_busy = lambda: False
    activated = []
    checks._activate = activated.append

    def identify(y):
        index = (y - 24) // 66
        return str(viewport["start"] + index) if 0 <= index < viewport["count"] else ""

    checks.tree = SimpleNamespace(
        winfo_height=lambda: 230,
        winfo_width=lambda: 800,
        identify_row=identify,
        selection=lambda: (),
        bbox=lambda row, column: (82, 24 + (int(row) - viewport["start"]) * 66, 108, 66),
        set=lambda row, column: states.get(row, "対象"),
    )
    checks.refresh()
    pool = checks.buttons.copy()
    assert len(pool) == 3
    assert all(button.visible for button in pool)

    viewport["start"] = 497
    checks.refresh()
    assert checks.buttons == pool
    assert [b.options["text"] for b in pool] == ["対象", "対象外", "選択不可"]
    assert pool[2].options["image"] == "disabled-off"
    pool[2].bindings["<Button-1>"](None)
    assert activated == []
    pool[1].bindings["<Button-1>"](None)
    assert activated == ["498"]

    checks.is_busy = lambda: True
    checks.refresh()
    assert all(b.options["image"].startswith("disabled-") for b in pool)

    viewport["count"] = 1
    checks.refresh()
    assert [b.visible for b in pool] == [True, False, False]

    viewport["count"] = 0
    checks.refresh()
    assert not any(b.visible for b in pool)
