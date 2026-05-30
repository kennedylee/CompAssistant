import re
import threading

import pyautogui
from PyQt6.QtCore import QThread, pyqtSignal

import anthropic
from config import get_api_key, get_model
from tools import TOOL_DEFINITIONS, execute_tool

_w, _h = pyautogui.size()

SYSTEM_PROMPT = f"""You are a powerful AI desktop assistant with full access to the user's Windows computer.

Screen resolution: {_w}x{_h} pixels

Your capabilities:
- See the screen (screenshot tool)
- Control the mouse: click, double-click, right-click, move, scroll, drag
- Type text and press keyboard shortcuts
- Read and write any file
- Run PowerShell commands for system administration
- Get system info: processes, disk, memory, network, startup items
- Open applications, files, and URLs
- Access and set the clipboard

How to work:
1. For visual tasks, take a screenshot first to see the current state.
2. Before destructive actions (deleting files, major settings changes), describe what you are about to do.
3. Prefer PowerShell commands for efficiency when a GUI interaction is not needed.
4. After completing a multi-step task, give a brief summary of what was done.
5. If something does not work as expected, take a screenshot and try again.

You are expected to ACTUALLY DO things, not just explain how to do them.
"""


def _content_to_params(content) -> list:
    """Convert API response content blocks to plain dicts for history storage."""
    result = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
    return result


# (pattern, human description) — checked case-insensitively against the command
_HIGH_CMD = [
    (r"\bRemove-Item\b",                    "Deletes files or directories"),
    (r"\brd\b|\brmdir\b",                   "Removes directories"),
    (r"\bFormat-\w+",                       "Formats a drive or volume"),
    (r"\bClear-Disk\b|\bInitialize-Disk\b", "Wipes or reinitializes a disk"),
    (r"\bInvoke-Expression\b|\biex\b",      "Executes dynamic or downloaded code"),
    (r"(Invoke-WebRequest|curl|wget).*\|.*(iex|Invoke-Expression)",
                                            "Downloads and immediately executes code"),
    (r"\bRemove-LocalUser\b",               "Deletes a local user account"),
    (r"\bRemove-Partition\b",               "Deletes a disk partition"),
    (r"\bClear-RecycleBin\b",              "Permanently empties the Recycle Bin"),
]

_MEDIUM_CMD = [
    (r"\breg\s+(add|delete)\b|Set-ItemProperty.*(HKLM|HKCU|HKEY)",
                                            "Modifies the Windows Registry"),
    (r"\bNew-ItemProperty\b.*(HKLM|HKCU|HKEY)",
                                            "Adds a Windows Registry entry"),
    (r"\bStop-Service\b|\bDisable-\w*Service\b",
                                            "Stops or disables a Windows service"),
    (r"\bSet-Service\b",                    "Changes a Windows service configuration"),
    (r"\bNew-ScheduledTask\b|\bRegister-ScheduledTask\b",
                                            "Creates a scheduled task"),
    (r"\bNew-LocalUser\b",                  "Creates a local user account"),
    (r"\bAdd-LocalGroupMember\b",           "Adds a user to a local group"),
    (r"\bSet-ExecutionPolicy\b",            "Changes PowerShell execution policy"),
    (r"\bnetsh\b",                          "Modifies network configuration"),
    (r"\bNew-NetFirewallRule\b|\bRemove-NetFirewallRule\b",
                                            "Changes Windows Firewall rules"),
    (r"\bStop-Computer\b|\bRestart-Computer\b",
                                            "Shuts down or restarts the computer"),
    (r"\bDisable-WindowsOptionalFeature\b", "Disables a Windows feature"),
    (r"\bStop-Process\b|\bkill\b",          "Terminates running processes"),
]

_HIGH_WRITE_PATHS = [
    r"(?i)c:\\windows\\",
    r"(?i)c:\\(windows\\)?system32\\",
]
_HIGH_WRITE_EXTS  = {".exe", ".dll", ".sys", ".bat", ".cmd", ".ps1",
                     ".vbs", ".js", ".hta", ".scr", ".msi"}
_MEDIUM_WRITE_PATHS = [
    r"(?i)c:\\program files",
    r"(?i)c:\\programdata",
    r"(?i)startup",
]


