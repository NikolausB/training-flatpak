from gi.repository import Adw, Gtk
from settings import app_settings, save_settings, AppSettings, DEFAULT_SETTINGS
from sound import sound_player, AVAILABLE_SOUNDS


_DISPLAY_NAMES = {
    "beep": "Beep",
    "round_start": "Ding (Round Start)",
    "round_end": "Bell (Round End)",
    "exercise_complete": "Chime (Exercise Complete)",
    "training_complete": "Fanfare (Training Complete)",
    "none": "None (Silent)",
}

_EVENT_LABELS = {
    "round_start_sound": "Round Start Sound",
    "round_end_sound": "Round End / Pause Sound",
    "countdown_tick_sound": "Countdown Tick Sound",
    "exercise_complete_sound": "Exercise Complete Sound",
    "training_complete_sound": "Training Complete Sound",
}

_EVENT_SUBTITLES = {
    "round_start_sound": "Played when a round or exercise begins",
    "round_end_sound": "Played when a round ends or rest starts",
    "countdown_tick_sound": "Played on timer countdown transitions",
    "exercise_complete_sound": "Played when a single exercise is completed",
    "training_complete_sound": "Played when the entire training session finishes",
}

_SOUND_OPTIONS = list(AVAILABLE_SOUNDS) + ["none"]


