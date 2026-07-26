from gi.repository import Adw, Gtk, GObject, GLib
from timer_core import TimerCore
from sound import sound_player
from settings import app_settings
from models import RoundConfig
from ui_scaling import apply_scaling
from controller_focus import ControllerFocusTracker


class RoundTimerPage(Adw.Bin):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self._config = RoundConfig()
        self._timer = TimerCore()
        self._timer.on_tick = self._on_timer_tick
        self._timer.on_finished = self._on_timer_finished
        self._current_round = 0
        self._is_pause = False
        self._total_rounds = 0

        self._focus = ControllerFocusTracker()

        self._build_ui()

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True)
        main_box.set_margin_top(24)
        main_box.set_margin_bottom(24)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)

        config_group = Adw.PreferencesGroup()
        config_group.set_title("Configuration")

        self._rounds_spin = self._add_spin_row(config_group, "Rounds", 1, 50, 10, 1)
        self._round_time_spin = self._add_spin_row(config_group, "Round duration (seconds)", 10, 3600, 180, 10)
        self._pause_time_spin = self._add_spin_row(config_group, "Pause duration (seconds)", 0, 600, 60, 5)

        main_box.append(config_group)

        timer_group = Adw.PreferencesGroup()
        timer_group.set_title("Timer")
        timer_group.set_margin_top(12)

        self._round_label = Gtk.Label(label="Round 0 / 0")
        self._round_label.add_css_class("title-2")
        timer_group.add(self._round_label)

        self._phase_label = Gtk.Label(label="")
        self._phase_label.add_css_class("heading")
        timer_group.add(self._phase_label)

        self._countdown_label = Gtk.Label(label="00:00")
        self._countdown_label.set_vexpand(True)
        self._countdown_label.set_valign(Gtk.Align.CENTER)
        timer_group.add(self._countdown_label)

        main_box.append(timer_group)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER)
        btn_box.set_margin_bottom(12)

        self._start_btn = Gtk.Button(label="Start", css_classes=["suggested-action"])
        self._start_btn.connect("clicked", self._on_start_clicked)
        btn_box.append(self._start_btn)

        self._pause_btn = Gtk.Button(label="Pause", sensitive=False, css_classes=["flat"])
        self._pause_btn.connect("clicked", self._on_pause_clicked)
        btn_box.append(self._pause_btn)

        self._reset_btn = Gtk.Button(label="Reset", sensitive=False, css_classes=["flat"])
        self._reset_btn.connect("clicked", self._on_reset_clicked)
        btn_box.append(self._reset_btn)

        self._skip_btn = Gtk.Button(label="Skip", sensitive=False, css_classes=["destructive-action"])
        self._skip_btn.connect("clicked", self._on_skip_clicked)
        btn_box.append(self._skip_btn)

        main_box.append(btn_box)
        self.set_child(main_box)

        self._focus.set_widgets([
            self._rounds_spin, self._round_time_spin, self._pause_time_spin,
            self._start_btn, self._pause_btn, self._reset_btn, self._skip_btn,
        ])

        self.connect("realize", self._on_realize)

    def _on_realize(self, *args):
        GLib.idle_add(self._initial_font_update)

    def _initial_font_update(self):
        root = self.get_root()
        if root is None:
            return GLib.SOURCE_CONTINUE
        w, h = root._font_dims()
        if w <= 1 or h <= 1:
            return GLib.SOURCE_CONTINUE
        self.update_fonts(w, h)
        return GLib.SOURCE_REMOVE

    def update_fonts(self, width, height):
        apply_scaling(
            [
                ("timer", self._countdown_label),
                ("info", self._round_label),
                ("info", self._phase_label),
            ],
            width,
            height,
        )

    def _add_spin_row(self, group, title, lower, upper, value, step):
        adj = Gtk.Adjustment(value=value, lower=lower, upper=upper, step_increment=step)
        row = Adw.SpinRow(title=title, adjustment=adj)
        group.add(row)
        return row

    def _format_time(self, seconds: float) -> str:
        total = max(0, int(seconds))
        mins = total // 60
        secs = total % 60
        return f"{mins:02d}:{secs:02d}"

    def _on_start_clicked(self, btn):
        if self._timer.is_running:
            return

        if self._current_round == 0:
            self._config.rounds = int(self._rounds_spin.get_value())
            self._config.round_seconds = int(self._round_time_spin.get_value())
            self._config.pause_seconds = int(self._pause_time_spin.get_value())
            self._total_rounds = self._config.rounds
            self._current_round = 1
            self._is_pause = False
            self._start_round()
        else:
            self._timer.resume()

        self._update_buttons_running(True)

    def _start_round(self):
        self._round_label.set_label(f"Round {self._current_round} / {self._total_rounds}")
        self._phase_label.set_label("FIGHT")
        self._phase_label.remove_css_class("dim-label")
        sound_player.play_sound(app_settings.get_sound("round_start_sound"))
        self._timer.start(self._config.round_seconds)

    def _start_pause(self):
        self._phase_label.set_label("PAUSE")
        self._phase_label.add_css_class("dim-label")
        if self._config.pause_seconds > 0:
            sound_player.play_sound(app_settings.get_sound("round_end_sound"))
            self._timer.start(self._config.pause_seconds)
        else:
            self._advance_round()

    def _advance_round(self):
        self._current_round += 1
        if self._current_round > self._total_rounds:
            self._on_training_complete()
        else:
            self._start_round()

    def _on_timer_tick(self, remaining, total):
        self._countdown_label.set_label(self._format_time(remaining))

    def _on_timer_finished(self):
        sound_player.play_sound(app_settings.get_sound("countdown_tick_sound"))
        if self._is_pause:
            self._is_pause = False
            self._advance_round()
        else:
            if self._current_round >= self._total_rounds:
                self._on_training_complete()
            elif self._config.pause_seconds > 0:
                self._is_pause = True
                self._start_pause()
            else:
                self._advance_round()

    def _on_training_complete(self):
        self._phase_label.set_label("COMPLETE!")
        self._phase_label.remove_css_class("dim-label")
        self._countdown_label.set_label("00:00")
        self._current_round = 0
        self._update_buttons_running(False)
        sound_player.play_sound(app_settings.get_sound("training_complete_sound"))

    def _on_pause_clicked(self, btn):
        if self._timer.is_running:
            self._timer.pause()
            self._pause_btn.set_label("Resume")
        else:
            self._timer.resume()
            self._pause_btn.set_label("Pause")

    def _on_reset_clicked(self, btn):
        self._timer.stop()
        self._current_round = 0
        self._is_pause = False
        self._countdown_label.set_label("00:00")
        self._round_label.set_label("Round 0 / 0")
        self._phase_label.set_label("")
        self._update_buttons_running(False)

    def _on_skip_clicked(self, btn):
        self._timer.stop()
        sound_player.play_sound(app_settings.get_sound("countdown_tick_sound"))
        if self._is_pause:
            self._is_pause = False
            self._advance_round()
        else:
            if self._current_round >= self._total_rounds:
                self._on_training_complete()
            elif self._config.pause_seconds > 0:
                self._is_pause = True
                self._start_pause()
            else:
                self._advance_round()

    def _update_buttons_running(self, running: bool):
        self._pause_btn.set_sensitive(running)
        self._reset_btn.set_sensitive(running or self._current_round > 0)
        self._skip_btn.set_sensitive(running)
        if not running:
            self._pause_btn.set_label("Pause")
        self._rounds_spin.set_sensitive(not running and self._current_round == 0)
        self._round_time_spin.set_sensitive(not running and self._current_round == 0)
        self._pause_time_spin.set_sensitive(not running and self._current_round == 0)

        widgets = []
        for w in [self._rounds_spin, self._round_time_spin, self._pause_time_spin,
                  self._start_btn, self._pause_btn, self._reset_btn, self._skip_btn]:
            if w.get_sensitive():
                widgets.append(w)
        self._focus.set_widgets(widgets)

    # ---- Controller API ---------------------------------------------------

    def get_controller_context(self):
        return "timer"

    def controller_dpad_up(self):
        self._focus.cycle(-1)

    def controller_dpad_down(self):
        self._focus.cycle(1)

    def controller_dpad_left(self):
        widget = self._focus.current_widget()
        if isinstance(widget, Adw.SpinRow):
            widget.set_value(widget.get_value() + widget.get_adjustment().get_step_increment() * -1)

    def controller_dpad_right(self):
        widget = self._focus.current_widget()
        if isinstance(widget, Adw.SpinRow):
            widget.set_value(widget.get_value() + widget.get_adjustment().get_step_increment() * 1)
        elif isinstance(widget, Gtk.Button):
            current = self._focus.current_widget()
            buttons = [self._start_btn, self._pause_btn, self._reset_btn, self._skip_btn]
            if current in buttons:
                idx = buttons.index(current)
                idx = (idx + 1) % len(buttons)
                self._focus.move_to_widget(buttons[idx])

    def controller_start(self):
        if self._timer.is_running:
            self._on_pause_clicked(self._pause_btn)
        else:
            self._on_start_clicked(self._start_btn)

    def controller_x(self):
        self._on_reset_clicked(self._reset_btn)

    def controller_back(self):
        self._on_skip_clicked(self._skip_btn)

    def controller_a(self):
        self._on_start_clicked(self._start_btn)
