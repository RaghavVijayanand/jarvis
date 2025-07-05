#!/usr/bin/env python3
"""
JARVIS Launcher - Simple script to run JARVIS AI Assistant
"""

import sys
import os
from pathlib import Path

# Add the jarvis directory to Python path
jarvis_dir = Path(__file__).parent
sys.path.insert(0, str(jarvis_dir))

def main():
    """Main launcher function"""
    print("🤖 JARVIS AI Assistant Launcher")
    print("=" * 40)
    
    # Check if jarvis.py exists
    jarvis_script = jarvis_dir / "jarvis.py"
    if not jarvis_script.exists():
        print("❌ jarvis.py not found in current directory")
        return
    
    try:
        # Import and run JARVIS
        from jarvis import JARVIS
        
        # Check command line arguments
        mode = "text"  # default mode
        
        if len(sys.argv) > 1:
            arg = sys.argv[1].lower()
            if arg in ["voice", "v", "-v", "--voice"]:
                mode = "voice"
                print("🎤 Starting JARVIS in voice mode...")
            elif arg in ["text", "t", "-t", "--text"]:
                mode = "text"
                print("📝 Starting JARVIS in text mode...")
            elif arg in ["help", "h", "-h", "--help"]:
                print("Usage: python run_jarvis.py [mode]")
                print("Modes:")
                print("  text  - Text input/output mode (default)")
                print("  voice - Voice mode with speech recognition")
                print("  help  - Show this help message")
                return
            else:
                print(f"❌ Unknown mode '{arg}'. Using text mode.")
                mode = "text"
        
        # Create and start JARVIS
        jarvis = JARVIS()
        jarvis.start(mode)
        
    except KeyboardInterrupt:
        print("\n👋 JARVIS shutdown by user")
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("💡 Try running: python setup.py install")
    except Exception as e:
        print(f"❌ Error starting JARVIS: {e}")
        print("💡 Make sure all dependencies are installed")

if __name__ == "__main__":
    main()
