#!/usr/bin/env python3
import sys
import os
import gi

sys.path.insert(0, "/app/share/training")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")

from gi.repository import Adw, Gtk, Gio

# Silence the common libadwaita dark-theme warning on systems that set the
# legacy GtkSettings key. libadwaita uses Adw.StyleManager instead.
Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", False)
from window import MainWindow
from settings import app_settings


class TrainingApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.NikolausB.WorkoutTimer",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(application=self)
        win.present()


def main():
    app = TrainingApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    main()