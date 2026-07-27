from gi.repository import Adw, Gtk, GObject, GLib
from models import TrainingPlan, Exercise, TrainingSession, ExerciseLog
from data_store import DataStore
from timer_core import TimerCore
from sound import sound_player
from ui_scaling import apply_scaling
from controller_focus import ControllerFocusTracker, adjust_focused_widget
from exercise_picker import ExercisePicker
from settings import app_settings
from datetime import datetime


class TrainingPlanPage(Adw.Bin):
    def __init__(self, data_store: DataStore, **kwargs):
        super().__init__(**kwargs)
        self._store = data_store
        self._plans: list[TrainingPlan] = []
        self._running_session: TrainingSession | None = None
        self._running_plan: TrainingPlan | None = None
        self._current_exercise_idx = 0
        self._current_round = 1
        self._total_rounds = 1
        self._phase = "exercise"
        self._exercise_start_time: float = 0
        self._timer = TimerCore()
        self._timer.on_tick = self._on_timer_tick
        self._timer.on_finished = self._on_timer_finished
        self._editing_plan_id: str | None = None
        self._editor_exercises: list[Exercise] = []
        self._exercise_rows: list[Adw.ExpanderRow] = []

        self._editor_focus = ControllerFocusTracker()
        self._list_focus = ControllerFocusTracker()
        self._runner_focus = ControllerFocusTracker()

        self._build_ui()
        self.refresh_plans()

    def _build_ui(self):
        self._nav = Adw.NavigationView()
        self._nav.connect("popped", self._on_nav_popped)

        self._build_list_page()
        self._build_editor_page()
        self._build_runner_page()
        self._build_summary_page()

        self.set_child(self._nav)

    # ---- List page --------------------------------------------------------

    def _build_list_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        new_btn = Gtk.Button(label="New Plan", css_classes=["suggested-action"], halign=Gtk.Align.START)
        new_btn.connect("clicked", self._on_new_plan)
        box.append(new_btn)
        self._new_plan_btn = new_btn

        self._list_stack = Gtk.Stack(vhomogeneous=True)
        self._list_stack.set_vexpand(True)

        scrolled = Gtk.ScrolledWindow()
        self._plan_list_box = Gtk.ListBox(css_classes=["boxed-list"])
        self._plan_list_box.set_activate_on_single_click(True)
        self._plan_list_box.connect("row-activated", self._on_plan_activated)
        scrolled.set_child(self._plan_list_box)
        self._list_stack.add_named(scrolled, "list")

        empty_label = Gtk.Label(label="No plans yet. Create one!", css_classes=["dim-label"])
        empty_label.set_vexpand(True)
        self._list_stack.add_named(empty_label, "empty")

        box.append(self._list_stack)

        self._plan_row_star_buttons: dict[str, Gtk.Button] = {}

        io_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.START)
        self._export_btn = Gtk.Button(label="Export", halign=Gtk.Align.START)
        self._export_btn.connect("clicked", lambda _: self._on_export_plans())
        io_box.append(self._export_btn)
        self._import_btn = Gtk.Button(label="Import", halign=Gtk.Align.START)
        self._import_btn.connect("clicked", lambda _: self._on_import_plans())
        io_box.append(self._import_btn)
        box.append(io_box)

        self._list_page = Adw.NavigationPage(title="Training Plans")
        self._list_page.set_child(box)
        self._nav.add(self._list_page)

    # ---- Editor page ------------------------------------------------------

    def _build_editor_page(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar.add_top_bar(header)

        save_btn = Gtk.Button(label="Save", css_classes=["suggested-action"])
        save_btn.connect("clicked", self._on_save_plan)
        header.pack_end(save_btn)
        self._editor_save_btn = save_btn

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        self._plan_name_entry = Adw.EntryRow(title="Plan Name")
        name_group = Adw.PreferencesGroup()
        name_group.add(self._plan_name_entry)

        self._favorite_switch = Adw.SwitchRow(
            title="Favorite",
            subtitle="Show this plan at the top of the list",
        )
        self._favorite_switch.connect("notify::active", self._on_favorite_switch_changed)
        name_group.add(self._favorite_switch)

        rounds_adj = Gtk.Adjustment(value=1, lower=1, upper=20, step_increment=1)
        self._total_rounds_spin = Adw.SpinRow(title="Total Rounds", subtitle="How many times to repeat all exercises", adjustment=rounds_adj)
        name_group.add(self._total_rounds_spin)

        rest_rounds_adj = Gtk.Adjustment(value=60, lower=0, upper=600, step_increment=5)
        self._rest_between_rounds_spin = Adw.SpinRow(title="Rest Between Rounds (seconds)", subtitle="Pause between rounds when total rounds > 1", adjustment=rest_rounds_adj)
        name_group.add(self._rest_between_rounds_spin)

        box.append(name_group)

        exercises_group_title = Adw.PreferencesGroup(title="Exercises")
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._editor_add_exercise_btn = Gtk.Button(label="Add Exercise", halign=Gtk.Align.START)
        self._editor_add_exercise_btn.connect("clicked", self._on_add_exercise)
        add_box.append(self._editor_add_exercise_btn)
        self._editor_browse_exercise_btn = Gtk.Button(label="Browse Exercises", halign=Gtk.Align.START)
        self._editor_browse_exercise_btn.connect("clicked", self._on_browse_add_exercise)
        add_box.append(self._editor_browse_exercise_btn)
        box.append(add_box)

        self._exercises_group = Adw.PreferencesGroup()
        box.append(self._exercises_group)

        actions_group = Adw.PreferencesGroup()

        run_btn = Adw.ButtonRow(title="Start Training")
        run_btn.connect("activated", self._on_run_plan)
        run_btn.add_css_class("suggested-action")
        actions_group.add(run_btn)
        self._editor_run_btn = run_btn

        save_row = Adw.ButtonRow(title="Save Plan")
        save_row.connect("activated", self._on_save_plan)
        actions_group.add(save_row)
        self._editor_save_row = save_row

        self._editor_delete_btn = Adw.ButtonRow(title="Delete Plan", css_classes=["destructive-action"])
        self._editor_delete_btn.connect("activated", self._on_confirm_delete_plan)
        actions_group.add(self._editor_delete_btn)
        box.append(actions_group)

        clamp.set_child(box)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)

        self._editor_page = Adw.NavigationPage(title="Edit Plan")
        self._editor_page.set_child(toolbar)

    # ---- Runner page ------------------------------------------------------

    def _build_runner_page(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        stop_btn = Gtk.Button(label="Stop")
        stop_btn.connect("clicked", lambda _: self._confirm_stop_workout())
        header.pack_end(stop_btn)
        self._runner_stop_btn = stop_btn
        toolbar.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, vexpand=True)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(16)
        box.set_margin_end(16)

        self._runner_plan_label = Gtk.Label(label="")
        self._runner_plan_label.add_css_class("title-2")
        box.append(self._runner_plan_label)

        self._runner_exercise_label = Gtk.Label(label="")
        self._runner_exercise_label.set_vexpand(True)
        self._runner_exercise_label.set_valign(Gtk.Align.CENTER)
        self._runner_exercise_label.add_css_class("title-1")
        box.append(self._runner_exercise_label)

        self._runner_phase_label = Gtk.Label(label="")
        self._runner_phase_label.add_css_class("heading")
        self._runner_phase_label.set_margin_top(6)
        box.append(self._runner_phase_label)

        self._runner_countdown = Gtk.Label(label="00:00")
        self._runner_countdown.set_margin_top(12)
        self._runner_countdown.set_margin_bottom(12)
        box.append(self._runner_countdown)

        runner_widget = self
        def _on_runner_realize(*args):
            root = runner_widget.get_root()
            if root is not None:
                w, h = root._font_dims()
                if w > 1 and h > 1:
                    runner_widget.update_fonts(w, h)
            runner_widget._runner_focus.set_widgets([
                runner_widget._reps_spin,
                runner_widget._runner_pause_btn,
                runner_widget._runner_skip_btn,
                runner_widget._runner_stop_btn,
            ])
        self.connect("realize", _on_runner_realize)

        self._runner_next_label = Gtk.Label(label="")
        self._runner_next_label.add_css_class("dim-label")
        box.append(self._runner_next_label)

        self._reps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._reps_spin = Adw.SpinRow(title="Reps completed")
        rep_adj = Gtk.Adjustment(value=0, lower=0, upper=9999, step_increment=1)
        self._reps_spin.set_adjustment(rep_adj)
        self._reps_box.append(self._reps_spin)
        done_reps_btn = Gtk.Button(label="Done", css_classes=["suggested-action"])
        done_reps_btn.connect("clicked", self._on_reps_done)
        self._reps_box.append(done_reps_btn)
        self._reps_revealer = Gtk.Revealer()
        self._reps_revealer.set_child(self._reps_box)
        self._reps_revealer.set_transition_type(Gtk.RevealerTransitionType.NONE)
        self._reps_revealer.set_reveal_child(False)
        box.append(self._reps_revealer)

        controls_group = Adw.PreferencesGroup()
        self._runner_pause_btn = Gtk.Button(label="Pause")
        self._runner_pause_btn.connect("clicked", self._on_runner_pause)
        self._runner_skip_btn = Gtk.Button(label="Skip", css_classes=["destructive-action"])
        self._runner_skip_btn.connect("clicked", self._on_runner_skip)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, halign=Gtk.Align.CENTER)
        btn_box.append(self._runner_pause_btn)
        btn_box.append(self._runner_skip_btn)
        controls_group.add(btn_box)
        box.append(controls_group)

        toolbar.set_content(box)

        self._runner_page = Adw.NavigationPage(title="Training")
        self._runner_page.set_child(toolbar)

    # ---- Summary page -----------------------------------------------------

    def _build_summary_page(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        clamp = Adw.Clamp()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        self._summary_title = Gtk.Label(label="Training Complete!", css_classes=["title-1"])
        box.append(self._summary_title)

        self._summary_plan_name = Gtk.Label(label="", css_classes=["title-2"])
        box.append(self._summary_plan_name)

        self._summary_info = Gtk.Label(label="", css_classes=["dim-label"])
        box.append(self._summary_info)

        self._summary_exercises_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ex_scrolled = Gtk.ScrolledWindow(vexpand=True)
        ex_scrolled.set_child(self._summary_exercises_box)
        box.append(ex_scrolled)

        clamp.set_child(box)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)

        self._summary_page = Adw.NavigationPage(title="Summary")
        self._summary_page.set_child(toolbar)

    def _on_nav_popped(self, nav, *args):
        visible_page = nav.get_visible_page()
        if visible_page == self._list_page:
            self.refresh_plans()
            self._focus_list_if_visible()
        self._refresh_hints()

    def _focus_list_if_visible(self):
        visible = self._nav.get_visible_page()
        if visible != self._list_page:
            return
        widgets = [self._new_plan_btn]
        if self._plans:
            for i in range(len(self._plans)):
                row = self._plan_list_box.get_row_at_index(i)
                if row is not None:
                    widgets.append(row)
        widgets.extend([self._export_btn, self._import_btn])
        self._list_focus.set_widgets(widgets)
        self._list_focus.focus_first()

    def on_page_visible(self):
        visible = self._nav.get_visible_page()
        if visible == self._list_page:
            self._focus_list_if_visible()

    # ---- Summary population ----------------------------------------------

    def _populate_summary(self, session: TrainingSession):
        self._summary_plan_name.set_label(session.plan_name)

        date_str = session.started_at.strftime("%Y-%m-%d %H:%M")
        finished_str = session.finished_at.strftime("%H:%M") if session.finished_at else "?"
        planned_min = session.total_planned_seconds // 60
        planned_sec = session.total_planned_seconds % 60
        actual_min = session.total_actual_seconds // 60
        actual_sec = session.total_actual_seconds % 60
        self._summary_info.set_label(
            f"{date_str} - {finished_str} | "
            f"Actual: {actual_min:02d}:{actual_sec:02d} / Planned: {planned_min:02d}:{planned_sec:02d}"
        )

        while child := self._summary_exercises_box.get_first_child():
            self._summary_exercises_box.remove(child)

        group = Adw.PreferencesGroup()
        show_rounds = session.total_rounds > 1
        group_title = "Exercises"
        if show_rounds:
            rbr_str = f", {session.rest_between_rounds_seconds}s rest between" if session.rest_between_rounds_seconds > 0 else ""
            group_title = f"Exercises ({session.total_rounds} rounds{rbr_str})"
        group.set_title(group_title)

        for ex_log in session.exercises:
            title = ex_log.exercise_name
            if show_rounds and ex_log.round_number > 1:
                title = f"R{ex_log.round_number}: {ex_log.exercise_name}"
            if ex_log.set_number and ex_log.set_number > 1:
                title += f" (Set {ex_log.set_number})"
            row = Adw.ActionRow(title=title)

            details = []
            if ex_log.planned_duration_seconds is not None:
                details.append(f"Time: {self._fmt_dur(ex_log.actual_duration_seconds)} / {self._fmt_dur(ex_log.planned_duration_seconds)}")
            elif ex_log.planned_reps is not None:
                actual = ex_log.actual_reps if ex_log.actual_reps is not None else "?"
                details.append(f"Reps: {actual} / {ex_log.planned_reps}")

            if ex_log.planned_weight_kg is not None and ex_log.planned_weight_kg > 0:
                details.append(f"Weight: {ex_log.planned_weight_kg:g}kg")

            details.append(f"Rest: {self._fmt_dur(ex_log.actual_rest_seconds)} / {self._fmt_dur(ex_log.rest_seconds)}")
            details.append(self._fmt_exercise_time(ex_log))

            row.set_subtitle(" | ".join(details))

            if not ex_log.completed:
                row.add_css_class("error")

            status_label = Gtk.Label(label="Done" if ex_log.completed else "Skipped")
            row.add_suffix(status_label)

            group.add(row)

        self._summary_exercises_box.append(group)

    @staticmethod
    def _fmt_dur(seconds) -> str:
        if seconds is None:
            return "--:--"
        s = max(0, int(seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    @staticmethod
    def _fmt_exercise_time(ex_log) -> str:
        if ex_log.started_at and ex_log.finished_at:
            start = ex_log.started_at.strftime("%H:%M")
            finish = ex_log.finished_at.strftime("%H:%M")
            return f"{start} - {finish} ({TrainingPlanPage._fmt_dur(ex_log.actual_duration_seconds)})"
        return f"Duration: {TrainingPlanPage._fmt_dur(ex_log.actual_duration_seconds)}"

    # ---- Navigation -------------------------------------------------------

    def _show_list(self):
        self._nav.pop_to_page(self._list_page)
        self._refresh_hints()

    def _show_editor(self, plan: TrainingPlan | None = None):
        self._editor_exercises = []
        for row in self._exercise_rows:
            self._exercises_group.remove(row)
        self._exercise_rows.clear()

        if plan:
            self._editing_plan_id = plan.id
            self._plan_name_entry.set_text(plan.name)
            self._favorite_switch.set_active(plan.is_favorite)
            self._total_rounds_spin.set_value(plan.total_rounds)
            self._rest_between_rounds_spin.set_value(plan.rest_between_rounds_seconds)
            self._editor_exercises = [Exercise.from_dict(e.to_dict()) for e in plan.exercises]
            self._editor_page.set_title("Edit Plan")
        else:
            self._editing_plan_id = None
            self._plan_name_entry.set_text("")
            self._favorite_switch.set_active(False)
            self._total_rounds_spin.set_value(1)
            self._rest_between_rounds_spin.set_value(60)
            self._editor_page.set_title("New Plan")

        for ex in self._editor_exercises:
            self._append_exercise_row(ex)

        self._nav.push(self._editor_page)
        self._refresh_editor_focus()
        self._editor_focus.focus_first()

    def _on_favorite_switch_changed(self, switch, param):
        if self._editing_plan_id:
            plan = self._store.get_plan(self._editing_plan_id)
            if plan and plan.is_favorite != switch.get_active():
                plan.is_favorite = switch.get_active()
                self._store.save_plan(plan)

    def _append_exercise_row(self, exercise: Exercise):
        row = Adw.ExpanderRow(title=self._exercise_display_title(exercise))
        row.set_expanded(False)
        row.connect("notify::expanded", lambda *_: self._refresh_editor_focus())

        name_entry = Adw.EntryRow(title="Name")
        name_entry.set_text(exercise.name)
        row.add_row(name_entry)

        dur_adj = Gtk.Adjustment(value=exercise.duration_seconds or 0, lower=0, upper=3600, step_increment=5)
        dur_spin = Adw.SpinRow(title="Duration (seconds)", adjustment=dur_adj)
        row.add_row(dur_spin)

        reps_adj = Gtk.Adjustment(value=exercise.reps or 0, lower=0, upper=9999, step_increment=1)
        reps_spin = Adw.SpinRow(title="Reps", adjustment=reps_adj)
        row.add_row(reps_spin)

        sets_adj = Gtk.Adjustment(value=max(1, exercise.sets), lower=1, upper=20, step_increment=1)
        sets_spin = Adw.SpinRow(title="Sets", subtitle="Number of times to repeat this exercise", adjustment=sets_adj)
        row.add_row(sets_spin)

        weight_adj = Gtk.Adjustment(value=exercise.weight_kg or 0, lower=0, upper=999, step_increment=0.5)
        weight_spin = Adw.SpinRow(title="Weight (kg)", adjustment=weight_adj)
        weight_spin.set_digits(1)
        row.add_row(weight_spin)

        rest_adj = Gtk.Adjustment(value=exercise.rest_seconds, lower=0, upper=600, step_increment=5)
        rest_spin = Adw.SpinRow(title="Rest after (seconds)", adjustment=rest_adj)
        row.add_row(rest_spin)

        remove_btn = Gtk.Button(label="Remove", css_classes=["destructive-action"])
        remove_btn.set_margin_top(6)
        remove_btn.connect("clicked", lambda _, r=row, e=exercise: self._remove_exercise_row(r, e))
        row.add_row(remove_btn)

        row._reorder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row._reorder_box.set_margin_top(6)

        up_btn = Gtk.Button(icon_name="go-up-symbolic", css_classes=["flat"])
        up_btn.connect("clicked", lambda _, r=row: self._move_exercise_up(r))
        row._reorder_box.append(up_btn)

        down_btn = Gtk.Button(icon_name="go-down-symbolic", css_classes=["flat"])
        down_btn.connect("clicked", lambda _, r=row: self._move_exercise_down(r))
        row._reorder_box.append(down_btn)

        row.add_row(row._reorder_box)

        row._child_widgets = [name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, remove_btn, row._reorder_box]

        name_entry.connect("changed", lambda *_: self._sync_exercise_from_row(row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise))
        dur_spin.connect("changed", lambda *_: self._sync_exercise_from_row(row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise))
        reps_spin.connect("changed", lambda *_: self._sync_exercise_from_row(row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise))
        sets_spin.connect("changed", lambda *_: self._sync_exercise_from_row(row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise))
        weight_spin.connect("changed", lambda *_: self._sync_exercise_from_row(row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise))
        rest_spin.connect("changed", lambda *_: self._sync_exercise_from_row(row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise))

        self._exercise_rows.append(row)
        self._exercises_group.add(row)

    def _on_browse_exercise(self, row, exercise):
        def on_selected(name, image_key):
            for child in self._iter_expander_children(row):
                if isinstance(child, Adw.EntryRow) and child.get_title() == "Name":
                    child.set_text(name)
                    break
            exercise.name = name
            row.set_title(name or "New Exercise")
        picker = ExercisePicker(on_selected=on_selected)
        picker.present(self.get_native())
        self.get_native()._register_controller_dialog(picker)

    def _iter_expander_children(self, row):
        children = []
        child = row.get_first_child()
        while child:
            children.append(child)
            child = child.get_next_sibling()
        return children

    def _sync_exercise_from_row(self, row, name_entry, dur_spin, reps_spin, sets_spin, weight_spin, rest_spin, exercise):
        exercise.name = name_entry.get_text()
        dur_val = int(dur_spin.get_value())
        exercise.duration_seconds = dur_val if dur_val > 0 else None
        reps_val = int(reps_spin.get_value())
        exercise.reps = reps_val if reps_val > 0 else None
        exercise.sets = max(1, int(sets_spin.get_value()))
        weight_val = weight_spin.get_value()
        exercise.weight_kg = round(weight_val, 1) if weight_val > 0 else None
        exercise.rest_seconds = int(rest_spin.get_value())
        row.set_title(self._exercise_display_title(exercise))
        self._refresh_editor_focus()

    def _remove_exercise_row(self, row, exercise):
        if exercise in self._editor_exercises:
            self._editor_exercises.remove(exercise)
        self._exercises_group.remove(row)
        if row in self._exercise_rows:
            self._exercise_rows.remove(row)
        self._refresh_editor_focus()

    def _exercise_display_title(self, exercise: Exercise) -> str:
        parts = []
        if exercise.weight_kg is not None and exercise.weight_kg > 0:
            parts.append(f"{exercise.weight_kg:g}kg")
        if exercise.duration_seconds is not None and exercise.duration_seconds > 0:
            parts.append(f"{exercise.duration_seconds}s")
        if exercise.reps is not None and exercise.reps > 0:
            parts.append(f"{exercise.reps} reps")
        if exercise.sets and exercise.sets > 1:
            parts.append(f"{exercise.sets} sets")
        rest = f"[{exercise.rest_seconds}s rest]" if exercise.rest_seconds > 0 else ""
        if parts:
            return f"{exercise.name or 'New Exercise'} ({', '.join(parts)}) {rest}".strip()
        return f"{exercise.name or 'New Exercise'} {rest}".strip()

    def update_fonts(self, width, height):
        apply_scaling(
            [
                ("timer", self._runner_countdown),
                ("exercise", self._runner_exercise_label),
                ("info", self._runner_plan_label),
                ("info", self._runner_phase_label),
                ("info", self._runner_next_label),
            ],
            width,
            height,
        )

    def _move_exercise_up(self, row):
        idx = self._exercise_rows.index(row)
        if idx <= 0:
            return
        self._sync_all_exercises_from_rows()
        self._editor_exercises[idx], self._editor_exercises[idx - 1] = self._editor_exercises[idx - 1], self._editor_exercises[idx]
        self._rebuild_exercise_group()

    def _move_exercise_down(self, row):
        idx = self._exercise_rows.index(row)
        if idx < 0 or idx >= len(self._exercise_rows) - 1:
            return
        self._sync_all_exercises_from_rows()
        self._editor_exercises[idx], self._editor_exercises[idx + 1] = self._editor_exercises[idx + 1], self._editor_exercises[idx]
        self._rebuild_exercise_group()

    def _sync_all_exercises_from_rows(self):
        for i, row in enumerate(self._exercise_rows):
            exercise = self._editor_exercises[i]
            children = self._iter_expander_children(row)
            name_entry = None
            dur_spin = None
            reps_spin = None
            sets_spin = None
            weight_spin = None
            rest_spin = None
            for child in children:
                if isinstance(child, Adw.EntryRow) and child.get_title() == "Name":
                    name_entry = child
                elif isinstance(child, Adw.SpinRow) and child.get_title() == "Duration (seconds)":
                    dur_spin = child
                elif isinstance(child, Adw.SpinRow) and child.get_title() == "Reps":
                    reps_spin = child
                elif isinstance(child, Adw.SpinRow) and child.get_title() == "Sets":
                    sets_spin = child
                elif isinstance(child, Adw.SpinRow) and child.get_title() == "Weight (kg)":
                    weight_spin = child
                elif isinstance(child, Adw.SpinRow) and child.get_title() == "Rest after (seconds)":
                    rest_spin = child
            if name_entry:
                exercise.name = name_entry.get_text()
            if dur_spin:
                dur_val = int(dur_spin.get_value())
                exercise.duration_seconds = dur_val if dur_val > 0 else None
            if reps_spin:
                reps_val = int(reps_spin.get_value())
                exercise.reps = reps_val if reps_val > 0 else None
            if sets_spin:
                exercise.sets = max(1, int(sets_spin.get_value()))
            if weight_spin:
                weight_val = weight_spin.get_value()
                exercise.weight_kg = round(weight_val, 1) if weight_val > 0 else None
            if rest_spin:
                exercise.rest_seconds = int(rest_spin.get_value())

    def _rebuild_exercise_group(self):
        for row in self._exercise_rows:
            self._exercises_group.remove(row)
        self._exercise_rows.clear()
        for exercise in self._editor_exercises:
            self._append_exercise_row(exercise)

    def refresh_plans(self):
        row = self._plan_list_box.get_row_at_index(0)
        while row is not None:
            self._plan_list_box.remove(row)
            row = self._plan_list_box.get_row_at_index(0)

        self._plan_row_star_buttons.clear()
        self._plans = self._store.load_plans()
        self._plans.sort(key=lambda p: (-int(p.is_favorite), p.name.lower()))

        if not self._plans:
            self._list_stack.set_visible_child_name("empty")
            self._focus_list_if_visible()
            return

        for plan in self._plans:
            rounds_str = f" ({plan.total_rounds} rounds)" if plan.total_rounds > 1 else ""
            rbr_str = f", {plan.rest_between_rounds_seconds}s rest between rounds" if plan.total_rounds > 1 and plan.rest_between_rounds_seconds > 0 else ""
            row = Adw.ActionRow(title=plan.name, subtitle=f"{len(plan.exercises)} exercises{rounds_str}{rbr_str}")
            row.set_activatable(True)

            icon_name = "starred-symbolic" if plan.is_favorite else "non-starred-symbolic"
            star_btn = Gtk.Button(icon_name=icon_name, css_classes=["flat"])
            star_btn.set_tooltip_text("Toggle favorite")
            star_btn.set_valign(Gtk.Align.CENTER)
            star_btn.connect("clicked", self._on_toggle_favorite, plan.id)
            row.add_suffix(star_btn)
            self._plan_row_star_buttons[plan.id] = star_btn

            self._plan_list_box.append(row)

        self._list_stack.set_visible_child_name("list")
        self._focus_list_if_visible()

    def _on_plan_activated(self, list_box, row):
        idx = row.get_index()
        if idx < 0 or idx >= len(self._plans):
            return
        plan = self._plans[idx]
        if plan:
            self._show_editor(plan)

    def _on_new_plan(self, btn):
        self._show_editor(None)

    def _on_toggle_favorite(self, btn, plan_id: str):
        plan = self._store.get_plan(plan_id)
        if plan is None:
            return
        plan.is_favorite = not plan.is_favorite
        self._store.save_plan(plan)
        self.refresh_plans()

    def _on_export_plans(self):
        from csv_io import export_plans_json

        chooser = Gtk.FileChooserNative(
            title="Export Training Plans",
            transient_for=self.get_native(),
            action=Gtk.FileChooserAction.SAVE,
        )
        filter_json = Gtk.FileFilter()
        filter_json.add_pattern("*.json")
        filter_json.set_name("JSON files")
        chooser.add_filter(filter_json)
        chooser.set_current_name("training-plans.json")

        def on_response(chooser, response_id):
            if response_id == Gtk.ResponseType.ACCEPT:
                path = chooser.get_file().get_path()
                try:
                    export_plans_json(self._store.load_plans(), path)
                except Exception as e:
                    dialog = Adw.AlertDialog()
                    dialog.set_heading("Export failed")
                    dialog.set_body(str(e))
                    dialog.add_response("ok", "OK")
                    dialog.present(self.get_native())
            chooser.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_import_plans(self):
        from csv_io import import_plans_json

        chooser = Gtk.FileChooserNative(
            title="Import Training Plans",
            transient_for=self.get_native(),
            action=Gtk.FileChooserAction.OPEN,
        )
        filter_json = Gtk.FileFilter()
        filter_json.add_pattern("*.json")
        filter_json.set_name("JSON files")
        chooser.add_filter(filter_json)

        def on_response(chooser, response_id):
            if response_id == Gtk.ResponseType.ACCEPT:
                path = chooser.get_file().get_path()
                try:
                    imported = import_plans_json(path)
                    if not imported:
                        chooser.destroy()
                        return
                    existing_ids = {p.id for p in self._store.load_plans()}
                    new_plans = [p for p in imported if p.id not in existing_ids]
                    if new_plans:
                        plans = self._store.load_plans()
                        plans.extend(new_plans)
                        self._store.save_plans(plans)
                        self.refresh_plans()
                except Exception as e:
                    dialog = Adw.AlertDialog()
                    dialog.set_heading("Import failed")
                    dialog.set_body(str(e))
                    dialog.add_response("ok", "OK")
                    dialog.present(self.get_native())
            chooser.destroy()

        chooser.connect("response", on_response)
        chooser.show()

    def _on_add_exercise(self, btn):
        ex = Exercise(name="", duration_seconds=30, rest_seconds=30)
        self._editor_exercises.append(ex)
        self._append_exercise_row(ex)

    def _on_browse_add_exercise(self, btn):
        def on_selected(name, image_key):
            ex = Exercise(name=name, duration_seconds=30, rest_seconds=30)
            self._editor_exercises.append(ex)
            self._append_exercise_row(ex)
        picker = ExercisePicker(on_selected=on_selected)
        picker.present(self.get_native())
        self.get_native()._register_controller_dialog(picker)

    def _on_save_plan(self, btn):
        name = self._plan_name_entry.get_text().strip()
        if not name:
            return

        self._sync_all_exercises_from_rows()

        if self._editing_plan_id:
            plan = self._store.get_plan(self._editing_plan_id)
            if plan:
                plan.name = name
                plan.is_favorite = self._favorite_switch.get_active()
                plan.exercises = [e for e in self._editor_exercises if e.name.strip()]
                plan.total_rounds = int(self._total_rounds_spin.get_value())
                plan.rest_between_rounds_seconds = int(self._rest_between_rounds_spin.get_value())
                self._store.save_plan(plan)
        else:
            plan = TrainingPlan(name=name, exercises=[e for e in self._editor_exercises if e.name.strip()], total_rounds=int(self._total_rounds_spin.get_value()), rest_between_rounds_seconds=int(self._rest_between_rounds_spin.get_value()), is_favorite=self._favorite_switch.get_active())
            self._store.save_plan(plan)
            self._editing_plan_id = plan.id

    def _on_confirm_delete_plan(self, btn):
        if not self._editing_plan_id:
            return
        dialog = Adw.AlertDialog(
            heading="Delete Plan?",
            body="This action cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")

        def on_response(dialog, response):
            if response == "delete":
                self._on_delete_plan()

        dialog.connect("response", on_response)
        self.get_native()._register_controller_dialog(dialog, "delete", "cancel")
        dialog.present(self.get_native())

    def _on_delete_plan(self):
        if self._editing_plan_id:
            self._store.delete_plan(self._editing_plan_id)
            self._editing_plan_id = None
            self._show_list()

    def _on_run_plan(self, btn):
        name = self._plan_name_entry.get_text().strip()
        if not name or not self._editor_exercises:
            return

        self._on_save_plan(None)

        plan = None
        if self._editing_plan_id:
            plan = self._store.get_plan(self._editing_plan_id)
        if not plan:
            plans = self._store.load_plans()
            for p in plans:
                if p.name == name:
                    plan = p
                    break

        if not plan or not plan.exercises:
            return

        self._start_training(plan)

    def open_plan(self, plan: TrainingPlan):
        self._show_editor(plan)

    def _start_training(self, plan: TrainingPlan):
        self._running_plan = plan
        self._current_exercise_idx = 0
        self._current_round = 1
        self._current_set = 1
        self._total_rounds = plan.total_rounds or 1
        self._rest_between_rounds = plan.rest_between_rounds_seconds or 0
        self._phase = "exercise"

        self._running_session = TrainingSession(
            plan_id=plan.id,
            plan_name=plan.name,
            total_planned_seconds=plan.total_planned_seconds(),
            total_rounds=plan.total_rounds or 1,
            rest_between_rounds_seconds=plan.rest_between_rounds_seconds or 0,
            exercises=[],
        )

        self._update_runner_plan_label()
        self._runner_page.set_title(plan.name)
        self._nav.push(self._runner_page)
        self._start_current_exercise()
        root = self.get_root()
        if root is not None:
            w, h = root._font_dims()
            if w > 1 and h > 1:
                self.update_fonts(w, h)

    def _update_runner_plan_label(self):
        if self._total_rounds > 1:
            self._runner_plan_label.set_label(f"{self._running_plan.name} — Round {self._current_round}/{self._total_rounds}")
        else:
            self._runner_plan_label.set_label(self._running_plan.name)

    def _start_current_exercise(self):
        if self._current_exercise_idx >= len(self._running_plan.exercises):
            self._finish_training()
            return

        ex = self._running_plan.exercises[self._current_exercise_idx]
        self._phase = "exercise"
        self._runner_focus_idx = -1
        self._refresh_hints()
        exercise_label = ex.name
        if ex.weight_kg is not None and ex.weight_kg > 0:
            exercise_label += f"  ({ex.weight_kg:g}kg)"
        if ex.sets > 1:
            exercise_label += f"  (Set {self._current_set}/{ex.sets})"
        self._runner_exercise_label.set_label(exercise_label)

        next_label = self._compute_next_label()
        self._runner_next_label.set_label(next_label)

        now = datetime.now()
        self._exercise_start_time = now.timestamp()
        self._exercise_start_dt = now
        if ex.is_timed():
            self._reps_revealer.set_reveal_child(False)
            self._runner_phase_label.set_label("GO!")
            sound_player.play_sound(app_settings.get_sound("round_start_sound"))
            self._timer.start(ex.duration_seconds)
        else:
            self._reps_revealer.set_reveal_child(True)
            self._runner_phase_label.set_label("Reps")
            self._reps_spin.set_value(ex.reps or 0)
            self._runner_countdown.set_label(f"{ex.reps or 0}")

    def _compute_next_label(self) -> str:
        ex = self._running_plan.exercises[self._current_exercise_idx]
        if ex.sets > 1 and self._current_set < ex.sets:
            return f"Next: Set {self._current_set + 1}/{ex.sets}"
        next_idx = self._current_exercise_idx + 1
        if next_idx < len(self._running_plan.exercises):
            return f"Next: {self._running_plan.exercises[next_idx].name}"
        if self._current_round < self._total_rounds:
            next_round = self._current_round + 1
            return f"Next: Round {next_round}: {self._running_plan.exercises[0].name}"
        return "Last exercise!"

    def _start_rest(self):
        ex = self._running_plan.exercises[self._current_exercise_idx]
        if ex.rest_seconds > 0:
            self._phase = "rest"
            self._refresh_hints()
            self._runner_phase_label.set_label("REST")
            sound_player.play_sound(app_settings.get_sound("round_end_sound"))
            self._timer.start(ex.rest_seconds)
        else:
            self._advance_exercise()

    def _advance_exercise(self):
        ex = self._running_plan.exercises[self._current_exercise_idx]
        if ex.sets > 1 and self._current_set < ex.sets:
            self._current_set += 1
            self._start_current_exercise()
            return

        self._current_set = 1
        self._current_exercise_idx += 1
        if self._current_exercise_idx >= len(self._running_plan.exercises):
            if self._current_round < self._total_rounds:
                if self._rest_between_rounds > 0:
                    self._start_round_break()
                else:
                    self._current_round += 1
                    self._current_exercise_idx = 0
                    self._update_runner_plan_label()
                    sound_player.play_sound(app_settings.get_sound("round_start_sound"))
                    self._start_current_exercise()
            else:
                self._finish_training()
        else:
            self._start_current_exercise()

    def _start_round_break(self):
        self._phase = "round_break"
        self._runner_focus_idx = -1
        self._refresh_hints()
        self._current_round += 1
        self._current_exercise_idx = 0
        self._current_set = 1
        self._update_runner_plan_label()
        self._runner_exercise_label.set_label("Round Break")
        self._runner_phase_label.set_label(f"Next: Round {self._current_round}")
        self._reps_revealer.set_reveal_child(False)

        self._runner_next_label.set_label(f"Next: {self._running_plan.exercises[0].name}")
        sound_player.play_sound(app_settings.get_sound("round_end_sound"))
        self._timer.start(self._rest_between_rounds)

    def _finish_training(self):
        self._timer.stop()
        self._running_session.finished_at = datetime.now()
        self._running_session.total_actual_seconds = self._running_session.compute_total_actual_seconds()
        self._store.save_session(self._running_session)

        sound_player.play_sound(app_settings.get_sound("training_complete_sound"))

        self._populate_summary(self._running_session)
        self._summary_page.set_title("Complete")
        self._nav.pop_to_page(self._runner_page)
        self._nav.push(self._summary_page)
        self._refresh_hints()

        self._running_session = None
        self._running_plan = None

    def _on_timer_tick(self, remaining, total):
        mins = max(0, int(remaining)) // 60
        secs = max(0, int(remaining)) % 60
        self._runner_countdown.set_label(f"{mins:02d}:{secs:02d}")

    def _on_timer_finished(self):
        if self._phase == "round_break":
            sound_player.play_sound(app_settings.get_sound("round_start_sound"))
            self._start_current_exercise()
            return

        ex = self._running_plan.exercises[self._current_exercise_idx]
        sound_player.play_sound(app_settings.get_sound("exercise_complete_sound"))

        if self._phase == "exercise":
            finished_at = datetime.now()
            elapsed = int(finished_at.timestamp() - self._exercise_start_time)
            ex_log = ExerciseLog(
                exercise_name=ex.name,
                planned_duration_seconds=ex.duration_seconds,
                actual_duration_seconds=elapsed,
                planned_reps=ex.reps,
                actual_reps=int(self._reps_spin.get_value()) if not ex.is_timed() else None,
                planned_weight_kg=ex.weight_kg,
                actual_weight_kg=ex.weight_kg,
                rest_seconds=ex.rest_seconds,
                completed=True,
                round_number=self._current_round,
                started_at=self._exercise_start_dt,
                finished_at=finished_at,
                set_number=self._current_set,
            )
            self._running_session.exercises.append(ex_log)
            self._start_rest()
        elif self._phase == "rest":
            ex_log = self._running_session.exercises[-1] if self._running_session.exercises else None
            if ex_log:
                ex_log.actual_rest_seconds = ex.rest_seconds
            self._advance_exercise()

    def _on_reps_done(self, btn):
        ex = self._running_plan.exercises[self._current_exercise_idx]
        finished_at = datetime.now()
        elapsed = int(finished_at.timestamp() - self._exercise_start_time)
        ex_log = ExerciseLog(
            exercise_name=ex.name,
            planned_duration_seconds=ex.duration_seconds,
            actual_duration_seconds=elapsed,
            planned_reps=ex.reps,
            actual_reps=int(self._reps_spin.get_value()),
            planned_weight_kg=ex.weight_kg,
            actual_weight_kg=ex.weight_kg,
            rest_seconds=ex.rest_seconds,
            completed=True,
            round_number=self._current_round,
            started_at=self._exercise_start_dt,
            finished_at=finished_at,
            set_number=self._current_set,
        )
        self._running_session.exercises.append(ex_log)
        sound_player.play_sound(app_settings.get_sound("exercise_complete_sound"))
        self._reps_revealer.set_reveal_child(False)
        self._start_rest()

    def _on_runner_pause(self, btn):
        if self._timer.is_running:
            self._timer.pause()
            self._runner_pause_btn.set_label("Resume")
        else:
            self._timer.resume()
            self._runner_pause_btn.set_label("Pause")

    def _on_runner_skip(self, btn):
        self._timer.stop()

        if self._phase == "round_break":
            self._start_current_exercise()
            return

        ex = self._running_plan.exercises[self._current_exercise_idx]

        if self._phase == "exercise":
            finished_at = datetime.now()
            elapsed = int(finished_at.timestamp() - self._exercise_start_time)
            ex_log = ExerciseLog(
                exercise_name=ex.name,
                planned_duration_seconds=ex.duration_seconds,
                actual_duration_seconds=elapsed,
                planned_reps=ex.reps,
                actual_reps=int(self._reps_spin.get_value()) if not ex.is_timed() else None,
                planned_weight_kg=ex.weight_kg,
                actual_weight_kg=ex.weight_kg,
                rest_seconds=ex.rest_seconds,
                completed=False,
                round_number=self._current_round,
                started_at=self._exercise_start_dt,
                finished_at=finished_at,
                set_number=self._current_set,
            )
            self._running_session.exercises.append(ex_log)
            self._start_rest()
        elif self._phase == "rest":
            ex_log = self._running_session.exercises[-1] if self._running_session.exercises else None
            if ex_log:
                elapsed_rest = ex.rest_seconds - int(self._timer.remaining_seconds) if self._timer.remaining_seconds > 0 else 0
                ex_log.actual_rest_seconds = elapsed_rest
            self._advance_exercise()

    def _confirm_back_to_list(self):
        dialog = Adw.AlertDialog(
            heading="Return to Plan List?",
            body="Any unsaved workout progress will be lost."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("back", "Back to Plans")
        dialog.set_response_appearance("back", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        def on_response(dialog, response):
            if response == "back":
                self._show_list()
        dialog.connect("response", on_response)
        self.get_native()._register_controller_dialog(dialog, "back", "cancel")
        dialog.present(self.get_native())

    def _confirm_stop_workout(self):
        dialog = Adw.AlertDialog(
            heading="End Training?",
            body="You can view a summary of your completed exercises."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("end", "End Training")
        dialog.set_response_appearance("end", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        def on_response(dialog, response):
            if response == "end":
                self._finalize_training_stop()
        dialog.connect("response", on_response)
        self.get_native()._register_controller_dialog(dialog, "end", "cancel")
        dialog.present(self.get_native())

    def _finalize_training_stop(self):
        self._timer.stop()
        if self._running_session and not self._running_session.finished_at:
            self._running_session.finished_at = datetime.now()
            self._running_session.total_actual_seconds = self._running_session.compute_total_actual_seconds()
            self._store.save_session(self._running_session)
            sound_player.play_sound(app_settings.get_sound("training_complete_sound"))
            self._populate_summary(self._running_session)
            self._summary_page.set_title("Complete")
            self._nav.pop_to_page(self._runner_page)
            self._nav.push(self._summary_page)
            self._running_session = None
            self._running_plan = None
        else:
            self._show_list()

    # ---- Controller API ---------------------------------------------------

    def _refresh_hints(self):
        native = self.get_native()
        if native:
            native._update_hints_visibility()

    def get_controller_context(self):
        visible = self._nav.get_visible_page()
        if visible == self._runner_page:
            return "runner_exercise"
        if visible == self._list_page:
            return "list"
        if visible == self._editor_page:
            return "editor"
        if visible == self._summary_page:
            return "runner_summary"
        return ""

    def get_controller_sub_key(self):
        if self._nav.get_visible_page() == self._runner_page:
            return self._phase
        return ""

    def controller_a(self):
        visible = self._nav.get_visible_page()
        if visible == self._runner_page and self._phase == "exercise":
            ex = self._running_plan.exercises[self._current_exercise_idx]
            if not ex.is_timed():
                self._on_reps_done(None)
        elif visible == self._runner_page and self._phase in ("rest", "round_break"):
            self._on_runner_skip(None)
        elif visible == self._summary_page:
            self._show_list()
        elif visible == self._list_page:
            widget = self._list_focus.current_widget()
            if widget is None:
                self._focus_list_if_visible()
                widget = self._list_focus.current_widget()
            if widget is not None:
                if widget == self._new_plan_btn:
                    widget.emit("clicked")
                elif widget == self._export_btn:
                    widget.emit("clicked")
                elif widget == self._import_btn:
                    widget.emit("clicked")
                else:
                    idx = widget.get_index()
                    if 0 <= idx < len(self._plans):
                        self._show_editor(self._plans[idx])
        elif visible == self._editor_page:
            widget = self._editor_focus.current_widget()
            if isinstance(widget, Adw.ExpanderRow):
                widget.set_expanded(not widget.get_expanded())
            elif isinstance(widget, Gtk.Button):
                widget.emit("clicked")
            elif isinstance(widget, Adw.ButtonRow):
                widget.emit("activated")
            else:
                widget.grab_focus()

    def controller_b(self):
        visible = self._nav.get_visible_page()
        if visible == self._runner_page:
            self._confirm_stop_workout()
        elif visible in (self._summary_page, self._editor_page):
            self._show_list()

    def controller_start(self):
        visible = self._nav.get_visible_page()
        if visible == self._runner_page:
            self._on_runner_pause(None)
        elif visible == self._editor_page:
            self._on_run_plan(None)

    def controller_y(self):
        if self._nav.get_visible_page() == self._runner_page and self._phase in ("exercise", "rest"):
            self._on_runner_skip(None)

    def controller_back(self):
        self.controller_b()

    def _refresh_editor_focus(self):
        widgets = [self._plan_name_entry, self._favorite_switch, self._total_rounds_spin, self._rest_between_rounds_spin,
                   self._editor_add_exercise_btn, self._editor_browse_exercise_btn]
        for row in self._exercise_rows:
            widgets.append(row)
            if row.get_expanded():
                for child in getattr(row, '_child_widgets', []):
                    widgets.append(child)
        widgets.extend([self._editor_save_row, self._editor_delete_btn, self._editor_run_btn])
        self._editor_focus.set_widgets(widgets)

    def controller_dpad_up(self):
        visible = self._nav.get_visible_page()
        if visible == self._editor_page:
            self._editor_focus.cycle(-1)
        elif visible == self._list_page:
            self._list_focus.cycle(-1)
        elif visible == self._runner_page:
            self._runner_focus.cycle(-1)

    def controller_dpad_down(self):
        visible = self._nav.get_visible_page()
        if visible == self._editor_page:
            self._editor_focus.cycle(1)
        elif visible == self._list_page:
            self._list_focus.cycle(1)
        elif visible == self._runner_page:
            self._runner_focus.cycle(1)

    def controller_dpad_left(self):
        visible = self._nav.get_visible_page()
        if visible == self._runner_page:
            widget = self._runner_focus.current_widget()
            if widget == self._reps_spin:
                self._reps_spin.set_value(self._reps_spin.get_value() - 1)
            return
        if visible != self._editor_page:
            return
        widget = self._editor_focus.current_widget()
        adjust_focused_widget(widget, -1)

    def controller_dpad_right(self):
        visible = self._nav.get_visible_page()
        if visible == self._runner_page:
            widget = self._runner_focus.current_widget()
            if widget == self._reps_spin:
                self._reps_spin.set_value(self._reps_spin.get_value() + 1)
            return
        if visible != self._editor_page:
            return
        widget = self._editor_focus.current_widget()
        adjust_focused_widget(widget, 1)

    def controller_x(self):
        visible = self._nav.get_visible_page()
        if visible == self._editor_page:
            widget = self._editor_focus.current_widget()
            if isinstance(widget, Adw.ExpanderRow):
                widget.set_expanded(not widget.get_expanded())
            else:
                parent = widget.get_ancestor(Adw.ExpanderRow) if widget else None
                if parent is not None:
                    parent.set_expanded(False)
        elif visible == self._list_page:
            widget = self._list_focus.current_widget()
            if isinstance(widget, Adw.ActionRow):
                idx = widget.get_index()
                if 0 <= idx < len(self._plans):
                    plan = self._plans[idx]
                    star_btn = self._plan_row_star_buttons.get(plan.id)
                    if star_btn is not None:
                        star_btn.emit("clicked")
