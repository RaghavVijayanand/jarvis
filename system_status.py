#!/usr/bin/env python3
"""
JARVIS System Status and Validation Summary
Final check that everything works as intended
"""

import sys
import os
import time
from datetime import datetime

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def show_system_overview():
    """Show comprehensive system overview"""
    print("🤖 JARVIS SYSTEM STATUS REPORT")
    print("="*60)
    print(f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💻 Platform: {os.name}")
    print(f"📂 Working Directory: {os.getcwd()}")
    print()

def check_core_components():
    """Check all core components"""
    print("🔧 CORE COMPONENTS STATUS")
    print("-"*40)
    
    components = []
    
    # Main JARVIS Class
    try:
        from jarvis import JARVIS
        components.append(("✅", "JARVIS Main Class", "Ready"))
    except Exception as e:
        components.append(("❌", "JARVIS Main Class", f"Error: {e}"))
    
    # Screen Automation
    try:
        from skills.screen_automation import ScreenAutomationSkill, process_automation_command
        automation = ScreenAutomationSkill()
        screenshot = automation.take_screenshot()
        if os.path.exists(screenshot):
            size = os.path.getsize(screenshot)
            components.append(("✅", "Screen Automation", f"Working - Screenshot: {size:,} bytes"))
        else:
            components.append(("⚠️", "Screen Automation", "Screenshot failed"))
        automation.cleanup()
    except Exception as e:
        components.append(("❌", "Screen Automation", f"Error: {e}"))
    
    # Visual Task Orchestrator
    try:
        from skills.visual_task_orchestrator import CompleteVisualTaskOrchestrator, process_visual_task
        orchestrator = CompleteVisualTaskOrchestrator()
        components.append(("✅", "Visual Task Orchestrator", "Ready"))
    except Exception as e:
        components.append(("❌", "Visual Task Orchestrator", f"Error: {e}"))
    
    # Dynamic App Selector
    try:
        from skills.dynamic_app_selector import DynamicAppSelector
        selector = DynamicAppSelector()
        apps_dict = selector.discover_all_applications()
        total_apps = sum(len(app_list) for app_list in apps_dict.values())
        components.append(("✅", "App Discovery System", f"{total_apps:,} apps found"))
    except Exception as e:
        components.append(("❌", "App Discovery System", f"Error: {e}"))
    
    # Command Processor
    try:
        class MockJARVIS:
            pass
        from skills.command_processor import CommandProcessor
        processor = CommandProcessor(MockJARVIS())
        components.append(("✅", "Command Processor", "Ready"))
    except Exception as e:
        components.append(("❌", "Command Processor", f"Error: {e}"))
    
    # Configuration
    try:
        from config import Config
        components.append(("✅", "Configuration System", f"Screenshots: {Config.AUTOMATION_SCREENSHOT_PATH}"))
    except Exception as e:
        components.append(("❌", "Configuration System", f"Error: {e}"))
    
    # Print results
    for status, component, message in components:
        print(f"{status} {component:<25} {message}")
    
    return components

def check_api_status():
    """Check API configuration and status"""
    print("\n🧠 AI INTEGRATION STATUS")
    print("-"*40)
    
    # API Keys
    openrouter_key = os.getenv('OPENROUTER_API_KEY')
    gemini_key = os.getenv('GEMINI_API_KEY')
    
    print(f"{'✅' if openrouter_key else '⚠️'} OpenRouter API Key: {'Configured' if openrouter_key else 'Not configured'}")
    print(f"{'✅' if gemini_key else '⚠️'} Gemini API Key: {'Configured' if gemini_key else 'Not configured'}")
    
    # OpenRouter Brain
    if openrouter_key:
        try:
            from openrouter_brain import OpenRouterBrain
            brain = OpenRouterBrain()
            print("✅ OpenRouter Brain: Ready for AI processing")
        except Exception as e:
            print(f"❌ OpenRouter Brain: Error - {e}")
    
    # Vision Features
    vision_available = bool(openrouter_key or gemini_key)
    print(f"{'✅' if vision_available else '⚠️'} AI Vision Features: {'Available' if vision_available else 'Limited (no API keys)'}")
    
    return vision_available

def check_directory_structure():
    """Check directory structure"""
    print("\n📁 DIRECTORY STRUCTURE")
    print("-"*40)
    
    required_dirs = [
        "skills",
        "cache",
        "cache/screenshots", 
        "cache/task_screenshots",
        "logs",
        "memory",
        "data"
    ]
    
    for directory in required_dirs:
        exists = os.path.exists(directory)
        print(f"{'✅' if exists else '❌'} {directory:<25} {'Exists' if exists else 'Missing'}")
        
        if not exists:
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"   📁 Created directory: {directory}")
            except Exception as e:
                print(f"   ❌ Failed to create: {e}")

