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


# (pattern, plain-English warning) — checked case-insensitively against the command
_HIGH_CMD = [
    (r"\bRemove-Item\b",
        "This will permanently delete files or folders. They will NOT go to the Recycle Bin and cannot be recovered."),
    (r"\brd\b|\brmdir\b",
        "This will permanently delete one or more folders and everything inside them."),
    (r"\bFormat-\w+",
        "This will erase everything on a drive. All data will be lost and cannot be recovered."),
    (r"\bClear-Disk\b|\bInitialize-Disk\b",
        "This will completely wipe a disk. Every file on it will be permanently destroyed."),
    (r"\bInvoke-Expression\b|\biex\b",
        "This will run code that was built on the fly. It could do anything to your computer and is difficult to predict or reverse."),
    (r"(Invoke-WebRequest|curl|wget).*\|.*(iex|Invoke-Expression)",
        "This will download code from the internet and run it immediately on your computer without any further review."),
    (r"\bRemove-LocalUser\b",
        "This will permanently delete a user account from this computer, including its settings and access."),
    (r"\bRemove-Partition\b",
        "This will permanently delete a disk partition and all data stored on it."),
    (r"\bClear-RecycleBin\b",
        "This will permanently delete everything currently in the Recycle Bin. Files cannot be recovered afterward."),
]

_MEDIUM_CMD = [
    (r"\breg\s+(add|delete)\b|Set-ItemProperty.*(HKLM|HKCU|HKEY)",
        "This will change the Windows Registry — the database that controls how your computer and programs behave. Incorrect changes can cause problems."),
    (r"\bNew-ItemProperty\b.*(HKLM|HKCU|HKEY)",
        "This will add a new entry to the Windows Registry, which can affect how your computer or a program behaves."),
    (r"\bStop-Service\b|\bDisable-\w*Service\b",
        "This will stop or disable a background service your computer relies on. Some features or programs may stop working."),
    (r"\bSet-Service\b",
        "This will change the behavior of a background service that your computer depends on."),
    (r"\bNew-ScheduledTask\b|\bRegister-ScheduledTask\b",
        "This will set up a task to run automatically in the background on a schedule."),
    (r"\bNew-LocalUser\b",
        "This will create a new user account on this computer with the ability to log in."),
    (r"\bAdd-LocalGroupMember\b",
        "This will give a user account additional permissions or access on this computer."),
    (r"\bSet-ExecutionPolicy\b",
        "This will change which scripts and programs are allowed to run on this computer."),
    (r"\bnetsh\b",
        "This will change your network or internet connection settings, which could affect your ability to get online."),
    (r"\bNew-NetFirewallRule\b|\bRemove-NetFirewallRule\b",
        "This will change your firewall rules, which control what is allowed to connect to or from your computer."),
    (r"\bStop-Computer\b|\bRestart-Computer\b",
        "This will shut down or restart your computer. Make sure you have saved any open work first."),
    (r"\bDisable-WindowsOptionalFeature\b",
        "This will turn off a built-in Windows feature. It can usually be re-enabled, but some features take time to restore."),
    (r"\bStop-Process\b|\bkill\b",
        "This will force-close one or more running programs. Any unsaved work in those programs will be lost."),
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
            return "high", "This will write a file directly into a protected Windows system folder. Changes here can affect how your entire computer runs."
        if ext in _HIGH_WRITE_EXTS:
            return "high", f"This will create a {ext} file — a type that can run programs on your computer. Only allow this if you know exactly what it does."
        if any(re.search(p, path) for p in _MEDIUM_WRITE_PATHS):
            return "medium", "This will write a file to a folder shared by all users on this computer. It may affect other accounts or installed programs."
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
        self._client = None  # set at start of run()

    def resolve_confirm(self, approved: bool):
        """Called from the main thread to unblock a pending confirmation."""
        self._confirm_approved = approved
        self._confirm_event.set()

    def _get_llm_description(self, tool_name: str, inputs: dict, risk_level: str) -> str:
        """Ask Claude Haiku for a plain-English explanation. Returns '' on any failure."""
        if self._client is None:
            return ""
        try:
            if tool_name == "run_command":
                subject = f"PowerShell command:\n{inputs.get('command', '')}"
            elif tool_name == "write_file":
                path = inputs.get("path", "")
                preview = inputs.get("content", "")[:300]
                subject = f"Writing to: {path}\nContent preview:\n{preview}"
            else:
                return ""

            risk_note = {
                "high":   " Emphasize that this could be permanent or very hard to undo.",
                "medium": " Mention what could be affected if something goes wrong.",
                "normal": "",
            }.get(risk_level, "")

            prompt = (
                f"Explain this computer action to a non-technical user in 1-2 plain sentences.{risk_note}\n"
                f"Be specific — mention actual file names, paths, or program names if present.\n"
                f"Use simple everyday language. Start with 'This will...'\n"
                f"Plain text only — no markdown, no bold, no asterisks.\n\n"
                f"{subject}"
            )

            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=120,
                messages=[{"role": "user", "content": prompt}],
                timeout=8.0,
            )
            return resp.content[0].text.strip()
        except Exception:
            return ""

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

        risk_level, static_detail = _classify_risk(tool_name, inputs)
        llm_detail = self._get_llm_description(tool_name, inputs, risk_level)
        detail = llm_detail if llm_detail else static_detail  # LLM first, static as fallback

        self._confirm_event.clear()
        self._confirm_approved = False
        self.confirm_needed.emit(title, body, risk_level, detail)
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
        self._client = client
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
