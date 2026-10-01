import sys
import ctypes
import datetime
import traceback
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from window import MainWindow

# Frozen (PyInstaller) builds point __file__ into a temp dir; use the exe's folder instead.
_base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
_crash_log = _base / 'crash.log'


def _install_crash_logger():
    """Without this, PyQt6 silently aborts the whole process on an unhandled
    exception raised inside a Qt slot — no dialog, no trace, it just vanishes.
    A custom excepthook makes PyQt6 log and keep running instead of aborting."""
    def _hook(exc_type, exc_value, exc_tb):
        try:
            with open(_crash_log, 'a', encoding='utf-8') as f:
                f.write(f"\n--- {datetime.datetime.now().isoformat()} ---\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except OSError:
            pass
        traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def main():
    _install_crash_logger()

    # Per-monitor DPI awareness so coordinates match pyautogui's view of the screen
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("CompAssistant")
    app.setStyle("Fusion")

    # Set app icon (works for taskbar and window title bar)
    _base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    icon_path = _base / 'icon.ico'
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
