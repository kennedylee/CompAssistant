import sys
import ctypes
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from window import MainWindow


def main():
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