class PreferencesDialog(Adw.Dialog):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Preferences")
        self.set_content_width(420)
        self.set_content_height(560)

        self._settings = AppSettings(**app_settings.to_dict())
        self._focus_tracker = _DialogFocusTracker()

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        save_btn = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(save_btn)

        toolbar.add_top_bar(header)

        self._page = Adw.PreferencesPage()
        self._build_sound_group()
        self._build_tabs_group()
        self._build_controller_group()

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._page)
        toolbar.set_content(scrolled)
        self.set_child(toolbar)

        self.connect("realize", self._on_realize)
        self.connect("closed", self._on_save_clicked)

    def _build_sound_group(self):
        group = Adw.PreferencesGroup(title="Sounds")
        group.set_description("Choose sounds played during training events")

        self._sound_switch = Adw.SwitchRow(title="Sound Enabled")
        self._sound_switch.set_active(self._settings.sound_enabled)
        self._sound_switch.connect("notify::active", self._on_sound_enabled_toggled)
        group.add(self._sound_switch)

        self._combo_rows: dict[str, Adw.ComboRow] = {}
        self._preview_rows: dict[str, Gtk.Button] = {}

        string_list = Gtk.StringList.new([_DISPLAY_NAMES.get(s, s) for s in _SOUND_OPTIONS])

        for event_key in _EVENT_LABELS:
            row = Adw.ComboRow(
                title=_EVENT_LABELS[event_key],
                subtitle=_EVENT_SUBTITLES[event_key],
            )
            row.set_model(string_list)

            current = getattr(self._settings, event_key)
            idx = self._sound_key_to_index(current)
            row.set_selected(idx)
            row.connect("notify::selected", self._on_combo_changed, event_key)
            row.set_sensitive(self._settings.sound_enabled)

            preview_btn = Gtk.Button(icon_name="media-playback-start-symbolic", css_classes=["flat"])
            preview_btn.set_valign(Gtk.Align.CENTER)
            preview_btn.connect("clicked", self._on_preview_clicked, event_key)
            preview_btn.set_sensitive(self._settings.sound_enabled)

            row.add_suffix(preview_btn)

            self._combo_rows[event_key] = row
            self._preview_rows[event_key] = preview_btn
            group.add(row)

        self._page.add(group)

    def _build_tabs_group(self):
        group = Adw.PreferencesGroup(title="Tabs")
        group.set_description("Choose which tabs are shown in the main view")

        self._home_switch = Adw.SwitchRow(
            title="Show Home Page",
            subtitle="Landing page with recent and recommended workouts",
        )
        self._home_switch.set_active(self._settings.show_home_page)
        group.add(self._home_switch)

        self._timer_switch = Adw.SwitchRow(
            title="Show Round Timer",
            subtitle="Configurable round timer with pause periods",
        )
        self._timer_switch.set_active(self._settings.show_timer_page)
        group.add(self._timer_switch)

        self._workout_switch = Adw.SwitchRow(
            title="Show Training Plans",
            subtitle="Training plan builder and runner",
        )
        self._workout_switch.set_active(self._settings.show_workout_page)
        group.add(self._workout_switch)

        self._ai_switch = Adw.SwitchRow(
            title="Show AI Coach",
            subtitle="AI-powered training plan generator (requires network access)",
        )
        self._ai_switch.set_active(self._settings.show_ai_page)
        group.add(self._ai_switch)

        self._page.add(group)

    def _build_controller_group(self):
        group = Adw.PreferencesGroup(title="Controller and Deck Mode")
        group.set_description("Settings for gamepad and Steam Deck compatibility")

        self._gamepad_switch = Adw.SwitchRow(
            title="Enable Gamepad",
            subtitle="Support for controllers and Steam Deck input",
        )
        self._gamepad_switch.set_active(self._settings.gamepad_enabled)
        group.add(self._gamepad_switch)

        self._hints_switch = Adw.SwitchRow(
            title="Show Button Hints",
            subtitle="Display controller button hints during workouts",
        )
        self._hints_switch.set_active(self._settings.gamepad_hints)
        group.add(self._hints_switch)

        self._deck_combo = Adw.ComboRow(
            title="Deck Mode",
            subtitle="Auto-detect or force Steam Deck UI scaling",
        )
        deck_items = Gtk.StringList.new(["Auto", "On", "Off"])
        self._deck_combo.set_model(deck_items)
        idx = {"auto": 0, "on": 1, "off": 2}.get(self._settings.deck_mode, 0)
        self._deck_combo.set_selected(idx)
        group.add(self._deck_combo)

        self._page.add(group)

    def _on_realize(self, *args):
        self._refresh_focus_widgets()
        self._focus_tracker.focus_first()

    def _refresh_focus_widgets(self):
        widgets = [self._sound_switch]
        widgets.extend(self._combo_rows.values())
        widgets.extend([
            self._home_switch,
            self._timer_switch,
            self._workout_switch,
            self._ai_switch,
            self._gamepad_switch,
            self._hints_switch,
            self._deck_combo,
        ])
        self._focus_tracker.set_widgets(widgets)

    def _sound_key_to_index(self, key: str) -> int:
        for i, s in enumerate(_SOUND_OPTIONS):
            if s == key:
                return i
        return 0

    def _index_to_sound_key(self, index: int) -> str:
        if 0 <= index < len(_SOUND_OPTIONS):
            return _SOUND_OPTIONS[index]
        return "beep"

    def _on_sound_enabled_toggled(self, switch, param):
        active = switch.get_active()
        self._settings.sound_enabled = active
        for event_key in self._combo_rows:
            self._combo_rows[event_key].set_sensitive(active)
            self._preview_rows[event_key].set_sensitive(active)

    def _on_combo_changed(self, combo_row, param, event_key):
        idx = combo_row.get_selected()
        key = self._index_to_sound_key(idx)
        setattr(self._settings, event_key, key)

    def _on_preview_clicked(self, btn, event_key):
        active = self._settings.sound_enabled
        if not active:
            return
        key = getattr(self._settings, event_key)
        if key == "none":
            return
        sound_player.play_sound(key)

    def _on_save_clicked(self, *args):
        global_settings = app_settings
        global_settings.sound_enabled = self._settings.sound_enabled
        for event_key in _EVENT_LABELS:
            setattr(global_settings, event_key, getattr(self._settings, event_key))
        global_settings.show_home_page = self._home_switch.get_active()
        global_settings.show_timer_page = self._timer_switch.get_active()
        global_settings.show_workout_page = self._workout_switch.get_active()
        global_settings.show_ai_page = self._ai_switch.get_active()
        global_settings.gamepad_enabled = self._gamepad_switch.get_active()
        global_settings.gamepad_hints = self._hints_switch.get_active()
        deck_idx = self._deck_combo.get_selected()
        global_settings.deck_mode = ["auto", "on", "off"][deck_idx]
        save_settings(global_settings)
        self.close()

    # ---- Controller API ---------------------------------------------------

    def controller_dpad_up(self):
        self._focus_tracker.cycle(-1)

    def controller_dpad_down(self):
        self._focus_tracker.cycle(1)

    def controller_dpad_left(self):
        self._adjust_focused(-1)

    def controller_dpad_right(self):
        self._adjust_focused(1)

    def _adjust_focused(self, delta):
        widget = self._focus_tracker.current_widget()
        if widget is None:
            return
        if isinstance(widget, Adw.ComboRow):
            model = widget.get_model()
            if model:
                new_idx = widget.get_selected() + delta
                if 0 <= new_idx < model.get_n_items():
                    widget.set_selected(new_idx)
        elif isinstance(widget, Adw.SwitchRow):
            widget.set_active(not widget.get_active())

    def controller_a(self):
        widget = self._focus_tracker.current_widget()
        if widget is None:
            return
        if isinstance(widget, Adw.SwitchRow):
            widget.set_active(not widget.get_active())
        elif isinstance(widget, Adw.ComboRow):
            model = widget.get_model()
            if model:
                widget.set_selected((widget.get_selected() + 1) % model.get_n_items())

    def controller_b(self):
        self.close()

    def controller_start(self):
        self._on_save_clicked()


class _DialogFocusTracker:
    def __init__(self, css_class="controller-focus"):
        self._widgets = []
        self._index = -1
        self._css_class = css_class

    def set_widgets(self, widgets):
        old = self.current_widget()
        self._clear_outline()
        self._widgets = [w for w in widgets if w is not None and w.get_sensitive()]
        if old is not None and old in self._widgets:
            self._index = self._widgets.index(old)
        else:
            self._index = -1

    def current_widget(self):
        if 0 <= self._index < len(self._widgets):
            return self._widgets[self._index]
        return None

    def focus_first(self):
        if self._widgets:
            self._clear_outline()
            self._index = 0
            self._apply_outline()

    def cycle(self, delta):
        if not self._widgets:
            return
        self._clear_outline()
        if self._index < 0:
            self._index = 0 if delta >= 0 else len(self._widgets) - 1
        else:
            self._index = (self._index + delta) % len(self._widgets)
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
