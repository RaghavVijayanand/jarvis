#!/usr/bin/env python3
"""
JARVIS Executable Builder
Creates a standalone executable that can run on any Windows system
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def install_pyinstaller():
    """Install PyInstaller if not already installed"""
    print("📦 Installing PyInstaller...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✅ PyInstaller installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install PyInstaller: {e}")
        return False
    return True

def create_spec_file():
    """Create PyInstaller spec file for JARVIS"""
    spec_content = '''
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Define all the Python files and modules to include
a = Analysis(
    ['main_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('skills', 'skills'),
        ('cache', 'cache'),
        ('data', 'data'),
        ('logs', 'logs'),
        ('memory', 'memory'),
        ('assets', 'assets'),
        ('config.py', '.'),
        ('requirements.txt', '.'),
        ('README.md', '.'),
        ('USERGUIDE.md', '.'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui', 
        'PySide6.QtWidgets',
        'speech_recognition',
        'pyttsx3',
        'pyautogui',
        'Pillow',
        'psutil',
        'requests',
        'openai',
        'anthropic',
        'google-generativeai',
        'rich',
        'langchain',
        'langchain_openai',
        'langchain_anthropic',
        'langchain_google_genai',
        'numpy',
        'opencv-python',
        'pyaudio',
        'sounddevice',
        'transformers',
        'torch',
        'win32gui',
        'win32con',
        'win32api',
        'winreg',
        'concurrent.futures',
        'threading',
        'asyncio',
        'json',
        'os',
        'sys',
        'time',
        'datetime',
        'pathlib',
        'subprocess',
        'multiprocessing',
        'tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='JARVIS_AI_Assistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to False for windowed application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/jarvis_icon.ico' if os.path.exists('assets/jarvis_icon.ico') else None,
)
'''
    
    with open('jarvis.spec', 'w') as f:
        f.write(spec_content)
    print("✅ Spec file created: jarvis.spec")

def create_icon():
    """Create a simple icon file if it doesn't exist"""
    assets_dir = Path('assets')
    assets_dir.mkdir(exist_ok=True)
    
    icon_path = assets_dir / 'jarvis_icon.ico'
    if not icon_path.exists():
        print("📎 Creating default icon...")
        # You can replace this with a proper icon file
        # For now, we'll skip the icon if it doesn't exist
        print("ℹ️  No icon file found. Executable will use default Windows icon.")

def prepare_directories():
    """Create necessary directories and files"""
    print("📁 Preparing directories...")
    
    # Create necessary directories
    dirs_to_create = ['cache', 'data', 'logs', 'memory', 'assets']
    for dir_name in dirs_to_create:
        Path(dir_name).mkdir(exist_ok=True)
    
    # Create empty files if they don't exist
    files_to_create = [
        'cache/app_cache.json',
        'memory/conversation.json',
        'data/.gitkeep',
        'logs/.gitkeep'
    ]
    
    for file_path in files_to_create:
        path = Path(file_path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.endswith('.json'):
                path.write_text('{}')
            else:
                path.write_text('')

def build_executable():
    """Build the executable using PyInstaller"""
    print("🔨 Building executable...")
    
    try:
        # Clean previous builds
        if os.path.exists('dist'):
            shutil.rmtree('dist')
        if os.path.exists('build'):
            shutil.rmtree('build')
        
        # Build the executable
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            '--clean',
            '--noconfirm',
            'jarvis.spec'
        ]
        
        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Executable built successfully!")
            print("📁 Executable location: dist/JARVIS_AI_Assistant.exe")
            
            # Check file size
            exe_path = Path('dist/JARVIS_AI_Assistant.exe')
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / (1024 * 1024)
                print(f"📊 Executable size: {size_mb:.1f} MB")
            
            return True
        else:
            print("❌ Build failed!")
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Build error: {e}")
        return False

def create_installer_script():
    """Create a simple installer script"""
    installer_content = '''
@echo off
echo.
echo ========================================
echo   JARVIS AI Assistant Installer
echo ========================================
echo.

echo Installing JARVIS AI Assistant...

if not exist "C:\\Program Files\\JARVIS" mkdir "C:\\Program Files\\JARVIS"

copy "JARVIS_AI_Assistant.exe" "C:\\Program Files\\JARVIS\\" >nul
if errorlevel 1 (
    echo Error: Could not copy files. Please run as Administrator.
    pause
    exit /b 1
)

echo Creating desktop shortcut...
powershell -command "$WshShell = New-Object -comObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%USERPROFILE%\\Desktop\\JARVIS AI Assistant.lnk'); $Shortcut.TargetPath = 'C:\\Program Files\\JARVIS\\JARVIS_AI_Assistant.exe'; $Shortcut.Save()"

echo.
echo ✅ Installation completed successfully!
echo.
echo You can now run JARVIS from:
echo - Desktop shortcut: "JARVIS AI Assistant"
echo - Direct path: C:\\Program Files\\JARVIS\\JARVIS_AI_Assistant.exe
echo.
pause
'''
    
    with open('dist/install_jarvis.bat', 'w') as f:
        f.write(installer_content)
    
    print("✅ Installer script created: dist/install_jarvis.bat")

def create_readme():
    """Create README for the executable"""
    readme_content = '''
# JARVIS AI Assistant - Standalone Executable

## What's Included
- JARVIS_AI_Assistant.exe - The main application
- install_jarvis.bat - Optional installer script

## Quick Start
1. Double-click JARVIS_AI_Assistant.exe to run
2. Or run install_jarvis.bat as Administrator for system-wide installation

## Features
- Complete AI Assistant with voice recognition
- Multi-model AI support (OpenRouter, Gemini, etc.)
- Advanced automation and screen control
- File management and system monitoring
- Web search and weather information
- Visual task orchestration

## System Requirements
- Windows 10/11 (64-bit)
- 4GB+ RAM recommended
- Internet connection for AI features
- Microphone for voice commands (optional)

## Configuration
On first run, JARVIS will create configuration files in:
- %APPDATA%\\JARVIS\\

You can configure API keys and settings through the GUI.

## Troubleshooting
- If antivirus flags the file, add it to exclusions
- Run as Administrator if you encounter permission issues
- Check Windows Defender firewall settings if network features don't work

## Support
For issues or questions, refer to the original GitHub repository.
'''
    
    with open('dist/README.txt', 'w') as f:
        f.write(readme_content)
    
    print("✅ README created: dist/README.txt")

def main():
    """Main build process"""
    print("🚀 JARVIS AI Assistant - Executable Builder")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not os.path.exists('main_gui.py'):
        print("❌ Error: main_gui.py not found. Please run this script from the JARVIS project directory.")
        sys.exit(1)
    
    # Install PyInstaller
    if not install_pyinstaller():
        sys.exit(1)
    
    # Prepare build environment
    prepare_directories()
    create_icon()
    create_spec_file()
    
    # Build the executable
    if build_executable():
        create_installer_script()
        create_readme()
        
        print("\n🎉 Build completed successfully!")
        print("\n📦 Distribution files:")
        print("  - dist/JARVIS_AI_Assistant.exe (Main executable)")
        print("  - dist/install_jarvis.bat (Installer script)")
        print("  - dist/README.txt (User documentation)")
        
        print("\n📋 Next steps:")
        print("  1. Test the executable: dist/JARVIS_AI_Assistant.exe")
        print("  2. Share the dist/ folder with users")
        print("  3. Users can run install_jarvis.bat as Admin for system install")
        
    else:
        print("\n❌ Build failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