def _classify_risk(tool_name: str, inputs: dict) -> tuple[str, str]:
    """Return (risk_level, human_detail). Levels: 'high', 'medium', 'normal'."""
    if tool_name == "run_command":
        cmd = inputs.get("command", "")
        for pattern, detail in _HIGH_CMD:
            if re.search(pattern, cmd, re.IGNORECASE):
                return "high", detail
        for pattern, detail in _MEDIUM_CMD:
            if re.search(pattern, cmd, re.IGNORECASE):
                return "medium", detail
        return "normal", ""

    if tool_name == "write_file":
        path = inputs.get("path", "").replace("/", "\\")
        ext  = re.search(r"\.\w+$", path)
        ext  = ext.group().lower() if ext else ""
        if any(re.search(p, path) for p in _HIGH_WRITE_PATHS):
            return "high", "Writing to a protected system directory"
        if ext in _HIGH_WRITE_EXTS:
            return "high", f"Writing an executable file type ({ext})"
        if any(re.search(p, path) for p in _MEDIUM_WRITE_PATHS):
            return "medium", "Writing to a shared system location"
        return "normal", ""

    return "normal", ""


class AgentThread(QThread):
    chunk_received = pyqtSignal(str)        # streaming text delta
    tool_started   = pyqtSignal(str, dict)  # tool_name, inputs
    tool_finished  = pyqtSignal(str, dict)  # tool_name, result
    turn_complete  = pyqtSignal()           # one full agentic turn done
    error_occurred = pyqtSignal(str)
    confirm_needed = pyqtSignal(str, str, str, str)  # title, body, risk_level, risk_detail

    def __init__(self, user_message: str, history: list, parent=None):
        super().__init__(parent)
        self.user_message = user_message
        # Work on a copy so the main thread's list is not mutated mid-run
        self.history = list(history)
        self._confirm_event = threading.Event()
        self._confirm_approved = False

    def resolve_confirm(self, approved: bool):
        """Called from the main thread to unblock a pending confirmation."""
        self._confirm_approved = approved
        self._confirm_event.set()

    def _request_confirmation(self, tool_name: str, inputs: dict) -> bool:
        """Emit confirm_needed and block until the user responds. Returns True = allow."""
        if tool_name == "run_command":
            title = "Run PowerShell Command?"
            body = inputs.get("command", "")
        elif tool_name == "write_file":
            path = inputs.get("path", "")
            content = inputs.get("content", "")
            preview = content[:500] + ("…" if len(content) > 500 else "")
            title = f"Write file: {path}"
            body = preview
        else:
            return True  # all other tools run without confirmation

        risk_level, risk_detail = _classify_risk(tool_name, inputs)

        self._confirm_event.clear()
        self._confirm_approved = False
        self.confirm_needed.emit(title, body, risk_level, risk_detail)
        self._confirm_event.wait(timeout=300)  # 5-min safety timeout
        return self._confirm_approved

    def run(self):
        api_key = get_api_key()
        if not api_key:
            self.error_occurred.emit(
                "No API key set. Click **API Key** in the toolbar to add yours."
            )
            return

        client = anthropic.Anthropic(api_key=api_key)
        model = get_model()

        self.history.append({"role": "user", "content": self.user_message})

        try:
            while True:
                # ---- stream one API turn ----
                text_buffer = ""

                with client.messages.stream(
                    model=model,
                    max_tokens=8096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=self.history,
                ) as stream:
                    for chunk in stream.text_stream:
                        text_buffer += chunk
                        self.chunk_received.emit(chunk)
                    final = stream.get_final_message()

                # Store assistant response as plain dicts
                assistant_content = _content_to_params(final.content)
                self.history.append({"role": "assistant", "content": assistant_content})

                # Collect tool_use blocks
                tool_uses = [b for b in final.content if b.type == "tool_use"]

                if final.stop_reason == "end_turn" or not tool_uses:
                    break

                # ---- execute all tools, collect results ----
                tool_results = []
                for tu in tool_uses:
                    self.tool_started.emit(tu.name, dict(tu.input))

                    if not self._request_confirmation(tu.name, dict(tu.input)):
                        result = {"output": "Cancelled by user."}
                        self.tool_finished.emit(tu.name, result)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": "The user cancelled this action. Ask what they would like to do instead.",
                        })
                        continue

                    result = execute_tool(tu.name, dict(tu.input))
                    self.tool_finished.emit(tu.name, result)

                    if "image" in result:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": [
                                {"type": "text", "text": result["output"]},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": f"image/{result.get('image_format', 'png')}",
                                        "data": result["image"],
                                    },
                                },
                            ],
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": result["output"],
                        })

                self.history.append({"role": "user", "content": tool_results})

            self.turn_complete.emit()

        except anthropic.AuthenticationError:
            self.error_occurred.emit("Invalid API key. Update it via the **API Key** button.")
        except anthropic.RateLimitError:
            self.error_occurred.emit("Rate limit reached. Wait a moment and try again.")
        except Exception as exc:
            self.error_occurred.emit(f"Unexpected error: {exc}")
