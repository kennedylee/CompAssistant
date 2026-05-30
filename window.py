import base64

import markdown as md_lib
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QSize
from PyQt6.QtGui import QFont, QPixmap, QKeySequence, QShortcut, QColor
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QStatusBar, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget, QComboBox,
)

from agent import AgentThread
from config import get_api_key, get_model, save_settings

# ── colour palette (GitHub dark) ───────────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
CARD     = "#21262d"
BORDER   = "#30363d"
USER_BG  = "#1f6feb"
AI_BG    = "#21262d"
TOOL_BG  = "#0d2818"
TOOL_BD  = "#1a5c32"
TEXT     = "#e6edf3"
MUTED    = "#8b949e"
ACCENT   = "#58a6ff"
SUCCESS  = "#3fb950"
DANGER   = "#f85149"

APP_CSS = f"""
* {{
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QWidget {{ background: {BG}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: {SURFACE}; width: 8px; border-radius: 4px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QTextEdit, QTextBrowser {{
    background: transparent; border: none; color: {TEXT};
    selection-background-color: {ACCENT};
}}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
"""

HEADER_CSS = f"background: {SURFACE}; border-bottom: 1px solid {BORDER};"
SEND_CSS = f"""
QPushButton {{
    background: {ACCENT}; color: {BG}; border: none;
    border-radius: 10px; font-weight: bold; font-size: 14px;
}}
QPushButton:hover {{ background: #79c0ff; }}
QPushButton:disabled {{ background: {BORDER}; color: {MUTED}; }}
"""
GHOST_BTN_CSS = f"""
QPushButton {{
    background: transparent; color: {MUTED};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 5px 12px; font-size: 13px;
}}
QPushButton:hover {{ background: {CARD}; color: {TEXT}; }}
"""
INPUT_CSS = f"""
QTextEdit {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 10px;
    padding: 10px 14px; font-size: 14px;
}}
QTextEdit:focus {{ border: 1px solid {ACCENT}; }}
"""


def _render_md(text: str) -> str:
    """Convert markdown to HTML with code block styling."""
    html = md_lib.markdown(
        text,
        extensions=["fenced_code", "tables", "nl2br"],
    )
    style = (
        f"body{{font-family:'Segoe UI',Arial;font-size:14px;color:{TEXT};"
        f"line-height:1.6;margin:0;padding:0;}}"
        f"code{{background:#2d333b;padding:2px 6px;border-radius:4px;"
        f"font-family:Consolas,'Courier New',monospace;font-size:13px;}}"
        f"pre{{background:#2d333b;padding:12px;border-radius:6px;"
        f"overflow-x:auto;margin:8px 0;}}"
        f"pre code{{background:transparent;padding:0;}}"
        f"table{{border-collapse:collapse;width:100%;}}"
        f"th,td{{border:1px solid {BORDER};padding:6px 10px;}}"
        f"th{{background:{CARD};}}"
        f"a{{color:{ACCENT};}}"
        f"blockquote{{border-left:3px solid {BORDER};margin:0;padding:0 12px;color:{MUTED};}}"
    )
    return f"<html><head><style>{style}</style></head><body>{html}</body></html>"


# ── message widgets ─────────────────────────────────────────────────────────

class UserMessageWidget(QFrame):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(60, 4, 16, 4)
        outer.addStretch()

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bubble.setStyleSheet(
            f"background:{USER_BG};color:{TEXT};border-radius:12px;"
            f"padding:10px 14px;line-height:1.5;"
        )
        outer.addWidget(bubble)


class AiMessageWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 4, 60, 4)

        self._buffer = ""
        self._streaming = False

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._browser.setStyleSheet(
            f"background:{AI_BG};border-radius:12px;padding:10px 14px;"
        )
        self._browser.document().contentsChanged.connect(self._auto_height)

        outer.addWidget(self._browser)
        outer.addStretch()

        # Batch timer for streaming updates
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(40)
        self._flush_timer.timeout.connect(self._flush)

    def _auto_height(self):
        doc_h = int(self._browser.document().size().height())
        self._browser.setFixedHeight(max(doc_h + 20, 40))

    def start_stream(self):
        self._streaming = True
        self._buffer = ""
        self._flush_timer.start()

    def append_chunk(self, chunk: str):
        self._buffer += chunk

    def _flush(self):
        if self._buffer:
            # During streaming show plain text for speed
            self._browser.setPlainText(self._buffer)

    def finish_stream(self):
        self._flush_timer.stop()
        self._streaming = False
        # Re-render with full markdown on completion
        if self._buffer.strip():
            self._browser.setHtml(_render_md(self._buffer))
        self._auto_height()

    def set_text(self, text: str):
        self._buffer = text
        self._browser.setHtml(_render_md(text))
        self._auto_height()

    def set_error(self, text: str):
        self._browser.setHtml(
            f"<p style='color:{DANGER};font-family:Segoe UI;'>{text}</p>"
        )
        self._auto_height()


