"""Outlook email and calendar, via COM automation of the Outlook desktop app —
no cloud setup, no API keys; it drives the same Outlook you already sign into.

Reading email/calendar is immediate. Sending an email or a reply is confirm-gated
by the caller (handlers/outlook.py) — it leaves your outbox and reaches someone
else, unlike everything else in this skill. Saving a draft is NOT confirm-gated:
nothing leaves your machine until you send it yourself from Outlook (or ask
JARVIS to).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from core.logging_setup import get_logger

log = get_logger("jarvis.outlook")

_FOLDER_INBOX = 6          # olFolderInbox
_FOLDER_CALENDAR = 9       # olFolderCalendar
_MAIL_ITEM = 0             # olMailItem


_MAX_SCAN = 500           # newest inbox items looked at when finding an email by subject


def _outlook():
    import win32com.client
    try:
        import pythoncom
        pythoncom.CoInitialize()      # tools run on worker threads; COM needs this once per thread
    except Exception:
        pass
    app = win32com.client.Dispatch("Outlook.Application")
    namespace = app.GetNamespace("MAPI")
    return app, namespace


class OutlookManager:
    """Email and calendar via Outlook's COM automation interface."""

    # ── email ────────────────────────────────────────────────────────────────

    def list_recent_emails(self, limit: int = 10, unread_only: bool = False) -> str:
        try:
            _, namespace = _outlook()
        except Exception as exc:
            return f"Couldn't connect to Outlook: {exc}"
        try:
            items = namespace.GetDefaultFolder(_FOLDER_INBOX).Items
            items.Sort("[ReceivedTime]", True)
            if unread_only:
                items = items.Restrict("[Unread] = true")
            limit = max(1, min(50, int(limit)))
            lines = []
            for item in items:
                if len(lines) >= limit:
                    break
                try:
                    subject = getattr(item, "Subject", "") or "(no subject)"
                    sender = getattr(item, "SenderName", "") or "unknown"
                    received = getattr(item, "ReceivedTime", "")
                    unread = "UNREAD " if getattr(item, "UnRead", False) else ""
                    lines.append(f"{len(lines) + 1}. {unread}{subject} — {sender} — {received}")
                except Exception:
                    continue
        except Exception as exc:
            return f"Couldn't read email: {exc}"
        return "\n".join(lines) if lines else "No emails found."

    def _find_email(self, query: str):
        q = (query or "").strip().lower()
        if not q:
            return None             # '' is in every subject: it would pick (and reply to) the newest mail
        try:
            _, namespace = _outlook()
            items = namespace.GetDefaultFolder(_FOLDER_INBOX).Items
            items.Sort("[ReceivedTime]", True)
        except Exception:
            return None
        for scanned, item in enumerate(items):
            if scanned >= _MAX_SCAN:
                break
            try:
                if q in (getattr(item, "Subject", "") or "").lower():
                    return item
            except Exception:
                continue
        return None

    def read_email(self, query: str) -> str:
        item = self._find_email(query)
        if item is None:
            return f"No email matching '{query}'."
        try:
            subject = getattr(item, "Subject", "") or "(no subject)"
            sender = getattr(item, "SenderName", "") or "unknown"
            received = getattr(item, "ReceivedTime", "")
            body = (getattr(item, "Body", "") or "").strip()
            if len(body) > 2000:
                body = body[:2000] + "..."
        except Exception as exc:
            return f"Couldn't read that email: {exc}"
        return f"From: {sender}\nSubject: {subject}\nReceived: {received}\n\n{body}"

    def send_email(self, to: str, subject: str, body: str, cc: str = "") -> str:
        try:
            app, _ = _outlook()
            mail = app.CreateItem(_MAIL_ITEM)
            mail.To = to
            if cc:
                mail.CC = cc
            mail.Subject = subject
            mail.Body = body
            mail.Send()
        except Exception as exc:
            return f"Couldn't send the email: {exc}"
        return f"Sent an email to {to}."

    def draft_email(self, to: str, subject: str, body: str, cc: str = "") -> str:
        try:
            app, _ = _outlook()
            mail = app.CreateItem(_MAIL_ITEM)
            mail.To = to
            if cc:
                mail.CC = cc
            mail.Subject = subject
            mail.Body = body
            mail.Save()
        except Exception as exc:
            return f"Couldn't save the draft: {exc}"
        return f"Saved a draft to {to}."

    def reply_to_email(self, query: str, body: str) -> str:
        item = self._find_email(query)
        if item is None:
            return f"No email matching '{query}'."
        try:
            subject = getattr(item, "Subject", "") or "(no subject)"
            sender = getattr(item, "SenderName", "") or "unknown"
            reply = item.Reply()
            reply.Body = f"{body}\n\n{reply.Body}"
            reply.Send()
        except Exception as exc:
            return f"Couldn't send the reply: {exc}"
        return f"Sent the reply to '{subject}' from {sender}."

    # ── calendar ─────────────────────────────────────────────────────────────

    def list_upcoming_events(self, days: int = 7) -> str:
        try:
            _, namespace = _outlook()
        except Exception as exc:
            return f"Couldn't connect to Outlook: {exc}"
        try:
            items = namespace.GetDefaultFolder(_FOLDER_CALENDAR).Items
            items.IncludeRecurrences = True
            items.Sort("[Start]")
            start = datetime.now()
            end = start + timedelta(days=max(1, min(60, int(days))))
            # Filtered here, not with Items.Restrict: Restrict parses dates in the *system locale*
            # (dd/mm on an Indian PC), so a hard-coded mm/dd string picked the wrong days. With
            # IncludeRecurrences an open-ended series never ends, so stop at the window's end.
            lines = []
            for scanned, event in enumerate(items):
                if scanned >= 2000 or len(lines) >= 30:
                    break
                try:
                    when = getattr(event, "Start", None)
                    local = datetime(when.year, when.month, when.day, when.hour, when.minute)
                    if local < start:
                        continue
                    if local > end:
                        break
                    subject = getattr(event, "Subject", "") or "(no subject)"
                    location = getattr(event, "Location", "") or ""
                    lines.append(f"• {subject} — {when}" + (f" @ {location}" if location else ""))
                except Exception:
                    continue
        except Exception as exc:
            return f"Couldn't read the calendar: {exc}"
        return "\n".join(lines[:30]) if lines else "No upcoming events."
