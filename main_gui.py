import sys
import os
import json
import asyncio
import threading
import subprocess
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, 
    QTextEdit, QLineEdit, QPushButton, QComboBox, QLabel, QSplitter,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QProgressBar, QStatusBar, QMenuBar, QMenu, QCheckBox, QSpinBox,
    QDialog, QListWidget, QDialogButtonBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QTextCursor, QAction

# Import all JARVIS modules for full functionality
from multi_model_brain import MultiModelBrain
from settings_dialog import SettingsDialog
from config import Config
from voice_engine import VoiceEngine
from skills.weather import WeatherSkill
from skills.utility import UtilitySkill
from skills.file_manager import FileManagerSkill
from skills.web_search import WebSearchSkill
from skills.system_monitor import SystemMonitor

# Import enhanced JARVIS capabilities
from skills.automation import AutomationSkill
from skills.app_control import ApplicationControl
from skills.command_processor import CommandProcessor
from skills.task_scheduler import TaskScheduler
from skills.screen_automation import ScreenAutomationSkill

class JarvisWorker(QThread):
    """Fast worker thread for processing commands"""
    response_ready = Signal(str)
    error_occurred = Signal(str)
    status_update = Signal(str)
    
    def __init__(self, jarvis_instance, skills, voice_engine=None):
        super().__init__()
        self.jarvis = jarvis_instance  # Use the main JARVIS instance
        self.brain = jarvis_instance.brain  # Keep for backward compatibility  
        self.skills = skills
        self.voice_engine = voice_engine
        self.current_command = ""
        self.voice_enabled = False
        
    def set_command(self, command, voice_enabled=False):
        self.current_command = command
        self.voice_enabled = voice_enabled
        
    def run(self):
        try:
            self.status_update.emit("Processing...")
            
            # Use the main JARVIS process_command method with all improvements
            response = self.jarvis.process_command(self.current_command, use_voice=self.voice_enabled)
            
            if response:
                self.response_ready.emit(response)
            else:
                self.response_ready.emit("I completed the task, but didn't receive a specific response.")
            
            self.status_update.emit("Ready")
                
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            self.error_occurred.emit(error_msg)
            self.status_update.emit("Error")


