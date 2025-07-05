#!/usr/bin/env python3
"""
JARVIS Setup Script
Installs dependencies and sets up the JARVIS AI Assistant
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"Error: {e.stderr}")
        return False

def check_python_version():
    """Check if Python version is compatible"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print("❌ Python 3.8 or higher is required")
        print(f"Current version: {version.major}.{version.minor}.{version.micro}")
        return False
    
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} detected")
    return True

def install_dependencies():
    """Install required Python packages"""
    print("📦 Installing Python dependencies...")
    
    # Upgrade pip first
    if not run_command(f"{sys.executable} -m pip install --upgrade pip", "Upgrading pip"):
        return False
    
    # Install requirements
    requirements_file = Path(__file__).parent / "requirements.txt"
    if requirements_file.exists():
        if not run_command(f"{sys.executable} -m pip install -r {requirements_file}", "Installing dependencies"):
            return False
    else:
        print("❌ requirements.txt not found")
        return False
    
    return True

def setup_environment():
    """Set up environment file"""
    env_example = Path(__file__).parent / ".env.example"
    env_file = Path(__file__).parent / ".env"
    
    if not env_file.exists() and env_example.exists():
        print("🔧 Setting up environment file...")
        try:
            with open(env_example, 'r') as src, open(env_file, 'w') as dst:
                dst.write(src.read())
            print("✅ Created .env file from template")
            print("ℹ️  Please edit .env file to add your API keys")
        except Exception as e:
            print(f"❌ Failed to create .env file: {e}")
            return False
    elif env_file.exists():
        print("✅ Environment file already exists")
    
    return True

def test_microphone():
    """Test microphone availability"""
    print("🎤 Testing microphone...")
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        
        # Check for input devices
        input_devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                input_devices.append(info['name'])
        
        p.terminate()
        
        if input_devices:
            print("✅ Microphone devices found:")
            for device in input_devices[:3]:  # Show first 3
                print(f"   - {device}")
        else:
            print("⚠️  No microphone devices detected")
            print("   Voice features may not work properly")
        
        return True
        
    except ImportError:
        print("❌ PyAudio not installed - microphone test skipped")
        return False
    except Exception as e:
        print(f"⚠️  Microphone test failed: {e}")
        return True  # Don't fail setup for this

def create_directories():
    """Create necessary directories"""
    print("📁 Creating directories...")
    
    base_dir = Path(__file__).parent
    directories = ["logs", "data", "skills"]
    
    for dir_name in directories:
        dir_path = base_dir / dir_name
        dir_path.mkdir(exist_ok=True)
        print(f"✅ Created/verified {dir_name} directory")
    
    return True

def main():
    """Main setup function"""
    print("🤖 JARVIS AI Assistant Setup")
    print("=" * 40)
    
    success = True
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Create directories
    if not create_directories():
        success = False
    
    # Install dependencies
    if not install_dependencies():
        success = False
    
    # Setup environment
    if not setup_environment():
        success = False
    
    # Test microphone
    test_microphone()
    
    print("\n" + "=" * 40)
    
    if success:
        print("🎉 JARVIS setup completed successfully!")
        print("\nNext steps:")
        print("1. Edit .env file to add your API keys (optional)")
        print("2. Run JARVIS:")
        print("   - Voice mode: python jarvis.py")
        print("   - Text mode:  python jarvis.py text")
        print("\n💡 For voice features, make sure you have a microphone connected")
    else:
        print("❌ Setup completed with errors")
        print("Some features may not work properly")
    
    return success

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Setup interrupted by user")
    except Exception as e:
        print(f"\n💥 Setup failed with error: {e}")
