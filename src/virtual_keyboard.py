from gi.repository import Gtk


# Compact 10-column QWERTY layout. Each row must have exactly 10 entries.
# Use tuples (label, key_type) where key_type is one of:
#   "char", "shift", "backspace", "enter", "space".
_LAYOUT = [
    [("1", "char"), ("2", "char"), ("3", "char"), ("4", "char"), ("5", "char"),
     ("6", "char"), ("7", "char"), ("8", "char"), ("9", "char"), ("0", "char")],
    [("q", "char"), ("w", "char"), ("e", "char"), ("r", "char"), ("t", "char"),
     ("y", "char"), ("u", "char"), ("i", "char"), ("o", "char"), ("p", "char")],
    [("a", "char"), ("s", "char"), ("d", "char"), ("f", "char"), ("g", "char"),
     ("h", "char"), ("j", "char"), ("k", "char"), ("l", "char"), ("⌫", "backspace")],
    [("Shift", "shift"), ("z", "char"), ("x", "char"), ("c", "char"), ("v", "char"),
     ("b", "char"), ("n", "char"), ("m", "char"), (",", "char"), ("↵", "enter")],
    [("Space", "space"), ("", "char"), ("", "char"), ("", "char"), ("", "char"),
     ("", "char"), ("", "char"), ("Close", "close"), ("", "char"), ("", "char")],
]


class VirtualKeyboard(Gtk.Box):
    def __init__(self, on_text_typed=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_text_typed = on_text_typed
        self._upper = False
        self._shift_locked = False
        self._buttons: dict[tuple[int, int], Gtk.Button] = {}
        self._key_types: dict[tuple[int, int], str] = {}
        self._cursor_x = 0
        self._cursor_y = 0

        title = Gtk.Label(label="Virtual Keyboard", css_classes=["title-2"])
        title.set_margin_bottom(4)
        self.append(title)

        self._grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        self._grid.set_halign(Gtk.Align.CENTER)
        self.append(self._grid)

        for row_idx, row_keys in enumerate(_LAYOUT):
            for col_idx, (label, key_type) in enumerate(row_keys):
                if key_type == "char" and not label:
                    continue
                btn = self._make_key_button(label, key_type)
                btn.set_focusable(True)
                btn.set_can_focus(True)
                width = 1
                if key_type == "space":
                    width = 7
                elif key_type == "close":
                    width = 3
                self._grid.attach(btn, col_idx, row_idx, width, 1)
                for w in range(width):
                    self._buttons[(row_idx, col_idx + w)] = btn
                self._key_types[(row_idx, col_idx)] = key_type
                btn.connect("clicked", self._on_key_clicked, row_idx, col_idx)

        self._set_initial_cursor()

    # ---- Public API --------------------------------------------------------

    def on_dpad(self, direction):
        rows = len(_LAYOUT)
        cols = 10
        if direction == "dpad_up":
            self._cursor_y = max(0, self._cursor_y - 1)
        elif direction == "dpad_down":
            self._cursor_y = min(rows - 1, self._cursor_y + 1)
        elif direction == "dpad_left":
            self._cursor_x = max(0, self._cursor_x - 1)
        elif direction == "dpad_right":
            self._cursor_x = min(cols - 1, self._cursor_x + 1)
        self._update_cursor()

    def on_confirm(self):
        btn = self._find_button(self._cursor_x, self._cursor_y)
        if btn:
            btn.activate()

    def on_backspace(self):
        if self._on_text_typed:
            self._on_text_typed("\b")

    def on_toggle_shift(self):
        self._shift_locked = not self._shift_locked
        self._upper = self._shift_locked
        self._update_shift_labels()

    def on_submit(self):
        if self._on_text_typed:
            self._on_text_typed("\n")

    # ---- Private -----------------------------------------------------------

    def _make_key_button(self, label, key_type):
        css_classes = ["keyboard-key"]
        if key_type != "char":
            css_classes.append("special")
        if key_type == "space":
            css_classes.append("space-key")
        btn = Gtk.Button(label=label, css_classes=css_classes)
        btn.set_hexpand(True)
        return btn

    def _set_initial_cursor(self):
        for col in range(10):
            if self._find_button(col, 0) is not None:
                self._cursor_x = col
                self._cursor_y = 0
                break
        self._update_cursor()

    def _find_button(self, x, y):
        return self._buttons.get((y, x))

    def _find_key_type(self, x, y):
        return self._key_types.get((y, x))

    def _update_cursor(self):
        for btn in self._buttons.values():
            btn.remove_css_class("selected")
        btn = self._find_button(self._cursor_x, self._cursor_y)
        if btn:
            btn.add_css_class("selected")
            btn.grab_focus()

    def _on_key_clicked(self, btn, row, col):
        key_type = self._find_key_type(col, row)
        if key_type == "shift":
            self.on_toggle_shift()
            return
        if key_type == "backspace":
            self.on_backspace()
            return
        if key_type == "enter":
            self.on_submit()
            return
        if key_type == "close":
            self.set_visible(False)
            return

        label = btn.get_label()
        if key_type == "space":
            text = " "
        else:
            text = label.upper() if self._upper else label
            if not self._shift_locked:
                self._upper = False
                self._update_shift_labels()

        if self._on_text_typed:
            self._on_text_typed(text)

    def _update_shift_labels(self):
        for row_idx, row_keys in enumerate(_LAYOUT):
            for col_idx, (label, key_type) in enumerate(row_keys):
                if key_type != "char" or not label:
                    continue
                btn = self._find_button(col_idx, row_idx)
                if btn:
                    btn.set_label(label.upper() if self._upper else label)

        shift_btn = self._find_button(0, 3)
        if shift_btn:
            shift_btn.set_label("SHIFT" if self._upper or self._shift_locked else "Shift")