class VoiceChatWorker(QThread):
    """Worker thread for continuous voice conversation"""
    message_received = Signal(str)
    response_ready = Signal(str)
    status_update = Signal(str)
    error_occurred = Signal(str)
    
    def __init__(self, brain, voice_engine, skills):
        super().__init__()
        self.brain = brain
        self.voice_engine = voice_engine
        self.skills = skills
        self.active = False
        
    def run(self):
        """Main voice chat loop"""
        self.active = True
        self.status_update.emit("Voice chat active - Start speaking...")
        
        while self.active:
            try:
                # Listen for voice input with longer phrase timeout for natural speech
                self.status_update.emit("🎤 Listening...")
                command = self.voice_engine.listen_continuously(timeout=60, phrase_timeout=3)
                
                if command:
                    # Show what was heard
                    self.message_received.emit(f"You said: {command}")
                    
                    # Process with skill-based logic (same as GUI text processing)
                    self.status_update.emit("🤔 Processing...")
                    response = self._process_command_with_skills(command)
                    
                    if response:
                        # Show response and speak it
                        self.response_ready.emit(response)
                        self.status_update.emit("🗣️ Speaking...")
                        
                        # Speak the response (shorten if too long)
                        voice_response = response
                        if len(response) > 300:
                            sentences = response.split('. ')
                            voice_response = sentences[0] + "." if sentences else response[:200] + "..."
                        
                        self.voice_engine.speak(voice_response)
                        
                        # Brief pause before listening again
                        self.msleep(1000)
                    else:
                        self.response_ready.emit("I'm not sure how to respond to that.")
                        self.voice_engine.speak("I'm not sure how to respond to that.")
                        
                elif self.active:  # Only continue if still active - no timeout message
                    # Just continue listening - no status message for timeouts
                    pass
                    
            except Exception as e:
                if self.active:  # Only show errors if still active
                    error_msg = f"Voice chat error: {str(e)}"
                    self.error_occurred.emit(error_msg)
                    self.msleep(2000)  # Wait before retrying
        
        self.status_update.emit("Voice chat stopped")
    
    def _process_command_with_skills(self, command):
        """Process command using the same skill logic as the main GUI"""
        try:
            command_lower = command.lower()
            
            # Use the same skill processing logic as JarvisWorker
            if any(word in command_lower for word in ['weather', 'temperature', 'forecast']):
                return self.skills['weather'].get_weather()
                
            elif any(word in command_lower for word in ['system', 'cpu', 'memory', 'disk', 'performance']):
                return self.skills['system_monitor'].get_system_info()
                
            elif any(word in command_lower for word in ['file', 'folder', 'directory', 'create', 'delete']):
                return self.skills['file_manager'].handle_file_command(command)
                
            elif any(word in command_lower for word in ['search', 'google', 'find', 'web']):
                return self.skills['web_search'].search_web(command, llm_brain=self.brain)
                
            elif any(word in command_lower for word in ['joke', 'funny', 'humor']):
                return self.skills['utility'].tell_joke()
                
            elif any(word in command_lower for word in ['calculate', 'math', 'compute']) or any(op in command for op in ['+', '-', '*', '/', '=']):
                return self.skills['utility'].calculate(command)
                
            elif any(word in command_lower for word in ['open', 'launch', 'start']):
                # Handle application opening with better detection
                return self._handle_app_opening(command)
            else:
                # Use the AI brain for general queries
                response = self.brain.process_command(command)
                if not response or "stub" in response.lower() or "not configured" in response.lower():
                    return f"I received your message: '{command}'. The AI model needs to be configured with API keys."
                return response
                
        except Exception as e:
            return f"Processing error: {str(e)}"
    
    def _handle_app_opening(self, command):
        """Handle opening various applications"""
        command_lower = command.lower()
        
        # Common applications mapping
        app_mappings = {
            'calculator': 'calc.exe',
            'calc': 'calc.exe', 
            'notepad': 'notepad.exe',
            'paint': 'mspaint.exe',
            'opera': 'C:\\Users\\%USERNAME%\\AppData\\Local\\Programs\\Opera\\opera.exe',
            'chrome': 'chrome.exe',
            'firefox': 'firefox.exe',
            'edge': 'msedge.exe',
            'settings': 'ms-settings:',
            'control panel': 'control.exe',
            'task manager': 'taskmgr.exe',
            'file explorer': 'explorer.exe',
            'cmd': 'cmd.exe',
            'command prompt': 'cmd.exe',
            'powershell': 'powershell.exe',
            'comet': None  # Will search for Comet
        }
        
        # Extract the app name from the command
        app_name = None
        for trigger in ['open ', 'launch ', 'start ']:
            if trigger in command_lower:
                app_name = command_lower.split(trigger, 1)[1].strip()
                break
        
        if not app_name:
            return "Please specify which application to open."
        
        # Try direct mapping first
        for key, executable in app_mappings.items():
            if key in app_name:
                try:
                    if executable is None:
                        # Special handling for apps that need searching
                        if key == 'comet':
                            return self._find_and_open_app('comet')
                    elif executable.startswith('ms-settings:'):
                        # Open Windows Settings
                        subprocess.Popen(['start', executable], shell=True)
                        return f"{key.title()} opened successfully!"
                    elif '%USERNAME%' in executable:
                        # Expand environment variables
                        expanded_path = os.path.expandvars(executable)
                        if os.path.exists(expanded_path):
                            subprocess.Popen([expanded_path])
                            return f"{key.title()} opened successfully!"
                        else:
                            # Try alternative Opera locations
                            alt_paths = [
                                'C:\\Program Files\\Opera\\opera.exe',
                                'C:\\Program Files (x86)\\Opera\\opera.exe'
                            ]
                            for path in alt_paths:
                                if os.path.exists(path):
                                    subprocess.Popen([path])
                                    return f"{key.title()} opened successfully!"
                            return f"{key.title()} not found in common locations."
                    else:
                        # Standard executable
                        subprocess.Popen([executable])
                        return f"{key.title()} opened successfully!"
                except Exception as e:
                    return f"Could not open {key}: {str(e)}"
        
        # If no direct mapping, try to find the app
        return self._find_and_open_app(app_name)
    
    def _find_and_open_app(self, app_name):
        """Find and open an application by searching common locations"""
        try:
            # Common installation directories
            search_paths = [
                os.path.expandvars(r'C:\Program Files'),
                os.path.expandvars(r'C:\Program Files (x86)'),
                os.path.expandvars(r'C:\Users\%USERNAME%\AppData\Local\Programs'),
                os.path.expandvars(r'C:\Users\%USERNAME%\AppData\Roaming'),
            ]
            
            # Search for executable files
            for search_path in search_paths:
                if os.path.exists(search_path):
                    for root, dirs, files in os.walk(search_path):
                        for file in files:
                            if (file.lower().endswith('.exe') and 
                                app_name.lower() in file.lower()):
                                full_path = os.path.join(root, file)
                                try:
                                    subprocess.Popen([full_path])
                                    return f"{app_name.title()} opened successfully!"
                                except:
                                    continue
            
            # Try Windows search as fallback
            try:
                subprocess.Popen(['start', app_name], shell=True)
                return f"Attempted to open {app_name.title()}."
            except:
                return f"Could not find or open {app_name.title()}."
                
        except Exception as e:
            return f"Error searching for {app_name}: {str(e)}"
    
    def stop(self):
        """Stop the voice chat loop"""
        self.active = False


