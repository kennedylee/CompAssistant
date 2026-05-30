import subprocess
import platform
import os
import base64
import time
from io import BytesIO
from pathlib import Path

import pyautogui
import psutil
from PIL import Image

# Don't halt if mouse hits corner; small pause between actions
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


# ---------------------------------------------------------------------------
# Tool schema definitions sent to Claude
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "screenshot",
        "description": (
            "Take a screenshot of the entire screen. Use this to see what is currently "
            "on screen before performing click or type actions. Returns the image."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "click",
        "description": (
            "Click at x,y pixel coordinates on the screen. "
            "Take a screenshot first to find the correct coordinates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Pixels from the left edge"},
                "y": {"type": "integer", "description": "Pixels from the top edge"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "description": "Which mouse button. Default: left",
                },
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "double_click",
        "description": "Double-click at x,y coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "right_click",
        "description": "Right-click at x,y coordinates to open a context menu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "move_mouse",
        "description": "Move the mouse to x,y coordinates without clicking (for hover effects).",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": (
            "Type text at the current cursor position using clipboard paste for "
            "reliable Unicode support. Click the target field first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "press_key",
        "description": (
            "Press a key or key combination. Examples: 'enter', 'escape', 'tab', "
            "'ctrl+c', 'ctrl+v', 'ctrl+a', 'alt+f4', 'win+d', 'ctrl+shift+esc', 'f5'. "
            "Use '+' to combine modifier keys."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {"type": "string", "description": "Key or combination (e.g. 'ctrl+c')"},
            },
            "required": ["keys"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the mouse wheel at x,y coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "clicks": {
                    "type": "integer",
                    "description": "Scroll amount: positive = up, negative = down",
                },
            },
            "required": ["x", "y", "clicks"],
        },
    },
    {
        "name": "drag",
        "description": "Click and drag from one point to another (e.g. to move windows or select text).",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_x": {"type": "integer"},
                "start_y": {"type": "integer"},
                "end_x": {"type": "integer"},
                "end_y": {"type": "integer"},
                "duration": {
                    "type": "number",
                    "description": "Drag duration in seconds. Default: 0.5",
                },
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the text contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full file path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed. Overwrites existing content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full file path"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and folders in a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a PowerShell command and return the output. "
            "Use for system administration, registry changes, network config, "
            "installing software, managing services, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell command to run"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout seconds. Default: 30",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "get_system_info",
        "description": "Get information about the system.",
        "input_schema": {
            "type": "object",
            "properties": {
                "info_type": {
                    "type": "string",
                    "enum": ["overview", "processes", "disk", "memory", "network", "startup"],
                    "description": "Category of information to retrieve",
                },
            },
            "required": ["info_type"],
        },
    },
    {
        "name": "open_application",
        "description": "Open an application, file, or URL with its default handler.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "App name, exe path, file path, or URL",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "get_clipboard",
        "description": "Get the current contents of the clipboard.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_clipboard",
        "description": "Set the clipboard to specific text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to put in clipboard"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "wait",
        "description": "Pause for a number of seconds (e.g. waiting for an app to load).",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "Seconds to wait (max 15)",
                },
            },
            "required": ["seconds"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def execute_tool(name: str, inputs: dict) -> dict:
    """Execute a tool by name. Returns dict with 'output' and optional 'image'/'image_format'."""
    try:
        handlers = {
            "screenshot":     _screenshot,
            "click":          _click,
            "double_click":   _double_click,
            "right_click":    _right_click,
            "move_mouse":     _move_mouse,
            "type_text":      _type_text,
            "press_key":      _press_key,
            "scroll":         _scroll,
            "drag":           _drag,
            "read_file":      _read_file,
            "write_file":     _write_file,
            "list_directory": _list_directory,
            "run_command":    _run_command,
            "get_system_info": _get_system_info,
            "open_application": _open_application,
            "get_clipboard":  _get_clipboard,
            "set_clipboard":  _set_clipboard,
            "wait":           _wait,
        }
        if name not in handlers:
            return {"output": f"Unknown tool: {name}"}
        return handlers[name](inputs)
    except Exception as exc:
        return {"output": f"Tool '{name}' error: {exc}"}


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------

def _screenshot(_inputs=None) -> dict:
    img = pyautogui.screenshot()
    # Downscale wide screens to stay within token budget
    max_w = 1280
    if img.width > max_w:
        scale = max_w / img.width
        img = img.resize((max_w, int(img.height * scale)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    w, h = pyautogui.size()
    return {
        "output": f"Screenshot captured. Screen resolution: {w}x{h}",
        "image": b64,
        "image_format": "png",
    }


def _click(inputs: dict) -> dict:
    x, y = inputs["x"], inputs["y"]
    btn = inputs.get("button", "left")
    pyautogui.click(x, y, button=btn)
    return {"output": f"Clicked {btn} at ({x}, {y})"}


def _double_click(inputs: dict) -> dict:
    x, y = inputs["x"], inputs["y"]
    pyautogui.doubleClick(x, y)
    return {"output": f"Double-clicked at ({x}, {y})"}


def _right_click(inputs: dict) -> dict:
    x, y = inputs["x"], inputs["y"]
    pyautogui.click(x, y, button="right")
    return {"output": f"Right-clicked at ({x}, {y})"}


def _move_mouse(inputs: dict) -> dict:
    x, y = inputs["x"], inputs["y"]
    pyautogui.moveTo(x, y)
    return {"output": f"Mouse moved to ({x}, {y})"}


def _type_text(inputs: dict) -> dict:
    import pyperclip
    text = inputs["text"]
    pyperclip.copy(text)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.05)
    return {"output": f"Typed: {repr(text[:80])}{'...' if len(text) > 80 else ''}"}


def _press_key(inputs: dict) -> dict:
    keys = inputs["keys"].strip()
    parts = [k.strip() for k in keys.split("+")]
    if len(parts) > 1:
        pyautogui.hotkey(*parts)
    else:
        pyautogui.press(parts[0])
    return {"output": f"Pressed: {keys}"}


def _scroll(inputs: dict) -> dict:
    x, y, clicks = inputs["x"], inputs["y"], inputs["clicks"]
    pyautogui.scroll(clicks, x=x, y=y)
    direction = "up" if clicks > 0 else "down"
    return {"output": f"Scrolled {abs(clicks)} clicks {direction} at ({x}, {y})"}


def _drag(inputs: dict) -> dict:
    sx, sy = inputs["start_x"], inputs["start_y"]
    ex, ey = inputs["end_x"], inputs["end_y"]
    dur = inputs.get("duration", 0.5)
    pyautogui.moveTo(sx, sy, duration=0.1)
    pyautogui.dragTo(ex, ey, duration=dur, button="left")
    return {"output": f"Dragged from ({sx},{sy}) to ({ex},{ey})"}


def _read_file(inputs: dict) -> dict:
    p = Path(inputs["path"])
    if not p.exists():
        return {"output": f"File not found: {p}"}
    if not p.is_file():
        return {"output": f"Not a file: {p}"}
    max_bytes = 100_000
    size = p.stat().st_size
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_bytes)
        if size > max_bytes:
            content += f"\n\n[Truncated — showing {max_bytes}/{size} bytes]"
        return {"output": content}
    except Exception as e:
        return {"output": f"Cannot read as text: {e}"}


def _write_file(inputs: dict) -> dict:
    p = Path(inputs["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(inputs["content"])
    return {"output": f"Wrote {len(inputs['content'])} chars to {p}"}


def _list_directory(inputs: dict) -> dict:
    p = Path(inputs["path"])
    if not p.exists():
        return {"output": f"Path not found: {p}"}
    if not p.is_dir():
        return {"output": f"Not a directory: {p}"}
    rows = []
    for item in sorted(p.iterdir(), key=lambda i: (i.is_file(), i.name.lower())):
        if item.is_dir():
            rows.append(f"[DIR]  {item.name}/")
        else:
            s = item.stat().st_size
            size_str = (
                f"{s}B" if s < 1024 else
                f"{s//1024}KB" if s < 1024**2 else
                f"{s//1024**2}MB"
            )
            rows.append(f"[FILE] {item.name}  ({size_str})")
    if not rows:
        return {"output": f"Empty directory: {p}"}
    return {"output": f"{p}\n" + "\n".join(rows)}


def _run_command(inputs: dict) -> dict:
    cmd = inputs["command"]
    timeout = int(inputs.get("timeout", 30))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = result.stdout or ""
        if result.stderr:
            out += ("\n" if out else "") + f"STDERR: {result.stderr}"
        if not out:
            out = "(No output)"
        if result.returncode != 0:
            out = f"Exit code {result.returncode}\n" + out
        if len(out) > 15_000:
            out = out[:15_000] + "\n[Output truncated]"
        return {"output": out}
    except subprocess.TimeoutExpired:
        return {"output": f"Command timed out after {timeout}s"}


def _get_system_info(inputs: dict) -> dict:
    kind = inputs["info_type"]

    if kind == "overview":
        cpu_pct = psutil.cpu_percent(interval=0.5)
        vm = psutil.virtual_memory()
        info = {
            "OS": f"{platform.system()} {platform.release()} {platform.version()}",
            "Processor": platform.processor() or platform.machine(),
            "CPU cores": psutil.cpu_count(logical=False),
            "CPU logical": psutil.cpu_count(),
            "CPU usage": f"{cpu_pct}%",
            "RAM total": f"{vm.total // 1024**3} GB",
            "RAM available": f"{vm.available // 1024**2} MB",
            "RAM usage": f"{vm.percent}%",
        }
        return {"output": "\n".join(f"{k}: {v}" for k, v in info.items())}

    if kind == "processes":
        procs = sorted(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
            key=lambda p: p.info.get("memory_percent") or 0,
            reverse=True,
        )[:25]
        lines = ["PID    Name                           CPU%   MEM%"]
        lines += [
            f"{p.info['pid']:<7}{p.info['name']:<31}"
            f"{(p.info['cpu_percent'] or 0):>5.1f}  {(p.info['memory_percent'] or 0):>5.1f}"
            for p in procs
        ]
        return {"output": "\n".join(lines)}

    if kind == "disk":
        lines = []
        for disk in psutil.disk_partitions():
            try:
                u = psutil.disk_usage(disk.mountpoint)
                lines.append(
                    f"{disk.device} [{disk.fstype}] "
                    f"{u.used//1024**3}GB/{u.total//1024**3}GB ({u.percent}%)"
                )
            except PermissionError:
                pass
        return {"output": "Disks:\n" + "\n".join(lines)}

    if kind == "memory":
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return {
            "output": (
                f"RAM: {vm.used//1024**2} MB used / {vm.total//1024**2} MB total ({vm.percent}%)\n"
                f"Swap: {sw.used//1024**2} MB used / {sw.total//1024**2} MB total ({sw.percent}%)"
            )
        }

    if kind == "network":
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        lines = []
        for iface, addr_list in addrs.items():
            st = stats.get(iface)
            status = "UP" if (st and st.isup) else "DOWN"
            for addr in addr_list:
                if addr.family.name == "AF_INET":
                    lines.append(f"{iface} ({status}): {addr.address}")
        return {"output": "Network:\n" + "\n".join(lines)}

    if kind == "startup":
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location | Format-Table -AutoSize"],
            capture_output=True, text=True, timeout=15,
        )
        return {"output": r.stdout or r.stderr or "(No startup items found)"}

    return {"output": f"Unknown info_type: {kind}"}


def _open_application(inputs: dict) -> dict:
    target = inputs["target"]
    try:
        os.startfile(target)
        return {"output": f"Opened: {target}"}
    except Exception:
        try:
            subprocess.Popen(target, shell=True)
            return {"output": f"Launched: {target}"}
        except Exception as e:
            return {"output": f"Failed to open {target}: {e}"}


def _get_clipboard(_inputs=None) -> dict:
    import pyperclip
    try:
        text = pyperclip.paste()
        return {"output": text if text else "(Clipboard is empty)"}
    except Exception as e:
        return {"output": f"Clipboard error: {e}"}


def _set_clipboard(inputs: dict) -> dict:
    import pyperclip
    pyperclip.copy(inputs["text"])
    return {"output": f"Clipboard set to: {repr(inputs['text'][:80])}"}


def _wait(inputs: dict) -> dict:
    secs = min(float(inputs.get("seconds", 1)), 15)
    time.sleep(secs)
    return {"output": f"Waited {secs:.1f} seconds"}
