"""A tiny, dependency-free Markdown → Qt rich-text converter for the command bar's reply cards.

Qt's own ``Qt.MarkdownText`` gives no control over fonts or colours, so the bar
renders a pragmatic subset itself, styled with the HUD palette:

    **bold**  *italic* / _italic_  `code`  [link](url)  # headings
    - / * / + bullets   1. numbered lists   ``` fenced code blocks ```

Everything else is shown as plain (escaped) text, so a reply can never inject
markup. The output is meant for a word-wrapped ``QLabel`` (``Qt.RichText``).
"""
from __future__ import annotations

import html
import re

from ui import theme

_FONT_STACK = "'Segoe UI Variable Text','Segoe UI','Inter',Arial,sans-serif"
_MONO_STACK = "'Cascadia Code','Cascadia Mono',Consolas,'DejaVu Sans Mono',monospace"

_BULLET = re.compile(r"^(\s*)([-*+•])\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def looks_like_markdown(text: str) -> bool:
    """Cheap check: is there anything worth rendering as rich text?"""
    return bool(re.search(r"(\*\*|__|`|^\s*[-*+•]\s|^\s*\d+[.)]\s|^#{1,6}\s|\[[^\]]+\]\()", text or "", re.M))


def _inline(text: str) -> str:
    """Escape, then apply inline code / bold / italic / links."""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if len(part) > 1 and part.startswith("`") and part.endswith("`"):
            code = html.escape(part[1:-1])
            out.append(f"<span style=\"font-family:{_MONO_STACK}; color:{theme.ACCENT}; "
                       f"background-color:#10263A;\">&#8201;{code}&#8201;</span>")
            continue
        s = html.escape(part, quote=False)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   lambda m: f"<a href=\"{m.group(2)}\" style=\"color:{theme.ACCENT}; text-decoration:none;\">"
                             f"{m.group(1)}</a>", s)
        s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__",
                   lambda m: f"<b style=\"color:#FFFFFF;\">{m.group(1) or m.group(2)}</b>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])",
                   lambda m: f"<i>{m.group(1) or m.group(2)}</i>", s)
        out.append(s)
    return "".join(out)


def _list_row(marker: str, body: str, depth: int, numbered: bool) -> str:
    colour = theme.ACCENT_2 if numbered else theme.ACCENT
    indent = 4 + depth * 16
    mark_w = 22 if numbered else 14
    return (f"<table cellspacing=\"0\" cellpadding=\"0\" style=\"margin-top:2px; margin-bottom:2px;\"><tr>"
            f"<td width=\"{indent}\"></td>"
            f"<td width=\"{mark_w}\" style=\"color:{colour}; font-family:{_MONO_STACK};\">{marker}</td>"
            f"<td>{_inline(body)}</td></tr></table>")


def _code_block(lines) -> str:
    code = "<br>".join(html.escape(line).replace(" ", "&nbsp;") or "&nbsp;" for line in lines)
    return (f"<table width=\"100%\" cellspacing=\"0\" cellpadding=\"8\" bgcolor=\"#050C14\" "
            f"style=\"margin-top:4px; margin-bottom:4px; border:1px solid {theme.BORDER_SOFT};\"><tr>"
            f"<td style=\"font-family:{_MONO_STACK}; font-size:12px; color:#BFEFFF;\">{code}</td></tr></table>")


def to_html(text: str) -> str:
    """Render the supported Markdown subset to Qt rich text."""
    lines = (text or "").replace("\r\n", "\n").replace("\t", "    ").split("\n")
    blocks = []
    para = []

    def flush():
        if para:
            blocks.append(f"<p style=\"margin:{6 if blocks else 0}px 0 0 0;\">{'<br>'.join(_inline(x) for x in para)}</p>")
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            flush()
            code = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            blocks.append(_code_block(code))
            i += 1
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            size = {1: 15, 2: 14}.get(len(m.group(1)), 13)
            blocks.append(f"<p style=\"margin:4px 0 4px 0; font-size:{size}px; font-weight:600; "
                          f"color:{theme.ACCENT}; letter-spacing:1px;\">{_inline(m.group(2))}</p>")
            i += 1
            continue
        if _RULE.match(line):
            flush()
            blocks.append(f"<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"margin:4px 0;\">"
                          f"<tr><td height=\"1\" bgcolor=\"{theme.BORDER}\"></td></tr></table>")
            i += 1
            continue
        m = _BULLET.match(line)
        if m:
            flush()
            blocks.append(_list_row("▸", m.group(3), len(m.group(1)) // 2, numbered=False))
            i += 1
            continue
        m = _NUMBER.match(line)
        if m:
            flush()
            blocks.append(_list_row(f"{int(m.group(2)):02d}", m.group(3), len(m.group(1)) // 2, numbered=True))
            i += 1
            continue
        para.append(line.strip())
        i += 1
    flush()
    body = "".join(blocks)
    return f"<div style=\"font-family:{_FONT_STACK}; color:{theme.TEXT};\">{body}</div>"
