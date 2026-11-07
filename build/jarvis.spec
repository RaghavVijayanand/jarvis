# -*- mode: python ; coding: utf-8 -*-
# JARVIS for Windows — PyInstaller spec (one-folder build, used by the installer).
#
#   python build/build_installer.py        # everything: icon → PyInstaller → Inno Setup
#   pyinstaller build/jarvis.spec --noconfirm --distpath dist --workpath _pyibuild
#
# Output: dist/JARVIS/JARVIS.exe (+ its runtime files). One-folder starts in ~1-2 s;
# a one-file exe would unpack ~300 MB to %TEMP% on every start.
#
# Laya (the local decision model: PyTorch + transformers, roughly +1 GB) ships
# inside the app by default, so a fresh install never needs a separate
# `pip install laya`. Set JARVIS_BUNDLE_LAYA=0 to opt back out of that (a
# smaller, rules-only build) — the app still falls back to the regex router
# whenever Laya isn't loaded, installed or reachable.
#
# If build/build_installer.py's warm_up_laya step pre-downloaded the model
# into _hf_cache/ (a real Windows machine with internet, run at build time),
# that folder is bundled too, as hf_cache/ next to JARVIS.exe — see
# core/decision.py's _prepare_hf_cache_env, which points Hugging Face Hub at
# it — so the packaged app has Laya ready offline from the first run. Without
# it, Laya still works: it just downloads the model on first use like a
# from-source install does.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
BUNDLE_LAYA = os.getenv('JARVIS_BUNDLE_LAYA', '1') == '1'
HF_CACHE = ROOT / '_hf_cache'
ICON = ROOT / 'assets' / 'jarvis.ico'

hidden = (
    ['app', 'main_gui', 'jarvis']
    + collect_submodules('core') + collect_submodules('handlers') + collect_submodules('skills')
    + collect_submodules('ui')
    + [
        'pyttsx3.drivers', 'pyttsx3.drivers.sapi5', 'speech_recognition', 'edge_tts',
        'win32api', 'win32con', 'win32gui', 'win32clipboard', 'win32com', 'win32com.client', 'pythoncom',
        'winreg', 'comtypes', 'comtypes.stream', 'pycaw', 'pycaw.pycaw',
        'pyautogui', 'PIL.ImageGrab', 'PIL.ImageChops',
        'rich.console', 'rich.panel', 'rich.markup', 'dotenv', 'schedule', 'wmi', 'winshell', 'send2trash',
        # pynput picks its backend at runtime, so PyInstaller can't see these imports
        'pynput.keyboard._win32', 'pynput.mouse._win32', 'pynput._util.win32',
        'vosk', 'bs4',
        'PySide6.QtNetwork',
    ]
)
# Built and installed separately from requirements.txt (see there): PyAudio compiles against
# PortAudio and has no prebuilt wheel on every Python version, so it may legitimately be
# missing from the build machine's venv. Bundle it only if it's actually there.
for optional in ('winsdk', 'winsdk.windows.media.control', 'pyaudio'):
    try:
        __import__(optional)
        hidden.append(optional)
    except Exception:
        pass

binaries, datas = [], [(str(ROOT / 'assets'), 'assets')]
try:                                   # vosk ships libvosk.dll + friends next to its package
    binaries += collect_dynamic_libs('vosk')
    datas += collect_data_files('vosk')
except Exception:
    pass
# Local speech (core/local_speech.py): Kokoro voice (ONNX + espeak-ng phonemes) and Whisper on the CPU
# (faster-whisper / CTranslate2). Their DLLs and data files aren't Python imports, so collect them here.
for package in ('kokoro_onnx', 'espeakng_loader', 'phonemizer', 'onnxruntime', 'faster_whisper', 'ctranslate2',
                'soundfile', 'sounddevice'):
    try:
        __import__(package)
    except Exception:
        continue
    hidden.append(package)
    try:
        binaries += collect_dynamic_libs(package)
        datas += collect_data_files(package)
    except Exception:
        pass
if BUNDLE_LAYA and HF_CACHE.is_dir():   # pre-downloaded Laya weights, if warm_up_laya produced them
    datas += [(str(HF_CACHE), 'hf_cache')]

excludes = ['tkinter', 'sqlalchemy', 'tensorflow', 'keras', 'matplotlib', 'pandas', 'sklearn', 'cv2',
            'IPython', 'jupyter', 'pytest']
if BUNDLE_LAYA:
    hidden += ['laya', 'torch', 'transformers', 'safetensors', 'huggingface_hub', 'numpy']
else:
    excludes += ['laya', 'torch', 'torchvision', 'torchaudio', 'transformers', 'datasets', 'scipy']

a = Analysis(
    [str(ROOT / 'app.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                         # UPX-packed Qt/Python DLLs trip antivirus heuristics
    console=False,                     # windowed: no terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(ROOT / 'build' / 'version_info.txt') if (ROOT / 'build' / 'version_info.txt').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='JARVIS',
)
