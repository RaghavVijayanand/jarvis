"""Natural-language requests that need the AI to write and run a script inside
another app — "make a model of a chair in Blender". Always confirms first: this
runs generated code, which is a different risk class from clicking a button."""
import re

from core.tools import params
from handlers.base import Handler

_BLENDER = re.compile(
    r"\b(?:make|model|create|build|design|generate|render)\b.*\bin\s+blender\b|"
    r"\bblender\b.*\b(?:make|model|create|build|design|generate)\b.*\b(?:model|mesh|object|scene)\b|"
    r"^(?:please\s+)?(?:open\s+)?blender\s+and\s+(?:make|model|create|build)\b", re.I)


class AppScriptHandler(Handler):
    intents = {"APPSCRIPT"}

    def handle(self, text, intent):
        app = self.app
        scripting = getattr(app, "app_scripting", None)
        if scripting is None:
            return "App scripting isn't available."
        if _BLENDER.search(text):
            description = text.strip()
            return app._ask_to_confirm(
                f"Let JARVIS ask the AI to write a Blender script for \"{description}\" and run it in "
                f"Blender? Review what it built before saving anything important.",
                lambda: scripting.blender_run(description), "run_blender_script")
        return None

    def register_tools(self, t):
        scripting = getattr(self.app, "app_scripting", None)
        if scripting is None:
            return
        t.add("run_blender_script", "Have the AI write a Python (bpy) script from a description and run "
              "it in Blender — for modeling, scenes, or anything Blender's scripting API can do. Opens "
              "Blender's normal window unless background is set.",
              lambda description, save_as="", background=False: scripting.blender_run(
                  description, save_as=save_as, background=bool(background)),
              params(["description"],
                    description=("string", "What to model/build, in plain language"),
                    save_as=("string", "Optional file path to save the .blend to afterward"),
                    background=("boolean", "Run headless with no visible window (good for pure exports)")),
              confirm=True,
              confirm_text="Let JARVIS ask the AI to write a Blender script for \"{description}\" and run it?")