class MicrophoneSettingsDialog(QDialog):
    """Dialog for selecting microphone"""
    def __init__(self, voice_engine, parent=None):
        super().__init__(parent)
        self.voice_engine = voice_engine
        self.setWindowTitle("Microphone Settings")
        self.setModal(True)
        self.resize(500, 400)
        
        layout = QVBoxLayout()
        
        # Current microphone info
        layout.addWidget(QLabel("Current Microphone:"))
        self.current_mic_label = QLabel(self.voice_engine.get_current_microphone_info())
        layout.addWidget(self.current_mic_label)
        
        layout.addWidget(QLabel(""))  # Spacer
        layout.addWidget(QLabel("Available Microphones:"))
        
        # Microphone list
        self.mic_list = QListWidget()
        self.populate_microphones()
        layout.addWidget(self.mic_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.test_button = QPushButton("Test Selected")
        self.test_button.clicked.connect(self.test_microphone)
        button_layout.addWidget(self.test_button)
        
        self.refresh_button = QPushButton("Refresh List")
        self.refresh_button.clicked.connect(self.populate_microphones)
        button_layout.addWidget(self.refresh_button)
        
        layout.addLayout(button_layout)
        
        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def populate_microphones(self):
        """Populate the microphone list"""
        self.mic_list.clear()
        microphones = self.voice_engine.get_available_microphones()
        
        if not microphones:
            self.mic_list.addItem("No microphones found")
            return
        
        for mic in microphones:
            display_text = f"[{mic['index']}] {mic['name']}"
            if mic['is_default']:
                display_text += " (Default)"
            
            self.mic_list.addItem(display_text)
            
            # Select current microphone if any
            if (self.voice_engine.selected_mic_index is not None and 
                mic['index'] == self.voice_engine.selected_mic_index):
                self.mic_list.setCurrentRow(mic['index'])
    
    def test_microphone(self):
        """Test the selected microphone"""
        current_item = self.mic_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Warning", "Please select a microphone to test.")
            return
        
        # Extract microphone index from the text
        text = current_item.text()
        try:
            mic_index = int(text.split(']')[0].split('[')[1])
            
            # Temporarily set the microphone for testing
            original_mic_index = self.voice_engine.selected_mic_index
            if self.voice_engine.set_microphone(mic_index):
                QMessageBox.information(self, "Test", 
                    f"Microphone set to: {text}\n\n"
                    "Try speaking now to test. The system will listen for 5 seconds.")
                
                # Test listening
                result = self.voice_engine.listen_for_command(timeout=5)
                if result:
                    QMessageBox.information(self, "Test Result", 
                        f"✅ Microphone working!\n\nRecognized: '{result}'")
                else:
                    QMessageBox.warning(self, "Test Result", 
                        "⚠️ No speech detected or microphone not working properly.")
                
                # Restore original microphone if test failed and user wants to revert
                if not result and original_mic_index is not None:
                    self.voice_engine.set_microphone(original_mic_index)
            else:
                QMessageBox.critical(self, "Error", "Failed to set microphone.")
                
        except (ValueError, IndexError):
            QMessageBox.critical(self, "Error", "Invalid microphone selection.")
    
    def accept(self):
        """Apply the selected microphone"""
        current_item = self.mic_list.currentItem()
        if current_item:
            text = current_item.text()
            try:
                mic_index = int(text.split(']')[0].split('[')[1])
                if self.voice_engine.set_microphone(mic_index):
                    QMessageBox.information(self, "Success", "Microphone settings saved!")
                else:
                    QMessageBox.critical(self, "Error", "Failed to apply microphone settings.")
            except (ValueError, IndexError):
                QMessageBox.critical(self, "Error", "Invalid microphone selection.")
        
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS AI Assistant - Full Featured")
        self.setGeometry(100, 100, 1200, 800)
        
        # Initialize the main JARVIS system instead of individual components
        from jarvis import JARVIS
        self.jarvis = JARVIS()
        
        # Get references to the components for backward compatibility
        self.brain = self.jarvis.brain
        self.voice_engine = self.jarvis.voice_engine
        self.skills = self.jarvis.skills
        self.voice_chat_active = False
        self.voice_chat_worker = None
        
        # Worker thread for fast processing - updated to use JARVIS
        self.worker = JarvisWorker(self.jarvis, self.skills, self.voice_engine)
        self.worker.response_ready.connect(self.on_response_ready)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.status_update.connect(self.on_status_update)
        
        # Setup UI
        self.setup_ui()
        self.setup_menus()
        
        # Auto-refresh models
        self.refresh_models()
        
        if not self.brain.current_model:
            self.append_text("System", "No models available. Configure API keys in Settings.")
    
    def setup_ui(self):
        """Setup the main UI with tabs and advanced features"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        
        # Top control bar
        control_bar = self.create_control_bar()
        main_layout.addWidget(control_bar)
        
        # Create tab widget for different features
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Chat tab (main interface)
        self.setup_chat_tab()
        
        # Skills tab
        self.setup_skills_tab()
        
        # System tab
        self.setup_system_tab()
        
        # Status bar with enhanced information
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        # Create status bar widgets
        self.status_label = QLabel("Ready")
        self.statusBar.addWidget(self.status_label)
        
        # Add separator
        self.statusBar.addPermanentWidget(QLabel("|"))
        
        # Show JARVIS brain type
        brain_type = getattr(self.jarvis, 'brain_type', 'native')
        self.brain_status = QLabel(f"Brain: {brain_type}")
        self.statusBar.addPermanentWidget(self.brain_status)
        
        # Show available capabilities
        capabilities = []
        if hasattr(self.jarvis, 'screen_automation') and self.jarvis.screen_automation:
            capabilities.append("Vision")
        if hasattr(self.jarvis, 'automation_skill') and self.jarvis.automation_skill:
            capabilities.append("Automation")
        if hasattr(self.jarvis, 'app_control') and self.jarvis.app_control:
            capabilities.append("AppControl")
        
        if capabilities:
            self.capabilities_status = QLabel(f"Capabilities: {', '.join(capabilities)}")
            self.statusBar.addPermanentWidget(self.capabilities_status)
    
    def create_control_bar(self):
        """Create the top control bar"""
        control_frame = QWidget()
        layout = QHBoxLayout(control_frame)
        
        # Model selection
        layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self.on_model_change)
        layout.addWidget(self.model_combo, 1)
        
        # Quick action buttons
        self.btn_list = QPushButton("List Models")
        self.btn_list.clicked.connect(self.on_list)
        layout.addWidget(self.btn_list)
        
        self.btn_voice = QPushButton("Voice Mode")
        self.btn_voice.setCheckable(True)
        self.btn_voice.clicked.connect(self.toggle_voice)
        layout.addWidget(self.btn_voice)
        
        # Voice conversation button
        self.btn_voice_chat = QPushButton("🎤 Voice Chat")
        self.btn_voice_chat.setCheckable(True)
        self.btn_voice_chat.clicked.connect(self.toggle_voice_chat)
        self.btn_voice_chat.setStyleSheet("""
            QPushButton:checked { 
                background-color: #ff4444; 
                color: white; 
                font-weight: bold; 
            }
        """)
        layout.addWidget(self.btn_voice_chat)
        
        # Microphone settings button
        self.btn_mic_settings = QPushButton("🎙️ Mic")
        self.btn_mic_settings.clicked.connect(self.open_mic_settings)
        layout.addWidget(self.btn_mic_settings)
        
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self.on_clear)
        layout.addWidget(self.btn_clear)
        
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        layout.addWidget(self.btn_settings)
        
        # Quick automation buttons
        layout.addWidget(QLabel("|"))  # Separator
        
        self.btn_quick_screenshot = QPushButton("📸 Screenshot")
        self.btn_quick_screenshot.clicked.connect(self.take_screenshot_and_analyze)
        self.btn_quick_screenshot.setToolTip("Take screenshot and analyze")
        layout.addWidget(self.btn_quick_screenshot)
        
        self.btn_quick_apps = QPushButton("🚀 Apps")
        self.btn_quick_apps.clicked.connect(self.discover_applications)
        self.btn_quick_apps.setToolTip("Discover available applications")
        layout.addWidget(self.btn_quick_apps)
        
        return control_frame
    
    def setup_chat_tab(self):
        """Setup the main chat interface"""
        chat_widget = QWidget()
        layout = QVBoxLayout(chat_widget)
        
        # Chat display
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Consolas", 10))
        layout.addWidget(self.transcript)
        
        # Input area
        input_layout = QHBoxLayout()
        
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type your command... (Try: 'weather', 'take screenshot', 'open Word and create document', 'search python')")
        self.input.returnPressed.connect(self.on_send)
        input_layout.addWidget(self.input, 1)
        
        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self.on_send)
        input_layout.addWidget(self.btn_send)
        
        layout.addLayout(input_layout)
        
        # Add quick command buttons
        quick_layout = QHBoxLayout()
        quick_commands = [
            ("Weather", "weather today"),
            ("System Info", "system status"),
            ("Tell Joke", "tell me a joke"),
            ("Calculate", "calculate 2+2"),
            ("Search Web", "search python programming")
        ]
        
        for text, command in quick_commands:
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked, cmd=command: self.quick_command(cmd))
            quick_layout.addWidget(btn)
        
        layout.addLayout(quick_layout)
        
        self.tab_widget.addTab(chat_widget, "Chat")
    
    def setup_skills_tab(self):
        """Setup skills management tab"""
        skills_widget = QWidget()
        layout = QVBoxLayout(skills_widget)
        
        # Skills tree
        self.skills_tree = QTreeWidget()
        self.skills_tree.setHeaderLabels(["Skill", "Status", "Description"])
        layout.addWidget(self.skills_tree)
        
        # Populate skills tree
        self.update_skills_tree()
        
        # Skills control buttons
        skills_controls = QHBoxLayout()
        
        btn_refresh_skills = QPushButton("Refresh Skills")
        btn_refresh_skills.clicked.connect(self.update_skills_tree)
        skills_controls.addWidget(btn_refresh_skills)
        
        btn_test_skill = QPushButton("Test Selected")
        btn_test_skill.clicked.connect(self.test_selected_skill)
        skills_controls.addWidget(btn_test_skill)
        
        layout.addLayout(skills_controls)
        
        self.tab_widget.addTab(skills_widget, "Skills")
    
    def setup_system_tab(self):
        """Setup system information tab"""
        system_widget = QWidget()
        layout = QVBoxLayout(system_widget)
        
        # System info display
        self.system_info = QTextEdit()
        self.system_info.setReadOnly(True)
        self.system_info.setFont(QFont("Courier", 9))
        layout.addWidget(self.system_info)
        
        # System controls
        system_controls = QHBoxLayout()
        
        btn_refresh_system = QPushButton("Refresh System Info")
        btn_refresh_system.clicked.connect(self.refresh_system_info)
        system_controls.addWidget(btn_refresh_system)
        
        btn_memory_info = QPushButton("Memory Details")
        btn_memory_info.clicked.connect(self.show_memory_info)
        system_controls.addWidget(btn_memory_info)
        
        btn_disk_info = QPushButton("Disk Usage")
        btn_disk_info.clicked.connect(self.show_disk_info)
        system_controls.addWidget(btn_disk_info)
        
        layout.addLayout(system_controls)
        
        self.tab_widget.addTab(system_widget, "System")
        
        # Automation Tab
        automation_widget = self.create_automation_tab()
        self.tab_widget.addTab(automation_widget, "Automation")
        
        # Visual Tasks Tab
        visual_tasks_widget = self.create_visual_tasks_tab()
        self.tab_widget.addTab(visual_tasks_widget, "Visual Tasks")
        
        # Auto-refresh system info
        self.refresh_system_info()
    
    def setup_menus(self):
        """Setup application menus"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        export_action = QAction("Export Chat", self)
        export_action.triggered.connect(self.export_chat)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        voice_test_action = QAction("Test Voice", self)
        voice_test_action.triggered.connect(self.test_voice)
        tools_menu.addAction(voice_test_action)
        
        skills_test_action = QAction("Test All Skills", self)
        skills_test_action.triggered.connect(self.test_all_skills)
        tools_menu.addAction(skills_test_action)
        
        tools_menu.addSeparator()
        
        screenshot_action = QAction("Quick Screenshot Analysis", self)
        screenshot_action.triggered.connect(self.take_screenshot_and_analyze)
        tools_menu.addAction(screenshot_action)
        
        # Automation menu
        automation_menu = menubar.addMenu("Automation")
        
        visual_task_action = QAction("Execute Visual Task...", self)
        visual_task_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(3))  # Switch to automation tab
        automation_menu.addAction(visual_task_action)
        
        complex_task_action = QAction("Execute Complex Task...", self)
        complex_task_action.triggered.connect(lambda: self.tab_widget.setCurrentIndex(4))  # Switch to visual tasks tab
        automation_menu.addAction(complex_task_action)
        
        automation_menu.addSeparator()
        
        discover_apps_action = QAction("Discover Applications", self)
        discover_apps_action.triggered.connect(self.discover_applications)
        automation_menu.addAction(discover_apps_action)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def refresh_models(self):
        """Refresh available models"""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for name in self.brain.available_models.keys():
            self.model_combo.addItem(name)
        if self.brain.current_model:
            idx = self.model_combo.findText(self.brain.current_model)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)
    
    def on_model_change(self, name: str):
        if not name:
            return
        msg = self.brain.switch_model(name)
        self.append_text("System", msg)
    
    def on_send(self):
        text = self.input.text().strip()
        if not text:
            return
        
        self.append_text("You", text)
        self.input.clear()
        
        # Process in worker thread for speed - restart if needed
        if self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(1000)  # Wait up to 1 second
        
        self.worker = JarvisWorker(self.jarvis, self.skills, self.voice_engine)
        self.worker.response_ready.connect(self.on_response_ready)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.status_update.connect(self.on_status_update)
        
        self.worker.set_command(text, voice_enabled=self.btn_voice.isChecked())
        self.worker.start()
    
    def quick_command(self, command):
        """Execute a quick command"""
        self.input.setText(command)
        self.on_send()
    
    def on_response_ready(self, response):
        """Handle response from worker thread"""
        self.append_text("Assistant", response)
    
    def on_error(self, error):
        """Handle error from worker thread"""
        self.append_text("Error", error)
    
    def on_status_update(self, status):
        """Update status bar"""
        self.statusBar.showMessage(status)
    
    def toggle_voice(self):
        """Toggle voice mode"""
        if self.btn_voice.isChecked():
            self.append_text("System", "Voice mode enabled - responses will be spoken")
            self.btn_voice.setText("Voice Mode: ON")
        else:
            self.append_text("System", "Voice mode disabled")
            self.btn_voice.setText("Voice Mode: OFF")
    
    def toggle_voice_chat(self):
        """Toggle voice conversation mode"""
        if self.btn_voice_chat.isChecked():
            # Start voice chat mode
            self.voice_chat_active = True
            self.btn_voice_chat.setText("🎤 Voice Chat: ON")
            
            # Disable text input while in voice chat mode
            self.input.setEnabled(False)
            self.btn_send.setEnabled(False)
            
            # Start voice chat worker
            self.voice_chat_worker = VoiceChatWorker(self.brain, self.voice_engine, self.skills)
            self.voice_chat_worker.message_received.connect(lambda msg: self.append_text("You", msg.replace("You said: ", "")))
            self.voice_chat_worker.response_ready.connect(lambda msg: self.append_text("Assistant", msg))
            self.voice_chat_worker.status_update.connect(self.on_status_update)
            self.voice_chat_worker.error_occurred.connect(self.on_error)
            
            self.append_text("System", "Voice chat started! Start speaking... (Click button again to stop)")
            self.voice_chat_worker.start()
            
        else:
            # Stop voice chat mode
            self.voice_chat_active = False
            self.btn_voice_chat.setText("🎤 Voice Chat: OFF")
            
            # Re-enable text input
            self.input.setEnabled(True)
            self.btn_send.setEnabled(True)
            
            # Stop voice chat worker
            if self.voice_chat_worker:
                self.voice_chat_worker.stop()
                self.voice_chat_worker.wait(3000)  # Wait up to 3 seconds
                self.voice_chat_worker = None
            
            self.append_text("System", "Voice chat stopped.")
    
    def open_mic_settings(self):
        """Open microphone settings dialog"""
        dialog = MicrophoneSettingsDialog(self.voice_engine, self)
        dialog.exec()
    
    def on_clear(self):
        """Clear chat history"""
        self.brain.clear_history()
        self.transcript.clear()
        self.append_text("System", "History cleared.")
    
    def on_list(self):
        """List available models"""
        self.append_text("System", self.brain.list_available_models())
    
    def open_settings(self):
        """Open settings dialog"""
        dlg = SettingsDialog(self)
        if dlg.exec():
            # Reload configuration
            from config import load_env
            load_env()
            self.brain._initialize_providers()
            self.brain._set_default_model()
            self.refresh_models()
            self.append_text("System", "Settings saved and models refreshed.")
    
    def update_skills_tree(self):
        """Update the skills tree widget"""
        self.skills_tree.clear()
        
        for skill_name, skill_obj in self.skills.items():
            item = QTreeWidgetItem([skill_name, "Active", f"{skill_obj.__class__.__name__}"])
            self.skills_tree.addTopLevelItem(item)
    
    def test_selected_skill(self):
        """Test the selected skill"""
        current = self.skills_tree.currentItem()
        if current:
            skill_name = current.text(0)
            if skill_name in self.skills:
                try:
                    if skill_name == 'weather':
                        result = self.skills[skill_name].get_weather("test weather")
                    elif skill_name == 'utility':
                        result = self.skills[skill_name].tell_joke()
                    elif skill_name == 'system_monitor':
                        result = self.skills[skill_name].get_system_info()
                    else:
                        result = f"{skill_name} skill is available"
                    
                    self.append_text("Skill Test", f"{skill_name}: {result}")
                except Exception as e:
                    self.append_text("Skill Test", f"{skill_name} error: {e}")
    
    def refresh_system_info(self):
        """Refresh system information"""
        try:
            if 'system_monitor' in self.skills:
                info = self.skills['system_monitor'].get_system_info()
                self.system_info.setText(info)
            else:
                import psutil
                info = f"""
System Information:
CPU Usage: {psutil.cpu_percent()}%
Memory Usage: {psutil.virtual_memory().percent}%
Disk Usage: {psutil.disk_usage('/').percent}%
"""
                self.system_info.setText(info)
        except Exception as e:
            self.system_info.setText(f"Error getting system info: {e}")
    
    def show_memory_info(self):
        """Show detailed memory information"""
        try:
            import psutil
            mem = psutil.virtual_memory()
            info = f"""
Memory Information:
Total: {mem.total / (1024**3):.2f} GB
Available: {mem.available / (1024**3):.2f} GB
Used: {mem.used / (1024**3):.2f} GB
Percentage: {mem.percent}%
"""
            QMessageBox.information(self, "Memory Information", info)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not get memory info: {e}")
    
    def show_disk_info(self):
        """Show disk usage information"""
        try:
            import psutil
            disks = psutil.disk_partitions()
            info = "Disk Usage:\n\n"
            for disk in disks:
                try:
                    usage = psutil.disk_usage(disk.mountpoint)
                    info += f"{disk.device}: {usage.percent:.1f}% used\n"
                except:
                    info += f"{disk.device}: Unable to read\n"
            QMessageBox.information(self, "Disk Information", info)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not get disk info: {e}")
    
    def test_voice(self):
        """Test voice functionality"""
        try:
            self.voice_engine.speak("Voice test successful. JARVIS is ready.")
            self.append_text("System", "Voice test completed")
        except Exception as e:
            self.append_text("System", f"Voice test failed: {e}")
    
    def test_all_skills(self):
        """Test all available skills"""
        self.append_text("System", "Testing all skills...")
        for skill_name in self.skills:
            self.skills_tree.setCurrentItem(
                self.skills_tree.topLevelItem(
                    list(self.skills.keys()).index(skill_name)
                )
            )
            self.test_selected_skill()
    
    def export_chat(self):
        """Export chat history"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Chat", "jarvis_chat.txt", "Text Files (*.txt)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.transcript.toPlainText())
                QMessageBox.information(self, "Export", "Chat exported successfully!")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Export failed: {e}")
    
    def show_about(self):
        """Show about dialog"""
        about_text = """
