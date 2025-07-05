#!/usr/bin/env python3
"""
Simple JARVIS Starter
Minimal version that works with just Python standard library + basic packages
"""

import sys
import os

def check_dependencies():
    """Check if required packages are available"""
    required = ["pyttsx3", "psutil", "rich", "colorama"]
    missing = []
    
    for package in required:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    return missing

def install_dependencies(packages):
    """Install missing dependencies"""
    import subprocess
    
    for package in packages:
        print(f"Installing {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        except subprocess.CalledProcessError:
            print(f"Failed to install {package}")
            return False
    return True

def main():
    print("🤖 JARVIS - Native AI Assistant")
    print("=" * 40)
    
    # Check dependencies
    missing = check_dependencies()
    
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        response = input("Install them now? (y/n): ").lower()
        
        if response == 'y':
            if install_dependencies(missing):
                print("Dependencies installed successfully!")
            else:
                print("Failed to install some dependencies.")
                return
        else:
            print("Cannot run without dependencies.")
            return
    
    # Import and run JARVIS
    try:
        from jarvis import JARVIS
        
        print("\nStarting JARVIS...")
        jarvis = JARVIS()
        
        # Choose mode
        print("\nSelect mode:")
        print("1. Text Mode (keyboard input, text output)")
        print("2. Voice Mode (keyboard input, voice output)")
        
        choice = input("Enter choice (1 or 2): ").strip()
        
        if choice == "2":
            jarvis.start("voice")
        else:
            jarvis.start("text")
            
    except ImportError as e:
        print(f"Error importing JARVIS: {e}")
        print("Make sure all JARVIS files are in the current directory.")
    except Exception as e:
        print(f"Error starting JARVIS: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
    except Exception as e:
        print(f"\nError: {e}")
