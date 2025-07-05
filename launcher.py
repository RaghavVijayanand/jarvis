#!/usr/bin/env python3
"""
JARVIS Launcher
Simple GUI launcher for JARVIS AI Assistant
"""

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

import subprocess
import sys
import threading
from pathlib import Path

class JARVISLauncher:
    def __init__(self):
        if not GUI_AVAILABLE:
            self.run_console_launcher()
            return
            
        self.root = tk.Tk()
        self.root.title("JARVIS AI Assistant Launcher")
        self.root.geometry("400x300")
        self.root.resizable(False, False)
        
        # Center the window
        self.root.eval('tk::PlaceWindow . center')
        
        self.setup_gui()
        
    def setup_gui(self):
        """Setup the GUI interface"""
        # Title
        title_label = tk.Label(
            self.root, 
            text="JARVIS AI Assistant",
            font=("Arial", 16, "bold"),
            fg="blue"
        )
        title_label.pack(pady=20)
        
        subtitle_label = tk.Label(
            self.root,
            text="Just A Rather Very Intelligent System",
            font=("Arial", 10, "italic"),
            fg="gray"
        )
        subtitle_label.pack(pady=5)
        
        # Mode selection
        mode_frame = tk.Frame(self.root)
        mode_frame.pack(pady=20)
        
        tk.Label(mode_frame, text="Select Mode:", font=("Arial", 12)).pack()
        
        self.mode_var = tk.StringVar(value="voice")
        
        voice_radio = tk.Radiobutton(
            mode_frame,
            text="Voice Mode (with microphone)",
            variable=self.mode_var,
            value="voice",
            font=("Arial", 10)
        )
        voice_radio.pack(anchor="w", pady=5)
        
        text_radio = tk.Radiobutton(
            mode_frame,
            text="Text Mode (keyboard only)",
            variable=self.mode_var,
            value="text",
            font=("Arial", 10)
        )
        text_radio.pack(anchor="w", pady=5)
        
        # Buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=20)
        
        start_button = tk.Button(
            button_frame,
            text="Start JARVIS",
            command=self.start_jarvis,
            bg="green",
            fg="white",
            font=("Arial", 12, "bold"),
            width=15,
            height=2
        )
        start_button.pack(side="left", padx=10)
        
        test_button = tk.Button(
            button_frame,
            text="Run Tests",
            command=self.run_tests,
            bg="orange",
            fg="white",
            font=("Arial", 12),
            width=15,
            height=2
        )
        test_button.pack(side="left", padx=10)
        
        # Status
        self.status_var = tk.StringVar(value="Ready to launch JARVIS")
        status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("Arial", 10),
            fg="green"
        )
        status_label.pack(pady=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(pady=10, fill="x", padx=20)
        
    def start_jarvis(self):
        """Start JARVIS in selected mode"""
        mode = self.mode_var.get()
        
        self.status_var.set(f"Starting JARVIS in {mode} mode...")
        self.progress.start()
        
        def run_jarvis():
            try:
                # Check if jarvis.py exists
                jarvis_script = Path(__file__).parent / "jarvis.py"
                if not jarvis_script.exists():
                    self.show_error("JARVIS script not found. Please ensure jarvis.py is in the same directory.")
                    return
                
                # Run JARVIS
                cmd = [sys.executable, str(jarvis_script)]
                if mode == "text":
                    cmd.append("text")
                
                process = subprocess.Popen(cmd, cwd=Path(__file__).parent)
                
                # Wait a moment then update status
                import time
                time.sleep(2)
                
                self.root.after(0, lambda: self.status_var.set(f"JARVIS running in {mode} mode"))
                self.root.after(0, self.progress.stop)
                
            except Exception as e:
                self.root.after(0, lambda: self.show_error(f"Failed to start JARVIS: {e}"))
                self.root.after(0, self.progress.stop)
        
        # Run in separate thread
        thread = threading.Thread(target=run_jarvis, daemon=True)
        thread.start()
    
    def run_tests(self):
        """Run JARVIS tests"""
        self.status_var.set("Running tests...")
        self.progress.start()
        
        def run_test_script():
            try:
                test_script = Path(__file__).parent / "test.py"
                if not test_script.exists():
                    self.show_error("Test script not found.")
                    return
                
                # Run tests in new window
                subprocess.Popen([sys.executable, str(test_script)], cwd=Path(__file__).parent)
                
                import time
                time.sleep(1)
                
                self.root.after(0, lambda: self.status_var.set("Tests started in new window"))
                self.root.after(0, self.progress.stop)
                
            except Exception as e:
                self.root.after(0, lambda: self.show_error(f"Failed to run tests: {e}"))
                self.root.after(0, self.progress.stop)
        
        thread = threading.Thread(target=run_test_script, daemon=True)
        thread.start()
    
    def show_error(self, message):
        """Show error message"""
        self.status_var.set("Error occurred")
        self.progress.stop()
        messagebox.showerror("Error", message)
    
    def run_console_launcher(self):
        """Run console-based launcher if GUI not available"""
        print("🤖 JARVIS AI Assistant Launcher")
        print("=" * 40)
        print()
        print("GUI not available. Using console launcher.")
        print()
        print("Choose an option:")
        print("[1] Start JARVIS (Voice Mode)")
        print("[2] Start JARVIS (Text Mode)")
        print("[3] Run Tests")
        print("[4] Exit")
        print()
        
        while True:
            try:
                choice = input("Enter your choice (1-4): ").strip()
                
                if choice == "1":
                    print("Starting JARVIS in voice mode...")
                    subprocess.run([sys.executable, "jarvis.py", "voice"])
                    break
                elif choice == "2":
                    print("Starting JARVIS in text mode...")
                    subprocess.run([sys.executable, "jarvis.py", "text"])
                    break
                elif choice == "3":
                    print("Running tests...")
                    subprocess.run([sys.executable, "test.py"])
                    break
                elif choice == "4":
                    print("Goodbye!")
                    break
                else:
                    print("Invalid choice. Please enter 1-4.")
                    
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
    
    def run(self):
        """Run the launcher"""
        if GUI_AVAILABLE:
            self.root.mainloop()

def main():
    """Main function"""
    launcher = JARVISLauncher()
    launcher.run()

if __name__ == "__main__":
    main()