JARVIS AI Assistant - Full Featured GUI

Version: 2.0
Features:
- Multi-model AI support
- Voice interaction
- Advanced skills system
- System monitoring
- File management
- Web search capabilities
- Automation tools

Built with PySide6 and Python
        """
        QMessageBox.about(self, "About JARVIS", about_text)
    
    def append_text(self, speaker: str, text: str):
        """Append text to the chat display"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_text = f"[{timestamp}] {speaker}: {text}"
        
        self.transcript.append(formatted_text)
        self.transcript.ensureCursorVisible()
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Stop voice chat if active
        if self.voice_chat_active and self.voice_chat_worker:
            self.voice_chat_worker.stop()
            self.voice_chat_worker.wait(1000)
        
        # Stop regular worker if running
        if self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(1000)
        
        event.accept()

    def create_automation_tab(self):
        """Create the automation control tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Automation controls
        automation_group = QWidget()
        automation_layout = QVBoxLayout(automation_group)
        
        # Screen automation section
        screen_section = QLabel("Screen Automation & AI Vision")
        screen_section.setFont(QFont("Arial", 12, QFont.Bold))
        automation_layout.addWidget(screen_section)
        
        # Screenshot and analysis
        screenshot_layout = QHBoxLayout()
        btn_screenshot = QPushButton("Take Screenshot")
        btn_screenshot.clicked.connect(self.take_screenshot_and_analyze)
        screenshot_layout.addWidget(btn_screenshot)
        
        btn_analyze_screen = QPushButton("Analyze Current Screen")
        btn_analyze_screen.clicked.connect(self.analyze_current_screen)
        screenshot_layout.addWidget(btn_analyze_screen)
        
        automation_layout.addLayout(screenshot_layout)
        
        # Visual task input
        task_input_layout = QHBoxLayout()
        self.visual_task_input = QLineEdit()
        self.visual_task_input.setPlaceholderText("Describe what you want me to do on screen (e.g., 'click the save button')")
        task_input_layout.addWidget(self.visual_task_input)
        
        btn_execute_visual = QPushButton("Execute Visual Task")
        btn_execute_visual.clicked.connect(self.execute_visual_task)
        task_input_layout.addWidget(btn_execute_visual)
        
        automation_layout.addLayout(task_input_layout)
        
        # App control section
        app_section = QLabel("Application Control")
        app_section.setFont(QFont("Arial", 12, QFont.Bold))
        automation_layout.addWidget(app_section)
        
        app_control_layout = QHBoxLayout()
        btn_discover_apps = QPushButton("Discover Apps")
        btn_discover_apps.clicked.connect(self.discover_applications)
        app_control_layout.addWidget(btn_discover_apps)
        
        btn_launch_app = QPushButton("Launch Application")
        btn_launch_app.clicked.connect(self.launch_application_dialog)
        app_control_layout.addWidget(btn_launch_app)
        
        automation_layout.addLayout(app_control_layout)
        
        layout.addWidget(automation_group)
        
        # Automation output/log area
        self.automation_log = QTextEdit()
        self.automation_log.setPlaceholderText("Automation activities and results will appear here...")
        self.automation_log.setMaximumHeight(200)
        layout.addWidget(self.automation_log)
        
        return widget

    def create_visual_tasks_tab(self):
        """Create the visual tasks and AI orchestration tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Task orchestration controls
        task_group = QWidget()
        task_layout = QVBoxLayout(task_group)
        
        # Multi-step task section
        multistep_section = QLabel("Multi-Step Task Orchestration")
        multistep_section.setFont(QFont("Arial", 12, QFont.Bold))
        task_layout.addWidget(multistep_section)
        
        # Complex task input
        complex_task_layout = QVBoxLayout()
        self.complex_task_input = QTextEdit()
        self.complex_task_input.setPlaceholderText("Describe a complex task that requires multiple steps (e.g., 'open Word, create a document with today's date, save it as daily_report.docx')")
        self.complex_task_input.setMaximumHeight(100)
        complex_task_layout.addWidget(self.complex_task_input)
        
        complex_task_buttons = QHBoxLayout()
        btn_execute_complex = QPushButton("Execute Complex Task")
        btn_execute_complex.clicked.connect(self.execute_complex_task)
        complex_task_buttons.addWidget(btn_execute_complex)
        
        btn_plan_task = QPushButton("Plan Task Steps")
        btn_plan_task.clicked.connect(self.plan_task_steps)
        complex_task_buttons.addWidget(btn_plan_task)
        
        complex_task_layout.addLayout(complex_task_buttons)
        task_layout.addLayout(complex_task_layout)
        
        # Task queue and monitoring
        queue_section = QLabel("Task Queue & Monitoring")
        queue_section.setFont(QFont("Arial", 12, QFont.Bold))
        task_layout.addWidget(queue_section)
        
        # Task queue list
        self.task_queue_list = QListWidget()
        self.task_queue_list.setMaximumHeight(150)
        task_layout.addWidget(self.task_queue_list)
        
        queue_controls = QHBoxLayout()
        btn_pause_tasks = QPushButton("Pause Queue")
        btn_pause_tasks.clicked.connect(self.pause_task_queue)
        queue_controls.addWidget(btn_pause_tasks)
        
        btn_resume_tasks = QPushButton("Resume Queue")
        btn_resume_tasks.clicked.connect(self.resume_task_queue)
        queue_controls.addWidget(btn_resume_tasks)
        
        btn_clear_queue = QPushButton("Clear Queue")
        btn_clear_queue.clicked.connect(self.clear_task_queue)
        queue_controls.addWidget(btn_clear_queue)
        
        task_layout.addLayout(queue_controls)
        
        layout.addWidget(task_group)
        
        # Task execution log
        self.task_execution_log = QTextEdit()
        self.task_execution_log.setPlaceholderText("Task execution details and progress will appear here...")
        layout.addWidget(self.task_execution_log)
        
        return widget

    # Automation and Visual Task Methods
    def take_screenshot_and_analyze(self):
        """Take screenshot and analyze with AI"""
        try:
            if hasattr(self.jarvis, 'screen_automation') and self.jarvis.screen_automation:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Taking screenshot for analysis...")
                
                # Use JARVIS screen automation
                response = self.jarvis.process_command("take a screenshot and tell me what you see")
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Analysis: {response}")
            else:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Screen automation not available")
        except Exception as e:
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}")

    def analyze_current_screen(self):
        """Analyze current screen without taking new screenshot"""
        try:
            if hasattr(self.jarvis, 'screen_automation') and self.jarvis.screen_automation:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Analyzing current screen...")
                
                response = self.jarvis.process_command("analyze the current screen and describe what you see")
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Analysis: {response}")
            else:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Screen automation not available")
        except Exception as e:
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}")

    def execute_visual_task(self):
        """Execute a visual task based on user input"""
        task_description = self.visual_task_input.text().strip()
        if not task_description:
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Please enter a task description")
            return
        
        try:
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Executing visual task: {task_description}")
            
            # Process the visual task through JARVIS
            response = self.jarvis.process_command(task_description)
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task result: {response}")
            self.visual_task_input.clear()
        except Exception as e:
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task execution error: {str(e)}")

    def discover_applications(self):
        """Discover available applications"""
        try:
            if hasattr(self.jarvis, 'app_control') and self.jarvis.app_control:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Discovering applications...")
                
                response = self.jarvis.process_command("discover available applications")
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {response}")
            else:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Application control not available")
        except Exception as e:
            self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}")

    def launch_application_dialog(self):
        """Show dialog to launch an application"""
        from PySide6.QtWidgets import QInputDialog
        
        app_name, ok = QInputDialog.getText(self, 'Launch Application', 'Enter application name to launch:')
        if ok and app_name:
            try:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Launching {app_name}...")
                
                response = self.jarvis.process_command(f"launch {app_name}")
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {response}")
            except Exception as e:
                self.automation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Launch error: {str(e)}")

    def execute_complex_task(self):
        """Execute a complex multi-step task"""
        task_description = self.complex_task_input.toPlainText().strip()
        if not task_description:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Please enter a task description")
            return
        
        try:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting complex task: {task_description}")
            
            # Add to task queue
            self.task_queue_list.addItem(f"Complex Task: {task_description[:50]}...")
            
            # Process through JARVIS - it will handle the orchestration
            response = self.jarvis.process_command(task_description)
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task completed: {response}")
            
            self.complex_task_input.clear()
        except Exception as e:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task execution error: {str(e)}")

    def plan_task_steps(self):
        """Plan the steps for a complex task without executing"""
        task_description = self.complex_task_input.toPlainText().strip()
        if not task_description:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Please enter a task description")
            return
        
        try:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Planning steps for: {task_description}")
            
            # Ask JARVIS to plan without executing
            planning_prompt = f"Plan the steps needed to complete this task, but don't execute them yet: {task_description}"
            response = self.jarvis.process_command(planning_prompt)
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Execution plan: {response}")
        except Exception as e:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Planning error: {str(e)}")

    def pause_task_queue(self):
        """Pause the task execution queue"""
        try:
            if hasattr(self.jarvis, 'task_scheduler') and self.jarvis.task_scheduler:
                self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Pausing task queue...")
                # Implementation depends on task scheduler capabilities
            else:
                self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task scheduler not available")
        except Exception as e:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}")

    def resume_task_queue(self):
        """Resume the task execution queue"""
        try:
            if hasattr(self.jarvis, 'task_scheduler') and self.jarvis.task_scheduler:
                self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Resuming task queue...")
                # Implementation depends on task scheduler capabilities
            else:
                self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task scheduler not available")
        except Exception as e:
            self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {str(e)}")

    def clear_task_queue(self):
        """Clear all tasks from the queue"""
        self.task_queue_list.clear()
        self.task_execution_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] Task queue cleared")


def main():
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("JARVIS AI Assistant")
    app.setApplicationVersion("2.0")
    
    win = MainWindow()
    win.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
