#!/usr/bin/env python3
"""
Simple test script to interact with JARVIS via stdin
"""
import subprocess
import time
import sys

def send_command_to_jarvis(command):
    """Send a command to JARVIS and capture response"""
    try:
        # Start JARVIS process
        process = subprocess.Popen(
            [sys.executable, "jarvis.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd="d:\\jarvis"
        )
        
        # Send command
        stdout, stderr = process.communicate(input=f"{command}\nexit\n", timeout=30)
        
        return stdout, stderr
    except subprocess.TimeoutExpired:
        process.kill()
        return "Timeout", "Process timed out"
    except Exception as e:
        return f"Error: {e}", ""

if __name__ == "__main__":
    commands = [
        "who are u",
        "create a file in this folder"
    ]
    
    for cmd in commands:
        print(f"\n=== Testing: {cmd} ===")
        stdout, stderr = send_command_to_jarvis(cmd)
        print("STDOUT:", stdout)
        if stderr:
            print("STDERR:", stderr)
        print("-" * 50)
