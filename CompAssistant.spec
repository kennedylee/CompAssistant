from PyInstaller.utils.hooks import collect_all, collect_submodules

# Collect full package trees for packages that use dynamic imports
anthropic_d, anthropic_b, anthropic_h = collect_all('anthropic')
markdown_d,  markdown_b,  markdown_h  = collect_all('markdown')
httpx_d,     httpx_b,     httpx_h     = collect_all('httpx')
anyio_d,     anyio_b,     anyio_h     = collect_all('anyio')

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[] + anthropic_b + httpx_b + anyio_b,
    datas=[('icon.ico', '.')] + anthropic_d + markdown_d + httpx_d + anyio_d,
    hiddenimports=[
        # pyautogui ecosystem
        'pyautogui', 'pyscreeze', 'pymsgbox', 'pygetwindow',
        'pytweening', 'mouseinfo', 'pyrect',
        # Pillow (screenshot support)
        'PIL', 'PIL.Image', 'PIL.ImageGrab', 'PIL.ImageDraw',
        'PIL.ImageFont', 'PIL.PngImagePlugin',
        # clipboard
        'pyperclip',
        # system
        'psutil', 'psutil._pswindows',
        # dotenv
        'dotenv',
        # anthropic / http
        *anthropic_h, *httpx_h, *anyio_h, *markdown_h,
        'httpcore', 'certifi', 'idna', 'sniffio',
        'pydantic', 'pydantic_core',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pdb'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CompAssistant',
    debug=False,
    strip=False,
    upx=False,
    console=False,        # no black console window
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='CompAssistant',
)
