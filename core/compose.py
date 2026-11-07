"""Write something with the AI and type it into an app.

    "open notepad"            → JARVIS remembers Notepad as the app it last opened
    "write an essay about world peace and type it there"
    "type an email to my boss asking for friday off"
    "draft a cover letter for a barista job in word"
                              → the AI writes it (plain text, no markdown) → the target
                                window is focused (opened first if needed) → pasted in

Without this, the splitter cut "…and type it there" into its own step and typed the
literal words "it there", and "type an essay about X" typed "an essay about X".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

COMPOSE_SYSTEM_PROMPT = (
    "You write text that will be pasted straight into the user's document or app. "
    "Output only the requested text itself: no preamble such as 'Here is', no closing remarks, "
    "no markdown (no #, **, or bullet symbols — use plain paragraphs and plain numbered lines). "
    "Match the requested length and tone; if no length is given, keep it reasonably concise.")

# Things people ask the AI to write. "type an essay…" means generate, but "type hello world" stays literal.
_PIECES = (r"essay|e-?mail|letter|cover letter|story|short story|poem|haiku|limerick|paragraph|summary|note|notes|"
           r"message|article|report|list|to-?do list|blog(?: post)?|speech|description|bio|biography|caption|tweet|"
           r"post|reply|response|resume|cv|outline|script|code|function|program|joke|song|lyrics|introduction|"
           r"conclusion|review|apology|invitation|application|proposal|essay outline|recipe|plan|agenda|memo|"
           r"thank[- ]you note|toast|eulogy|limerick|sonnet|rap|dialogue|statement|abstract|thesis|answer")
_VERB = r"(?:write|type|draft|compose|generate|create|make|give me|come up with)"
_COMPOSE = re.compile(
    rf"^(?:(?:hey\s+)?jarvis,?\s+)?(?:please\s+|can you\s+|could you\s+|now\s+)*(?P<verb>{_VERB})\s+(?:me\s+|out\s+|up\s+)?"
    rf"(?:a|an|the|some|one|two|three|\d+|a few|a short|a long|my)\b[^.?!]*?\b(?:{_PIECES})s?\b", re.I)
# "…and type it there", ", then paste it in notepad", "…and put that into word"
_PUT = re.compile(r"\s*(?:,|\band\b|\bthen\b|\s)+\s*(?:then\s+)?(?:type|put|paste|write|enter|insert|add|drop)\s+"
                  r"(?:it|that|this|them|the (?:text|result|essay|whole thing))\b(?P<rest>.*)$", re.I)
_HERE = re.compile(r"^\s*(?:out\s+)?(?:there|here|in there|in here|over there|for me|now|please|\s)*[.!?]*\s*$", re.I)
_IN_APP = re.compile(r"^\s*(?:out\s+)?(?:in|into|inside)\s+(?:the\s+|my\s+|a\s+new\s+|a\s+)?(?P<app>[\w .+-]{2,40}?)"
                     r"(?:\s+(?:app|window|document|doc|file))?\s*[.!?]*\s*$", re.I)


@dataclass
class ComposeRequest:
    prompt: str                    # what to ask the AI to write
    app: Optional[str] = None      # explicit target app ("notepad"), or None
    here: bool = False             # "there" / "here" / "it": the app JARVIS last opened, else the focused window


def parse(text: str, known_apps=()) -> Optional[ComposeRequest]:
    """``known_apps``: names that may end a request ("…in notepad"); other trailing "in X" stays in the topic."""
    raw = (text or "").strip()
    m = _COMPOSE.match(raw)
    if not m:
        return None
    verb = m.group("verb").lower()
    body, app, here = raw, None, False
    put = _PUT.search(raw, m.end())
    if put:
        body = raw[:put.start()]
        rest = put.group("rest")
        app_match = _IN_APP.match(rest)
        if app_match:
            app = app_match.group("app").strip()
        elif _HERE.match(rest):
            here = True
        else:
            return None                                   # "…and put it on my calendar": not typing
    else:
        tail = re.search(r"\s+(?:in|into|inside)\s+(?:the\s+|my\s+|a\s+new\s+|a\s+)?(?P<app>[\w .+-]{2,40}?)"
                         r"(?:\s+(?:app|window|document|doc|file))?\s*[.!?]*\s*$", raw)
        known = {a.lower() for a in known_apps}
        if tail and tail.group("app").strip().lower() in known:
            app = tail.group("app").strip()
            body = raw[:tail.start()]
        elif re.search(r"\s+(?:there|here|in there|in here)\s*[.!?]*\s*$", raw, re.I):
            here = True
            body = re.sub(r"\s+(?:there|here|in there|in here)\s*[.!?]*\s*$", "", raw, flags=re.I)
        elif verb != "type":
            return None                                   # "write me a poem": answer in chat as before
        else:
            here = True                                   # "type an essay about X": into the current app
    prompt = re.sub(rf"^(?:(?:hey\s+)?jarvis,?\s+)?(?:please\s+|can you\s+|could you\s+|now\s+)*{_VERB}\b", "Write",
                    body.strip(), count=1, flags=re.I).strip().rstrip(",;:")
    return ComposeRequest(prompt=prompt, app=app, here=here)


_OPENED = re.compile(r"^Opened (?P<name>[^\n]+?)\.\s*$")


def opened_app(reply: str) -> Optional[str]:
    """'Opened Notepad.' → 'Notepad'; websites and folders opened in a browser don't count."""
    m = _OPENED.match((reply or "").strip())
    if not m:
        return None
    name = m.group("name")
    if " in " in name or "/" in name or "folder" in name.lower():
        return None
    return name.strip()
