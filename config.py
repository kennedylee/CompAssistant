import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# When frozen by PyInstaller, __file__ points into a temp dir; use the exe's folder instead.
_base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
_env_path = _base / '.env'
_history_path = _base / 'history.json'
load_dotenv(_env_path)

# Keep the saved file small: drop any base64 tool-result images and cap how
# far back we keep messages, since screenshots otherwise make this huge fast.
_MAX_HISTORY_MESSAGES = 40


def _strip_images(content):
    if not isinstance(content, list):
        return content
    cleaned = []
    for block in content:
        if not isinstance(block, dict):
            cleaned.append(block)
        elif block.get("type") == "image":
            cleaned.append({"type": "text", "text": "[image omitted from saved history]"})
        elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
            cleaned.append({**block, "content": _strip_images(block["content"])})
        else:
            cleaned.append(block)
    return cleaned


def save_history(history: list):
    trimmed = history[-_MAX_HISTORY_MESSAGES:]
    cleaned = [
        {**msg, "content": _strip_images(msg.get("content"))}
        for msg in trimmed
    ]
    try:
        with open(_history_path, 'w', encoding='utf-8') as f:
            json.dump(cleaned, f)
    except OSError:
        pass


def load_history() -> list:
    try:
        with open(_history_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def clear_history():
    try:
        _history_path.unlink()
    except OSError:
        pass


def get_api_key() -> str:
    return os.getenv('ANTHROPIC_API_KEY', '')


def get_model() -> str:
    return os.getenv('MODEL', 'claude-opus-4-7')


def save_settings(api_key: str, model: str):
    lines = []
    if api_key:
        lines.append(f'ANTHROPIC_API_KEY={api_key}')
    if model:
        lines.append(f'MODEL={model}')
    with open(_env_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    # Reload
    os.environ['ANTHROPIC_API_KEY'] = api_key
    os.environ['MODEL'] = model
