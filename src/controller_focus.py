from gi.repository import Gtk, Adw


class ControllerFocusTracker:
    """Small reusable helper for controller-based focus cycling.

    Keeps a list of focusable widgets, applies a CSS outline to the currently
    focused widget, and handles D-pad up/down cycling.  Each page still
    decides *which* widgets are focusable, but the cycling logic is shared.
    """

    def __init__(self, css_class: str = "controller-focus"):
        self._widgets: list[Gtk.Widget] = []
        self._index = -1
        self._css_class = css_class

    def set_widgets(self, widgets: list[Gtk.Widget]):
        """Replace the focus list.  Try to keep focus on the same widget."""
        old_widget = self.current_widget()
        self._clear_outline()
        self._widgets = [w for w in widgets if w is not None and w.get_sensitive()]
        if old_widget is not None and old_widget in self._widgets:
            self._index = self._widgets.index(old_widget)
        else:
            self._index = -1

    def current_widget(self) -> Gtk.Widget | None:
        if 0 <= self._index < len(self._widgets):
            return self._widgets[self._index]
        return None

    def cycle(self, delta: int):
        if not self._widgets:
            return
        self._clear_outline()
        if self._index < 0:
            self._index = 0 if delta >= 0 else len(self._widgets) - 1
        else:
            self._index = (self._index + delta) % len(self._widgets)
        self._apply_outline()

    def focus_first(self):
        if self._widgets:
            self._clear_outline()
            self._index = 0
            self._apply_outline()

    def move_to_widget(self, widget: Gtk.Widget | None):
        if widget is None or widget not in self._widgets:
            return
        self._clear_outline()
        self._index = self._widgets.index(widget)
        self._apply_outline()

    def _clear_outline(self):
        widget = self.current_widget()
        if widget is not None:
            widget.remove_css_class(self._css_class)

    def _apply_outline(self):
        widget = self.current_widget()
        if widget is not None:
            widget.add_css_class(self._css_class)
            widget.grab_focus()


def adjust_focused_widget(widget: Gtk.Widget, delta: int):
    """Adjust a SpinRow/ComboRow/SwitchRow value by delta via controller."""
    if isinstance(widget, Adw.SpinRow):
        adj = widget.get_adjustment()
        if adj is not None:
            widget.set_value(widget.get_value() + adj.get_step_increment() * delta)
    elif isinstance(widget, Adw.ComboRow):
        model = widget.get_model()
        if model is not None:
            new_idx = widget.get_selected() + delta
            if 0 <= new_idx < model.get_n_items():
                widget.set_selected(new_idx)
    elif isinstance(widget, Adw.SwitchRow):
        widget.set_active(not widget.get_active())