def show_usage_guide():
    """Show comprehensive usage guide"""
    print("\n📚 COMPREHENSIVE USAGE GUIDE")
    print("="*60)
    
    print("""
🚀 QUICK START COMMANDS:

1. GUI Interface (Recommended):
   python main_gui.py

2. Command Line Interface:
   python jarvis.py

3. Direct Function Calls:
   # Take screenshot
   python -c "from skills.screen_automation import ScreenAutomationSkill; ScreenAutomationSkill().take_screenshot()"
   
   # Discover apps
   python -c "from skills.dynamic_app_selector import DynamicAppSelector; print(f'Found {sum(len(apps) for apps in DynamicAppSelector().discover_all_applications().values())} apps')"
   
   # Visual task automation
   python -c "from skills.visual_task_orchestrator import process_visual_task; print(process_visual_task('take screenshot'))"

🎯 AUTOMATION CAPABILITIES:

Screen Automation:
   • "click on start button"
   • "find and click calculator"
   • "press the OK button"
   • "locate and click File menu"

Complex Multi-Step Tasks:
   • "open calculator and calculate 5+3"
   • "take screenshot then open notepad"
   • "launch browser and navigate to google.com"
   • "set an alarm for 8:30 AM"

File Operations:
   • "create file about space exploration"
   • "create folder called projects"
   • "read file config.py"
   • "create detailed file about machine learning"

System Commands:
   • "take screenshot"
   • "launch calculator"
   • "get system health"
   • "list all windows"

🔧 MAIN ENTRY POINTS:

1. process_automation_command(command, jarvis_instance)
   - For basic screen automation
   - Handles clicking, typing, key presses

2. process_visual_task(task_description)
   - For complex multi-step tasks
   - Uses AI vision for dynamic task execution

3. JARVIS.process_command(command, use_voice=True)
   - Full JARVIS command processing
   - Integrates all subsystems

🧠 AI FEATURES (Requires API Keys):

• Dynamic visual task analysis
• Smart element detection on screen
• Intelligent app selection for tasks
• Complex task planning and execution
• Natural language command processing

📝 ENVIRONMENT VARIABLES:

Required for AI features:
   set OPENROUTER_API_KEY=your_key_here
   set GEMINI_API_KEY=your_key_here

Optional:
   set AUTOMATION_SAFE=1  # Enables destructive test operations
   set CI=1               # Disables interactive features in CI
""")

def run_final_validation():
    """Run final validation tests"""
    print("\n🧪 FINAL VALIDATION TESTS")
    print("="*50)
    
    tests_passed = 0
    total_tests = 0
    
    # Test 1: Screenshot
    print("📸 Test: Screenshot Capture")
    try:
        from skills.screen_automation import ScreenAutomationSkill
        automation = ScreenAutomationSkill()
        screenshot = automation.take_screenshot()
        if os.path.exists(screenshot):
            print(f"   ✅ PASS - Screenshot captured: {os.path.basename(screenshot)}")
            tests_passed += 1
        else:
            print(f"   ❌ FAIL - Screenshot not created")
        automation.cleanup()
    except Exception as e:
        print(f"   ❌ FAIL - Error: {e}")
    total_tests += 1
    
    # Test 2: App Discovery
    print("🔍 Test: Application Discovery")
    try:
        from skills.dynamic_app_selector import DynamicAppSelector
        selector = DynamicAppSelector()
        apps = selector.discover_all_applications()
        total_apps = sum(len(app_list) for app_list in apps.values())
        if total_apps > 0:
            print(f"   ✅ PASS - Found {total_apps:,} applications")
            tests_passed += 1
        else:
            print(f"   ❌ FAIL - No applications found")
    except Exception as e:
        print(f"   ❌ FAIL - Error: {e}")
    total_tests += 1
    
    # Test 3: App Selection
    print("🎯 Test: Smart App Selection")
    try:
        best_app = selector.find_best_app_for_task("calculator")
        if best_app:
            print(f"   ✅ PASS - Found calculator: {best_app.get('name')}")
            tests_passed += 1
        else:
            print(f"   ❌ FAIL - Calculator not found")
    except Exception as e:
        print(f"   ❌ FAIL - Error: {e}")
    total_tests += 1
    
    # Test 4: Entry Points
    print("🔧 Test: Entry Point Functions")
    try:
        from skills.screen_automation import process_automation_command
        from skills.visual_task_orchestrator import process_visual_task
        
        if callable(process_automation_command) and callable(process_visual_task):
            print(f"   ✅ PASS - All entry points available")
            tests_passed += 1
        else:
            print(f"   ❌ FAIL - Entry points not callable")
    except Exception as e:
        print(f"   ❌ FAIL - Error: {e}")
    total_tests += 1
    
    # Results
    success_rate = (tests_passed / total_tests) * 100
    print(f"\n📊 VALIDATION RESULTS:")
    print(f"   Tests Passed: {tests_passed}/{total_tests}")
    print(f"   Success Rate: {success_rate:.1f}%")
    print(f"   Status: {'🎉 ALL SYSTEMS OPERATIONAL' if tests_passed == total_tests else '⚠️ SOME ISSUES DETECTED'}")
    
    return tests_passed == total_tests

def main():
    """Main status check"""
    show_system_overview()
    
    components = check_core_components()
    vision_available = check_api_status()
    check_directory_structure()
    
    # Overall system status
    failed_components = [c for c in components if c[0] == "❌"]
    
    print(f"\n🎯 OVERALL SYSTEM STATUS")
    print("="*40)
    
    if not failed_components:
        print("🎉 ALL CORE COMPONENTS OPERATIONAL")
        print("✅ JARVIS is fully functional and ready for use!")
    else:
        print(f"⚠️ {len(failed_components)} COMPONENTS NEED ATTENTION")
        for status, component, message in failed_components:
            print(f"   • {component}: {message}")
    
    if vision_available:
        print("🧠 AI Vision features available")
    else:
        print("⚠️ AI Vision features limited (configure API keys)")
    
    # Run final validation
    all_tests_passed = run_final_validation()
    
    show_usage_guide()
    
    print(f"\n{'🚀 JARVIS SYSTEM READY FOR OPERATION! 🚀' if all_tests_passed and not failed_components else '⚠️ SYSTEM PARTIALLY OPERATIONAL ⚠️'}")
    
    return 0 if (all_tests_passed and not failed_components) else 1

if __name__ == "__main__":
    sys.exit(main())
