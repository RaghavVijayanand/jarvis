"""Turn casual speech into the plain command the fast routes understand.

    "hi um can you like start chrome"          → "start chrome"
    "hey jarvis could you please fire up spotify for me" → "open spotify"
    "pull the calculator up real quick"        → "open the calculator"
    "chrome please"                            → "chrome"

Only the routing sees the tidied text. The language model (and the history)
always get exactly what was said, so nothing is lost when a request needs it.
Text after "type / write / say" is left alone — that's what gets typed.
"""
from __future__ import annotations

import re

_LEAD = re.compile(
    r"^(?:"
    r"(?:hey|hi|hello|hiya|yo|sup|oi|ok|okay)\s+jarvis|jarvis|"
    r"hi|hello|hey|hiya|yo|sup|good (?:morning|afternoon|evening)|"
    r"u+m+|u+h+|e+r+m*|h+m+|a+h+|oh|so|like|well|okay|ok|alright|right|yeah|yep|actually|basically|just|now|"
    r"(?:can|could|would|will|wo?n'?t) (?:you|u|ya)(?: (?:please|pls|maybe|quickly|just|kindly))*|"
    r"please|pls|plz|kindly|"
    r"i (?:want|need|would like|'?d like) (?:you )?to|i wanna|i need you to|"
    r"go ahead and|do me a favou?r and|be a dear and|let'?s|lets"
    r")\b[\s,.!-]*", re.I)
_TRAIL = re.compile(        # (?<!…): only try from the start of a space run — linear, not quadratic, on long gaps
    r"(?<![\s,])[\s,]+(?:please|pls|plz|for me|thanks|thank you|thx|real quick|quickly|right now|asap|"
    r"will you|would you|could you|can you|ok|okay|bro|man|dude|mate|yeah)\s*[.!?]*\s*$", re.I)
_FILLER = re.compile(r"(?<![\w'])(?:u+m+|u+h+|e+r+m+|h+m+)(?![\w'])[,.]?\s*", re.I)
_LITERAL = re.compile(r"^(?:type|write|say|dictate)\b", re.I)
_OPEN_SYNONYMS = (
    (re.compile(r"^(?:fire|boot|start|load|pull|bring|power|spin|open)\s+up\s+(?P<x>.+)$", re.I), "open {x}"),
    (re.compile(r"^(?:fire|boot|load|pull|bring|power|spin|get)\s+(?P<x>.+?)\s+up$", re.I), "open {x}"),
    (re.compile(r"^(?:launch|run the app|run the program)\s+(?P<x>.+)$", re.I), "open {x}"),
    (re.compile(r"^take me to\s+(?P<x>.+)$", re.I), "go to {x}"),
    (re.compile(r"^(?:go back to|bring back|switch back to|back to)\s+(?P<x>.+)$", re.I), "switch to {x}"),
    (re.compile(r"^(?:can|could|may) i (?:get|have)\s+(?P<x>.+?)\s+(?:open|opened|up|running)$", re.I), "open {x}"),
)
# "i need the calculator" → open it, but only for real app names ("i need help" stays a request).
_WANT_APP = re.compile(r"^(?:i need|i want|i'?d like|gimme|give me|get me)\s+(?:the\s+|my\s+|a\s+)?(?P<x>.+)$", re.I)


def tidy(text: str) -> str:
    original = (text or "").strip()
    out = original
    for _ in range(12):                                   # peel "hi, um, so like, can you…" layer by layer
        stripped = _LEAD.sub("", out, count=1).strip()
        if stripped == out:
            break
        out = stripped
    if _LITERAL.match(out):
        return out                                        # what follows "type" is the text itself
    out = _FILLER.sub("", out).strip()
    for _ in range(4):
        stripped = _TRAIL.sub("", out).strip()
        if stripped == out:
            break
        out = stripped
    out = out.rstrip(" ,.!?")
    for pattern, template in _OPEN_SYNONYMS:
        m = pattern.match(out)
        if m:
            out = template.format(x=m.group("x").strip())
            break
    m = _WANT_APP.match(out)
    if m:
        try:
            from skills.app_control import _APP_ALIASES
        except Exception:
            _APP_ALIASES = {}
        if m.group("x").strip().lower() in _APP_ALIASES:
            out = f"open {m.group('x').strip()}"
    return out or original
