from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QLabel
from config import save_api_keys, Config
import os

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS Settings")
        self.setModal(True)
        self.resize(400, 300)

        self.openrouter_edit = QLineEdit(self)
        self.openrouter_edit.setPlaceholderText("OpenRouter API Key")
        self.openrouter_edit.setText(getattr(Config, "OPENROUTER_API_KEY", ""))
        self.openrouter_edit.setEchoMode(QLineEdit.Password)

        self.gemini_edit = QLineEdit(self)
        self.gemini_edit.setPlaceholderText("Gemini API Key")
        self.gemini_edit.setText(getattr(Config, "GEMINI_API_KEY", ""))
        self.gemini_edit.setEchoMode(QLineEdit.Password)
        
        # Add location preference field
        self.location_edit = QLineEdit(self)
        self.location_edit.setPlaceholderText("Your City (e.g., Chennai, India)")
        self.location_edit.setText(os.getenv("JARVIS_LOCATION", ""))

        form = QFormLayout()
        form.addRow("OpenRouter API Key:", self.openrouter_edit)
        form.addRow("Gemini API Key:", self.gemini_edit)
        form.addRow(QLabel())  # Spacer
        form.addRow("Preferred Location:", self.location_edit)
        form.addRow(QLabel("(For weather - leave empty for auto-detection)"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addWidget(buttons)

        self.setLayout(form)

    def get_values(self):
        return self.openrouter_edit.text().strip(), self.gemini_edit.text().strip(), self.location_edit.text().strip()

    def accept(self):
        openrouter, gemini, location = self.get_values()
        save_api_keys(openrouter, gemini)
        
        # Save location preference
        if location:
            os.environ["JARVIS_LOCATION"] = location
            # Also save to the .env file
            self._save_location_to_env(location)
        
        super().accept()
    
    def _save_location_to_env(self, location):
        """Save location preference to .env file"""
        try:
            from config import APPDATA_DIR, ENV_PATH
            
            existing = ""
            if ENV_PATH.exists():
                existing = ENV_PATH.read_text(encoding="utf-8")
            
            # Remove existing JARVIS_LOCATION line
            lines = existing.splitlines(True)
            lines = [ln for ln in lines if not ln.startswith("JARVIS_LOCATION=")]
            
            # Add new location line
            if location:
                lines.append(f"JARVIS_LOCATION={location}\n")
            
            ENV_PATH.write_text("".join(lines), encoding="utf-8")
        except Exception:
            pass  # Ignore errors silently