class ToolWidget(QFrame):
    def __init__(self, tool_name: str, inputs: dict, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"QFrame{{background:{TOOL_BG};border:1px solid {TOOL_BD};"
            f"border-radius:8px;margin:2px 16px;}}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        title = QLabel(f"  {tool_name}")
        title.setStyleSheet(
            f"color:{SUCCESS};font-weight:bold;font-size:12px;"
            f"background:transparent;border:none;"
        )
        layout.addWidget(title)

        self._status = QLabel("Running…")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color:{MUTED};font-size:12px;background:transparent;border:none;"
        )
        layout.addWidget(self._status)

        self._img_label = None

    def set_result(self, result: dict):
        out = result.get("output", "")
        self._status.setText(out[:300] + ("…" if len(out) > 300 else ""))

        if "image" in result:
            data = base64.b64decode(result["image"])
            px = QPixmap()
            px.loadFromData(data)
            if px.width() > 520:
                px = px.scaledToWidth(520, Qt.TransformationMode.SmoothTransformation)
            if self._img_label is None:
                self._img_label = QLabel()
                self._img_label.setStyleSheet("background:transparent;border:none;")
                self.layout().addWidget(self._img_label)
            self._img_label.setPixmap(px)


# ── confirmation dialog ──────────────────────────────────────────────────────

class ConfirmDialog(QDialog):
    """Shown before running PowerShell commands or overwriting files."""

    _RISK_STYLE = {
        # (banner_bg, banner_text_color, banner_icon, allow_bg, allow_hover, allow_label)
        "high":   ("#3d0000", DANGER,   "🔴", DANGER,   "#ff6b6b", "Allow Anyway"),
        "medium": ("#2d1f00", "#e3b341","🟡", "#b45309", "#d97706", "Allow"),
        "normal": (None,      None,     None, "#2ea043", "#3fb950", "Allow"),
    }

    def __init__(self, title: str, body: str,
                 risk_level: str = "normal", risk_detail: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Action")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            f"QDialog{{background:{SURFACE};color:{TEXT};}}"
            f"QLabel{{color:{TEXT};background:transparent;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)

        banner_bg, banner_fg, banner_icon, allow_bg, allow_hover, allow_label = \
            self._RISK_STYLE.get(risk_level, self._RISK_STYLE["normal"])

        # Risk banner — only shown for high / medium
        if risk_level in ("high", "medium") and risk_detail:
            banner = QFrame()
            banner.setStyleSheet(
                f"QFrame{{background:{banner_bg};border:1px solid {banner_fg};"
                f"border-radius:6px;padding:0px;}}"
            )
            b_lay = QHBoxLayout(banner)
            b_lay.setContentsMargins(12, 10, 12, 10)
            b_lay.setSpacing(10)

            icon_lbl = QLabel(banner_icon)
            icon_lbl.setFont(QFont("Segoe UI Emoji", 14))
            icon_lbl.setStyleSheet("background:transparent;border:none;")
            b_lay.addWidget(icon_lbl)

            risk_lbl = QLabel(risk_detail)
            risk_lbl.setWordWrap(True)
            risk_lbl.setStyleSheet(
                f"color:{banner_fg};font-weight:bold;font-size:13px;"
                f"background:transparent;border:none;"
            )
            b_lay.addWidget(risk_lbl, stretch=1)
            lay.addWidget(banner)

        # Header: icon + title
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        warn = QLabel("⚠")
        warn.setFont(QFont("Segoe UI Emoji", 18))
        warn.setStyleSheet(f"color:#e3b341;background:transparent;")
        hdr.addWidget(warn)
        lbl = QLabel(title)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size:14px;font-weight:bold;color:{TEXT};")
        hdr.addWidget(lbl, stretch=1)
        lay.addLayout(hdr)

        # Command / file preview
        body_box = QTextEdit()
        body_box.setReadOnly(True)
        body_box.setPlainText(body)
        body_box.setFixedHeight(130)
        body_box.setStyleSheet(
            f"background:{BG};color:{TEXT};border:1px solid {BORDER};"
            f"border-radius:6px;padding:8px;"
            f"font-family:Consolas,'Courier New',monospace;font-size:13px;"
        )
        lay.addWidget(body_box)

        # Buttons — Cancel is the safe default
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(GHOST_BTN_CSS)
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(self.reject)
        allow_btn = QPushButton(allow_label)
        allow_btn.setStyleSheet(
            f"QPushButton{{background:{allow_bg};color:white;border:none;"
            f"border-radius:6px;padding:7px 18px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{allow_hover};}}"
        )
        allow_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(allow_btn)
        lay.addLayout(btn_row)


# ── settings dialog ─────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self.setStyleSheet(
            f"QDialog{{background:{SURFACE};color:{TEXT};}}"
            f"QLabel{{color:{TEXT};background:transparent;}}"
            f"QLineEdit,QComboBox{{background:{BG};color:{TEXT};"
            f"border:1px solid {BORDER};border-radius:6px;padding:7px;font-size:13px;}}"
            f"QPushButton{{background:{ACCENT};color:{BG};border:none;"
            f"border-radius:6px;padding:7px 14px;font-weight:bold;}}"
            f"QPushButton:hover{{background:#79c0ff;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(14)

        lay.addWidget(_bold_label("Anthropic API Key"))
        self.key_input = QLineEdit(get_api_key())
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("sk-ant-…")
        lay.addWidget(self.key_input)

        lay.addWidget(_bold_label("Model"))
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        ])
        current = get_model()
        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        lay.addWidget(self.model_combo)

        note = QLabel("Get your key at console.anthropic.com — stored locally in .env")
        note.setStyleSheet(f"color:{MUTED};font-size:12px;")
        lay.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def get_values(self):
        return self.key_input.text().strip(), self.model_combo.currentText()


