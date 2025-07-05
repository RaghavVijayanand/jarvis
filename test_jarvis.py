#!/usr/bin/env python3
"""
JARVIS System Test - Quick verification that all components work
"""

import sys
import os
from pathlib import Path

# Add the jarvis directory to Python path
jarvis_dir = Path(__file__).parent
sys.path.insert(0, str(jarvis_dir))

def test_imports():
    """Test if all required modules can be imported"""
    print("Testing imports...")
    
    try:
        import pyttsx3
        print("✅ pyttsx3 (Text-to-Speech)")
    except ImportError:
        print("❌ pyttsx3 not found - install with: pip install pyttsx3")
        return False
    
    try:
        import psutil
        print("✅ psutil (System monitoring)")
    except ImportError:
        print("❌ psutil not found - install with: pip install psutil")
        return False
    
    try:
        from rich.console import Console
        print("✅ rich (Console formatting)")
    except ImportError:
        print("❌ rich not found - install with: pip install rich")
        return False
    
    try:
        import requests
        print("✅ requests (HTTP client)")
    except ImportError:
        print("❌ requests not found - install with: pip install requests")
        return False
    
    try:
        import speech_recognition
        print("✅ speech_recognition (Voice input)")
    except ImportError:
        print("⚠️ speech_recognition not found - voice input won't work")
        print("   Install with: pip install SpeechRecognition")
    
    return True

def test_core_modules():
    """Test JARVIS core modules"""
    print("\nTesting JARVIS core modules...")
    
    try:
        from config import Config
        print("✅ config.py")
    except ImportError as e:
        print(f"❌ config.py: {e}")
        return False
    
    try:
        from voice_engine import VoiceEngine
        print("✅ voice_engine.py")
    except ImportError as e:
        print(f"❌ voice_engine.py: {e}")
        return False
    
    try:
        from brain import AIBrain
        print("✅ brain.py")
    except ImportError as e:
        print(f"❌ brain.py: {e}")
        return False
    
    try:
        from advanced_brain import AdvancedAIBrain
        print("✅ advanced_brain.py")
    except ImportError as e:
        print(f"❌ advanced_brain.py: {e}")
        return False
    
    return True

def test_skills():
    """Test JARVIS skills modules"""
    print("\nTesting skills modules...")
    
    skills = [
        ("weather", "WeatherSkill"),
        
        ("utility", "UtilitySkill"),
        ("file_manager", "FileManagerSkill")
    ]
    
    for skill_name, class_name in skills:
        try:
            module = __import__(f"skills.{skill_name}", fromlist=[class_name])
            skill_class = getattr(module, class_name)
            print(f"✅ skills/{skill_name}.py")
        except ImportError as e:
            print(f"❌ skills/{skill_name}.py: {e}")
            return False
        except AttributeError as e:
            print(f"❌ skills/{skill_name}.py - {class_name} not found: {e}")
            return False
    
    return True

def test_basic_functionality():
    """Test basic JARVIS functionality"""
    print("\nTesting basic JARVIS functionality...")
    
    try:
        from brain import AIBrain
        brain = AIBrain()
        
        # Test basic response
        response = brain.process_command("hello")
        if response:
            print("✅ Basic AI response generation")
        else:
            print("❌ Basic AI response failed")
            return False
        
        # Test voice engine (TTS only)
        from voice_engine import VoiceEngine
        voice = VoiceEngine()
        print("✅ Voice engine initialization")
        
        # Test skills
        from skills.utility import UtilitySkill
        utility = UtilitySkill()
        result = utility.calculate("2 + 2")
        if "4" in str(result):
            print("✅ Basic calculation skill")
        else:
            print("❌ Calculation skill failed")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Basic functionality test failed: {e}")
        return False



def main():
    """Run all tests"""
    print("JARVIS System Test")
    print("=" * 50)
    
    all_passed = True
    
    # Run tests
    if not test_imports():
        all_passed = False
    
    if not test_core_modules():
        all_passed = False
    
    if not test_skills():
        all_passed = False
    
    if not test_basic_functionality():
        all_passed = False
    
    
    
    print("\n" + "=" * 50)
    if all_passed:
        print("All critical tests passed! JARVIS is ready to run.")
        print("\nQuick start:")
        print("   Text mode: python run_jarvis.py text")
        print("   Voice mode: python run_jarvis.py voice")
        print("   Windows: double-click start_jarvis.bat")
    else:
        print("❌ Some tests failed. Please fix the issues above.")
        print("\n💡 Try running: python setup.py install")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
