Cleanup summary for JARVIS repo (auto-generated)

Removed:
- __pycache__/ directories (compiled caches)
- *.pyc files
- Added .gitignore to keep caches and envs out of source control
- Kept logs/, cache/, data/, memory/ directories but they are empty; they remain ignored by git

Safety fixes:
- Config: removed hardcoded API key and now reads from environment; added VOICE_SETTINGS.enabled flag
- VoiceEngine: guarded voice settings access; fixed indentation bugs
- AdvancedAIBrain: optional Gemini import, adjusted memory load, and Ollama config guards

Validation:
- Repo builds without syntax errors in key modules (config.py, voice_engine.py, advanced_brain.py, brain.py)
- Next step: run tests via `python test.py` or `python test_jarvis.py`

