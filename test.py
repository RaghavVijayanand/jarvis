#!/usr/bin/env python3
"""
JARVIS Test Suite
Basic tests to verify JARVIS functionality
"""

import sys
import os
from pathlib import Path

# Add the current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test if all required modules can be imported"""
    print("🧪 Testing imports...")
    
    tests = [
        ("speech_recognition", "Speech Recognition"),
        ("pyttsx3", "Text-to-Speech"),
        ("requests", "HTTP Requests"),
        ("psutil", "System Information"),
        ("rich", "Rich Console"),
        ("config", "JARVIS Config"),
        ("brain", "AI Brain"),
        ("voice_engine", "Voice Engine"),
        ("system_control", "System Control")
    ]
    
    results = []
    
    for module, description in tests:
        try:
            __import__(module)
            print(f"✅ {description}")
            results.append(True)
        except ImportError as e:
            print(f"❌ {description}: {e}")
            results.append(False)
        except Exception as e:
            print(f"⚠️  {description}: {e}")
            results.append(False)
    
    return all(results)

def test_voice_engine():
    """Test voice engine initialization"""
    print("\n🎤 Testing voice engine...")
    
    try:
        from voice_engine import VoiceEngine
        
        # Test TTS initialization
        engine = VoiceEngine()
        print("✅ Voice engine initialized")
        
        # Test TTS
        print("🔊 Testing text-to-speech...")
        speak_thread = engine.speak("JARVIS voice systems online.")
        if speak_thread:
            print("✅ Text-to-speech working")
        else:
            print("⚠️  Text-to-speech may have issues")
        
        return True
        
    except Exception as e:
        print(f"❌ Voice engine test failed: {e}")
        return False

def test_ai_brain():
    """Test AI brain functionality"""
    print("\n🧠 Testing AI brain...")
    
    try:
        from brain import AIBrain
        
        brain = AIBrain()
        print("✅ AI brain initialized")
        
        # Test basic command processing
        response = brain.process_command("hello")
        if response:
            print(f"✅ AI response: {response}")
        else:
            print("⚠️  AI brain returned empty response")
        
        return True
        
    except Exception as e:
        print(f"❌ AI brain test failed: {e}")
        return False

def test_system_control():
    """Test system control functionality"""
    print("\n💻 Testing system control...")
    
    try:
        from system_control import SystemControl
        
        control = SystemControl()
        print("✅ System control initialized")
        
        # Test system status
        status = control.get_system_status()
        if status and len(status) > 50:  # Basic check for reasonable output
            print("✅ System status retrieved")
        else:
            print("⚠️  System status may be incomplete")
        
        return True
        
    except Exception as e:
        print(f"❌ System control test failed: {e}")
        return False

def test_skills():
    """Test skill modules"""
    print("\n🛠️  Testing skills...")
    
    try:
        from skills.utility import UtilitySkill
        from skills.weather import WeatherSkill
        from skills.web_search import WebSearchSkill
        
        # Test utility skill
        utility = UtilitySkill()
        joke = utility.tell_joke()
        if joke:
            print("✅ Utility skill working")
        
        # Test weather skill
        weather = WeatherSkill()
        print("✅ Weather skill initialized")
        
        # Test web search skill
        web = WebSearchSkill()
        print("✅ Web search skill initialized")
        
        return True
        
    except Exception as e:
        print(f"❌ Skills test failed: {e}")
        return False

def test_configuration():
    """Test configuration loading"""
    print("\n⚙️  Testing configuration...")
    
    try:
        from config import Config
        
        # Check basic config values
        if hasattr(Config, 'WAKE_WORD'):
            print(f"✅ Wake word: {Config.WAKE_WORD}")
        
        if hasattr(Config, 'PERSONALITY'):
            print(f"✅ Personality configured: {Config.PERSONALITY.get('name', 'Unknown')}")
        
        # Check directories
        if hasattr(Config, 'BASE_DIR'):
            print(f"✅ Base directory: {Config.BASE_DIR}")
        
        return True
        
    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🤖 JARVIS Test Suite")
    print("=" * 40)
    
    tests = [
        test_imports,
        test_configuration,
        test_ai_brain,
        test_system_control,
        test_skills,
        test_voice_engine  # Last because it might make noise
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"💥 Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 40)
    print("📊 Test Results:")
    print(f"Passed: {sum(results)}/{len(results)}")
    
    if all(results):
        print("🎉 All tests passed! JARVIS is ready to run.")
        print("\nTo start JARVIS:")
        print("  python jarvis.py        (voice mode)")
        print("  python jarvis.py text   (text mode)")
    else:
        print("⚠️  Some tests failed. JARVIS may have limited functionality.")
        print("Run 'python setup.py' to install missing dependencies.")
    
    return all(results)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n💥 Test suite failed: {e}")
