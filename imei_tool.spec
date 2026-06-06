# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS .app (onedir, ổn định hơn onefile trên macOS)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import os

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

if tesseract_bundle.is_dir():
    tess_bin = tesseract_bundle / "bin" / "tesseract"
    tessdata = tesseract_bundle / "share" / "tessdata"
    tess_lib = tesseract_bundle / "lib"
    if tess_bin.is_file():
        binaries.append((str(tess_bin), "tesseract/bin"))
    if tessdata.is_dir():
        datas.append((str(tessdata), "tesseract/share/tessdata"))
    if tess_lib.is_dir():
        for dylib in tess_lib.glob("*.dylib"):
            binaries.append((str(dylib), "tesseract/lib"))

hiddenimports += collect_submodules("pymobiledevice3")
hiddenimports += collect_submodules("PIL")
try:
    hiddenimports += collect_submodules("ocrmac")
except Exception:
    pass
hiddenimports += [
    "customtkinter",
    "ocrmac",
    "ocrmac.ocrmac",
    "Vision",
    "objc",
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
    "src.macos_ocr",
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
    "src.macos_menu",
    "src.about_dialog",
    "src.trial",
    "Foundation",
    "AppKit",
]

datas += collect_data_files("pymobiledevice3", include_py_files=True)
datas += collect_data_files("certifi")
datas += collect_data_files("customtkinter")

_assets = project_dir / "assets"
if _assets.is_dir():
    datas.append((str(_assets), "assets"))

_icon_icns = _assets / "AppIcon.icns"
_app_icon = str(_icon_icns) if _icon_icns.is_file() else None

_entry = str(_obf_root / "main.py") if _use_obf else str(project_dir / "main.py")
_pathex = [str(_obf_root), str(project_dir)] if _use_obf else [str(project_dir)]

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
