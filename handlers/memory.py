"""What JARVIS remembers about the user."""
import re

from core.tools import params
from handlers.base import Handler


class MemoryHandler(Handler):
    intents = {"MEMORY"}

    def handle(self, text, intent):
        app = self.app
        if getattr(app, "brain", None) is None:
            return "Memory is unavailable because the AI brain failed to start."
        memory = app.brain.memory
        low = text.lower().strip().rstrip(".!?")
        if re.search(r"what do you (?:know|remember) about me|show (?:me )?(?:my )?memor|who am i", low):
            return memory.summary()
        if re.search(r"what(?:'s|s| is) my name", low):
            name = memory.memory.get("user_name")
            return f"Your name is {name}." if name else "You haven't told me your name yet."
        if re.search(r"^forget (?:everything|all(?: about me)?)$", low):
            return app._ask_to_confirm("Forget everything I know about you?",
                                       lambda: (memory.forget_all(), "Done — my memory of you is wiped.")[1],
                                       "forget_all")
        if re.fullmatch(r"forget (?:it|that|about it|this)", low):
            # Colloquial "never mind" — must not delete every fact containing "it"/"that".
            return "Okay, never mind."
        m = re.match(r"^forget (?:that |about |fact )?(.+)$", low)
        if m:
            removed = memory.forget(m.group(1))
            return (f"Forgotten ({removed} item{'s' if removed != 1 else ''})." if removed
                    else "I don't have anything matching that.")
        m = re.match(r"^(?:please\s+)?(?:remember|note|keep in mind|don'?t forget)(?: that)?\s+(.+)$", text.strip(), re.I) \
            or re.match(r"^((?:hi,?\s+|hello,?\s+)?my name is\s+.+)$", text.strip().rstrip(".!"), re.I)
        if m:
            fact = re.sub(r"^(?:hi|hello),?\s+", "", m.group(1), flags=re.I)
            name = re.match(r"my name is ([^\W\d_][^\W\d_'’-]*(?:[-'’][^\W\d_]+)*(?: [^\W\d_][^\W\d_'’-]*)?)", fact, re.I)
            if name:
                # Keep the user's own capitalisation ("McDonald"); only fix all-lowercase input.
                spoken = " ".join(w if w != w.lower() else w[:1].upper() + w[1:] for w in name.group(1).split())
                memory.set_user_name(spoken)
                return f"Noted — I'll call you {spoken}."
            loc = re.match(r"i live in (.+)", fact, re.I)
            if loc:
                memory.set_preference("location", loc.group(1).strip())
                return f"Noted — you live in {loc.group(1).strip()}."
            return "Noted. I'll remember that." if memory.remember_fact(fact) else "I already know that."
        return None

    def register_tools(self, t):
        brain = getattr(self.app, "brain", None)
        if brain is None:
            return
        t.add("remember_fact", "Store a lasting fact about the user.",
              lambda fact: "Noted." if brain.memory.remember_fact(fact) else "Already known.",
              params(["fact"], fact=("string", "The fact")))
