"""Base class for intent handlers.

A handler owns one domain end to end: it answers the requests the decision
engine routes to its intents (``handle``) *and* registers the matching tools
the language model may call (``register_tools``). Keeping both in one place
means a capability is defined once, whether it is reached by a direct command,
a step of a plan, live voice, or a model's tool call.
"""
from typing import Optional, Set

from core.logging_setup import get_logger


class Handler:
    intents: Set[str] = set()

    def __init__(self, app):
        self.app = app               # the JARVIS instance: skills, confirm(), notify(), _ask_to_confirm()
        self.log = get_logger(f"jarvis.handlers.{type(self).__name__}")

    def handle(self, text: str, intent: str) -> Optional[str]:
        """Return a reply, or None to let the language model take over."""
        raise NotImplementedError

    def register_tools(self, tools) -> None:
        """Add this domain's tools to the shared ToolRegistry (optional)."""
