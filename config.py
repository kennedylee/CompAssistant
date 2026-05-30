import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# When frozen by PyInstaller, __file__ points into a temp dir; use the exe's folder instead.
_base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
_env_path = _base / '.env'
load_dotenv(_env_path)


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
