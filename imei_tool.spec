# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS .app (onedir, ổn định hơn onefile trên macOS)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import os
import sys

block_cipher = None
project_dir = Path(SPECPATH)
_obf_dir = os.environ.get("PYARMOR_OBF_DIR", "").strip()
_obf_root = Path(_obf_dir) if _obf_dir else None
_use_obf = _obf_root is not None and (_obf_root / "main.py").is_file()
hooks_dir = project_dir / "hooks"
tesseract_bundle = project_dir / "build" / "tesseract_bundle"

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = []

def _add_tesseract_bundle(bundle_dir: Path) -> None:
    if not bundle_dir.is_dir():
        return
    tess_bin = bundle_dir / "bin" / "tesseract"
    if sys.platform == "win32":
        tess_bin = bundle_dir / "bin" / "tesseract.exe"
    tessdata = bundle_dir / "share" / "tessdata"
    tess_lib = bundle_dir / "lib"
    if tess_bin.is_file():
        binaries.append((str(tess_bin), "tesseract/bin"))
    if sys.platform == "win32":
        for dll in (bundle_dir / "bin").glob("*.dll"):
            binaries.append((str(dll), "tesseract/bin"))
    if tessdata.is_dir():
        datas.append((str(tessdata), "tesseract/share/tessdata"))
    if tess_lib.is_dir():
        for dylib in tess_lib.glob("*.dylib"):
            binaries.append((str(dylib), "tesseract/lib"))


for _bundle in (tesseract_bundle, project_dir / "tesseract"):
    _add_tesseract_bundle(_bundle)

hiddenimports += collect_submodules("pymobiledevice3")
hiddenimports += collect_submodules("PIL")
try:
    hiddenimports += collect_submodules("ocrmac")
except Exception:
    pass
hiddenimports += [
    "customtkinter",
    "asyncio",
    "plistlib",
    "construct",
    "construct.core",
    "cryptography",
    "OpenSSL",
    "PIL._tkinter_finder",
    "PIL.ImageGrab",
    "pytesseract",
    "openpyxl",
    "traitlets",
    "traitlets.config",
    "tqdm",
    "requests",
    "src",
    "src.gui",
    "src.usb_reader",
    "src.ocr_parser",
    "src.excel_export",
    "src.models",
    "src.database",
    "src.product_map",
    "src.bundle_paths",
    "src.battery_reader",
    "src.storage_reader",
    "src.app_branding",
    "src.clipboard_image",
    "src.enclosure_color",
    "src.print_labels",
    "src.app_settings",
    "src.settings_dialog",
    "barcode",
    "barcode.writer",
    "barcode.codex",
    "barcode.codex.code128",
    "src.line_import",
    "src.about_dialog",
    "src.trial",
    "src.macos_menu",
]
if sys.platform == "darwin":
    hiddenimports += [
        "ocrmac",
        "ocrmac.ocrmac",
        "Vision",
        "objc",
        "src.macos_ocr",
        "Foundation",
        "AppKit",
    ]
if sys.platform == "win32":
    hiddenimports += [
        "win32api",
        "win32con",
        "win32security",
        "pywintypes",
    ]

datas += collect_data_files("pymobiledevice3", include_py_files=True)
datas += collect_data_files("certifi")
datas += collect_data_files("customtkinter")

_assets = project_dir / "assets"
if _assets.is_dir():
    datas.append((str(_assets), "assets"))

_icon_icns = _assets / "AppIcon.icns"
_icon_ico = _assets / "AppIcon.ico"
_app_icon = None
if sys.platform == "darwin" and _icon_icns.is_file():
    _app_icon = str(_icon_icns)
elif sys.platform == "win32" and _icon_ico.is_file():
    _app_icon = str(_icon_ico)

_entry = str(_obf_root / "main.py") if _use_obf else str(project_dir / "main.py")
_pathex = [str(_obf_root), str(project_dir)] if _use_obf else [str(project_dir)]

if _use_obf and _obf_root is not None:
    for runtime_dir in _obf_root.glob("pyarmor_runtime_*"):
        if runtime_dir.is_dir():
            datas.append((str(runtime_dir), runtime_dir.name))

a = Analysis(
    [_entry],
    pathex=_pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(hooks_dir)],
    hooksconfig={},
    runtime_hooks=[str(hooks_dir / "pyi_rth_ipython_stub.py")],
    excludes=["matplotlib", "numpy", "pandas", "scipy", "jupyter", "IPython", "xonsh"],
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
    name="Taoden IMEI Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=os.environ.get("TARGET_ARCH") or None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_app_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Taoden IMEI Tool",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Taoden IMEI Tool.app",
        icon=_app_icon,
        bundle_identifier="com.taoden.imeitool",
        info_plist={
            "CFBundleName": "Taoden IMEI Tool",
            "CFBundleDisplayName": "Taoden IMEI Tool",
            "CFBundleVersion": "1.0.1",
            "CFBundleShortVersionString": "1.0.1",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
        },
    )
