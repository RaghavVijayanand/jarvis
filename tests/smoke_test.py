#!/usr/bin/env python3
"""
Quick smoke test for JARVIS core features (non-destructive).
Runs a series of text commands programmatically with voice off and prints concise results.
"""

import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jarvis


def run():
    j = jarvis.JARVIS()
    cmds = [
        # Utilities
        'tell me a joke',
        'flip a coin',
        'roll dice',
        'what time is it',
        'what date is it',
        'calculate 2+3*4',
        'random number between 10 and 12',
        'word count hello world from jarvis',
        # System
        'cpu usage',
        'memory usage',
        'disk usage',
        # Context/history
        'context on',
        'context off',
        'clear history',
        # Files
        'create a file named smoke.txt on this folder and write about testing',
        'read file smoke.txt',
        'rename smoke.txt to smoke2.txt',
        'delete file smoke2.txt',
    ]
    for i, c in enumerate(cmds, 1):
        print(f"\n=== CMD {i}/{len(cmds)}: {c}")
        try:
            j.process_command(c, use_voice=False)
        except Exception as e:
            print(f"ERROR executing '{c}': {e}")
    print("\nSMOKE_DONE")


if __name__ == '__main__':
    run()
