#!/usr/bin/env python3
"""
Simple test script to verify JARVIS functionality
"""

import sys
from pathlib import Path

# Add jarvis directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_basic_functionality():
    """Test basic JARVIS functionality"""
    print("🧪 Testing JARVIS basic functionality...")
    
    try:
        # Test imports
        from config import Config
        from multi_model_brain import MultiModelBrain
        from jarvis import JARVIS
        print("✅ All imports successful")
        
        # Test configuration
        print(f"✅ Config loaded - Debug mode: {Config.DEBUG_MODE}")
        
        # Test multi-model brain
        brain = MultiModelBrain()
        print(f"✅ MultiModelBrain initialized - Available models: {len(brain.available_models)}")
        
        # Test basic response
        response = brain.process_command("Hello, test message")
        print(f"✅ Basic response generated: {response[:50]}...")
        
        print("\n🎉 All tests passed! JARVIS is ready to use.")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = test_basic_functionality()
    sys.exit(0 if success else 1)
