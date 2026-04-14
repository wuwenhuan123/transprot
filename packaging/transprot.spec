# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

project_root = Path(SPECPATH).resolve().parent
src_root = project_root / "src"
entry_script = src_root / "transprot" / "__main__.py"
build_cache_root = Path(os.environ.get("LOCALAPPDATA", str(project_root / ".tmp-build" / "localappdata"))) / "TransProt"
cache_root = build_cache_root / "build-cache"

for path in (build_cache_root, cache_root, cache_root / "paddle", cache_root / "paddlex", cache_root / "temp"):
    path.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("APPDATA", str(build_cache_root))
os.environ.setdefault("LOCALAPPDATA", str(build_cache_root))
os.environ.setdefault("HOME", str(build_cache_root))
os.environ.setdefault("USERPROFILE", str(build_cache_root))
os.environ.setdefault("XDG_CACHE_HOME", str(cache_root))
os.environ.setdefault("PADDLE_HOME", str(cache_root / "paddle"))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_root / "paddlex"))
os.environ.setdefault("TEMP", str(cache_root / "temp"))
os.environ.setdefault("TMP", str(cache_root / "temp"))

modules_to_collect = ["paddle", "paddleocr", "paddlex", "PIL", "imagesize", "bidi", "pyclipper", "pypdfium2", "shapely"]
metadata_to_copy = ["opencv-contrib-python", "pyclipper", "pypdfium2", "python-bidi", "shapely", "imagesize"]
offline_ocr_source = os.environ.get("TRANSPROT_OFFLINE_OCR_SOURCE", "").strip()
datas = [
    (str(project_root / "README.md"), "."),
    (str(project_root / "config.example.json"), "."),
]
binaries = []
hiddenimports = []

for module_name in modules_to_collect:
    collected_datas, collected_binaries, collected_hiddenimports = collect_all(module_name)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hiddenimports

for distribution_name in metadata_to_copy:
    datas += copy_metadata(distribution_name)

if offline_ocr_source:
    offline_ocr_root = Path(offline_ocr_source).resolve()
    if not offline_ocr_root.exists():
        raise FileNotFoundError(f"Offline OCR model path does not exist: {offline_ocr_root}")
    for file_path in offline_ocr_root.rglob("*"):
        if not file_path.is_file():
            continue
        target_dir = Path("offline-ocr-models") / file_path.relative_to(offline_ocr_root).parent
        datas.append((str(file_path), str(target_dir)))


a = Analysis(
    [str(entry_script)],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TransProt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TransProt",
)