def _bold_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight:bold;font-size:13px;")
    return lbl


# ── input box with Ctrl+Enter submit ────────────────────────────────────────

class InputBox(QTextEdit):
    def __init__(self, on_submit, parent=None):
        super().__init__(parent)
        self._on_submit = on_submit
        self.setPlaceholderText("Ask me anything… (Shift+Enter for new line)")
        self.setAcceptRichText(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)  # Shift+Enter = new line
            else:
                self._on_submit()             # Enter = send
        else:
            super().keyPressEvent(event)


# ── main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CompAssistant")
        self.resize(960, 720)
        self.setStyleSheet(APP_CSS)

        self._history: list = []
        self._agent: AgentThread | None = None
        self._current_ai_widget: AiMessageWidget | None = None
        self._current_tool_widget: ToolWidget | None = None

        self._build_ui()
        if not get_api_key():
            QTimer.singleShot(300, self._open_settings)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(self._make_header())
        vbox.addWidget(self._make_chat_area(), stretch=1)
        vbox.addWidget(self._make_input_area())

        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status = sb
        sb.showMessage("Ready")

    def _make_header(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(HEADER_CSS)
        bar.setFixedHeight(60)
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 0, 18, 0)

        icon = QLabel("🤖")
        icon.setFont(QFont("Segoe UI Emoji", 18))
        icon.setStyleSheet("background:transparent;border:none;")
        h.addWidget(icon)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        t1 = QLabel("CompAssistant")
        t1.setStyleSheet(f"font-size:17px;font-weight:bold;background:transparent;border:none;")
        t2 = QLabel("AI Desktop Assistant")
        t2.setStyleSheet(f"font-size:11px;color:{MUTED};background:transparent;border:none;")
        titles.addWidget(t1)
        titles.addWidget(t2)
        h.addLayout(titles)
        h.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(GHOST_BTN_CSS)
        clear_btn.clicked.connect(self._clear_chat)
        h.addWidget(clear_btn)

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setStyleSheet(GHOST_BTN_CSS)
        settings_btn.clicked.connect(self._open_settings)
        h.addWidget(settings_btn)

        return bar

    def _make_chat_area(self) -> QScrollArea:
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._chat_pane = QWidget()
        self._chat_pane.setStyleSheet(f"background:{BG};")
        self._chat_vbox = QVBoxLayout(self._chat_pane)
        self._chat_vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._chat_vbox.setSpacing(6)
        self._chat_vbox.setContentsMargins(0, 14, 0, 14)

        welcome = QLabel(
            "Hello! I'm your AI desktop assistant. I can see your screen, control your "
            "mouse and keyboard, run commands, manage files, and handle virtually anything "
            "on your computer. What would you like me to do?"
        )
        welcome.setWordWrap(True)
        welcome.setStyleSheet(
            f"background:{CARD};color:{MUTED};border-radius:10px;"
            f"padding:14px;margin:6px 16px;font-size:13px;"
        )
        self._chat_vbox.addWidget(welcome)

        self._scroll.setWidget(self._chat_pane)
        return self._scroll

    def _make_input_area(self) -> QWidget:
        bar = QWidget()
        bar.setStyleSheet(f"background:{SURFACE};border-top:1px solid {BORDER};")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(10)

        self._input = InputBox(on_submit=self._send)
        self._input.setStyleSheet(INPUT_CSS)
        self._input.setFixedHeight(80)

        self._send_btn = QPushButton("Send")
        self._send_btn.setStyleSheet(SEND_CSS)
        self._send_btn.setFixedSize(QSize(80, 80))
        self._send_btn.clicked.connect(self._send)

        h.addWidget(self._input)
        h.addWidget(self._send_btn)
        return bar

    # ── actions ───────────────────────────────────────────────────────────

    def _send(self):
        text = self._input.toPlainText().strip()
        if not text or self._agent is not None:
            return
        self._input.clear()

        # User bubble
        self._chat_vbox.addWidget(UserMessageWidget(text))

        # Empty AI bubble ready for streaming
        self._current_ai_widget = AiMessageWidget()
        self._current_ai_widget.start_stream()
        self._chat_vbox.addWidget(self._current_ai_widget)
        self._scroll_bottom()

        self._send_btn.setEnabled(False)
        self._status.showMessage("Thinking…")

        self._agent = AgentThread(text, self._history)
        self._agent.chunk_received.connect(self._on_chunk)
        self._agent.tool_started.connect(self._on_tool_started)
        self._agent.tool_finished.connect(self._on_tool_finished)
        self._agent.turn_complete.connect(self._on_complete)
        self._agent.error_occurred.connect(self._on_error)
        self._agent.confirm_needed.connect(self._on_confirm_needed)
        self._agent.start()

    @pyqtSlot(str)
    def _on_chunk(self, chunk: str):
        if self._current_ai_widget:
            self._current_ai_widget.append_chunk(chunk)
        self._scroll_bottom()

    @pyqtSlot(str, dict)
    def _on_tool_started(self, tool_name: str, inputs: dict):
        # Finish current AI widget stream before showing tool
        if self._current_ai_widget:
            self._current_ai_widget.finish_stream()

        self._current_tool_widget = ToolWidget(tool_name, inputs)
        self._chat_vbox.addWidget(self._current_tool_widget)
        self._status.showMessage(f"Running tool: {tool_name}…")
        self._scroll_bottom()

    @pyqtSlot(str, dict)
    def _on_tool_finished(self, tool_name: str, result: dict):
        if self._current_tool_widget:
            self._current_tool_widget.set_result(result)

        # Fresh AI widget for the next response segment
        self._current_ai_widget = AiMessageWidget()
        self._current_ai_widget.start_stream()
        self._chat_vbox.addWidget(self._current_ai_widget)
        self._scroll_bottom()

    @pyqtSlot()
    def _on_complete(self):
        if self._current_ai_widget:
            self._current_ai_widget.finish_stream()
        # Adopt the agent's updated history
        if self._agent:
            self._history = list(self._agent.history)
        self._reset_input()
        self._status.showMessage("Ready")

    @pyqtSlot(str, str, str, str)
    def _on_confirm_needed(self, title: str, body: str, risk_level: str, risk_detail: str):
        dlg = ConfirmDialog(title, body, risk_level, risk_detail, self)
        approved = dlg.exec() == QDialog.DialogCode.Accepted
        if self._agent:
            self._agent.resolve_confirm(approved)

    @pyqtSlot(str)
    def _on_error(self, message: str):
        if self._current_ai_widget:
            self._current_ai_widget.finish_stream()
            self._current_ai_widget.set_error(message)
        self._reset_input()
        self._status.showMessage("Error — see message above", 6000)

    def _reset_input(self):
        self._agent = None
        self._send_btn.setEnabled(True)
        self._input.setFocus()

    def _clear_chat(self):
        # Remove all widgets except the welcome label (index 0)
        while self._chat_vbox.count() > 1:
            item = self._chat_vbox.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        self._history.clear()
        self._current_ai_widget = None
        self._status.showMessage("Conversation cleared", 2000)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key, model = dlg.get_values()
            if key:
                save_settings(key, model)
                self._status.showMessage("Settings saved", 3000)

    def _scroll_bottom(self):
        QTimer.singleShot(20, lambda: (
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            )
        ))
