"""Outlook email and calendar. Reading email/calendar and saving a draft run
immediately; sending an email or a reply always confirms first — it leaves your
outbox and reaches someone else, unlike anything else JARVIS does with Outlook."""
import re

from core.tools import params
from handlers.base import Handler

_LIST_EMAILS = re.compile(r"^(?:please\s+)?(?:list|show)\s+(?:my\s+)?(?:recent\s+)?(unread\s+)?emails?"
                          r"[.!?]*$", re.I)
_READ_EMAIL = re.compile(r"^(?:please\s+)?read\s+(?:the\s+)?email\s+(?:about|from)\s+(.+?)[.!?]*$", re.I)
_SEND_EMAIL = re.compile(r"^(?:please\s+)?send\s+(?:an\s+)?email\s+to\s+(\S+)\s+(?:with\s+)?subject\s+"
                         r"(.+?)\s+(?:saying|body)\s+(.+?)[.!?]*$", re.I)
_DRAFT_EMAIL = re.compile(r"^(?:please\s+)?draft\s+(?:an\s+)?email\s+to\s+(\S+)\s+(?:with\s+)?subject\s+"
                          r"(.+?)\s+(?:saying|body)\s+(.+?)[.!?]*$", re.I)
_REPLY_EMAIL = re.compile(r"^(?:please\s+)?reply\s+to\s+(?:the\s+)?email\s+(?:about|from)\s+(.+?)\s+"
                          r"(?:saying|with)\s+(.+?)[.!?]*$", re.I)
_LIST_EVENTS = re.compile(r"\b(?:upcoming|next)\s+(?:calendar\s+)?events?\b|"
                          r"\bwhat(?:'s|s| is) on my calendar\b|"
                          r"\bmy\s+(?:meetings|schedule)(?:\s+(?:today|tomorrow|this week))?\b", re.I)


class OutlookHandler(Handler):
    intents = {"EMAIL"}

    def handle(self, text, intent):
        app = self.app
        ol = getattr(app, "outlook", None)
        if ol is None:
            return "Outlook integration isn't available."
        confirm = app._ask_to_confirm
        low = text.strip()

        m = _LIST_EMAILS.match(low)
        if m:
            return ol.list_recent_emails(unread_only=bool(m.group(1)))
        m = _READ_EMAIL.match(low)
        if m:
            return ol.read_email(m.group(1).strip())
        m = _SEND_EMAIL.match(low)
        if m:
            to, subject, body = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            return confirm(f"Send an email to {to} with subject '{subject}'?",
                          lambda: ol.send_email(to, subject, body), "send_email")
        m = _DRAFT_EMAIL.match(low)
        if m:
            to, subject, body = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            return ol.draft_email(to, subject, body)
        m = _REPLY_EMAIL.match(low)
        if m:
            query, body = m.group(1).strip(), m.group(2).strip()
            return confirm(f"Send a reply to the email about '{query}'?",
                          lambda: ol.reply_to_email(query, body), "reply_to_email")
        if _LIST_EVENTS.search(low):
            return ol.list_upcoming_events()
        return None

    def register_tools(self, t):
        ol = getattr(self.app, "outlook", None)
        if ol is None:
            return
        t.add("list_recent_emails", "List recent emails in the Outlook inbox.", ol.list_recent_emails,
              params(limit=("integer", "How many to show"), unread_only=("boolean", "Only unread emails")))
        t.add("read_email", "Read an email by matching its subject.", ol.read_email,
              params(["query"], query=("string", "Text to match in the subject")))
        t.add("send_email", "Send an email via Outlook.", ol.send_email,
              params(["to", "subject", "body"], to=("string", "Recipient address"),
                    subject=("string", "Subject line"), body=("string", "Email body"),
                    cc=("string", "CC address(es), optional")),
              confirm=True, confirm_text="Send an email to {to} with subject '{subject}'?")
        t.add("draft_email", "Save an email draft in Outlook without sending it.", ol.draft_email,
              params(["to", "subject", "body"], to=("string", "Recipient address"),
                    subject=("string", "Subject line"), body=("string", "Email body"),
                    cc=("string", "CC address(es), optional")))
        t.add("reply_to_email", "Reply to and send a reply to an email matched by subject.", ol.reply_to_email,
              params(["query", "body"], query=("string", "Text to match in the subject"),
                    body=("string", "Reply text")),
              confirm=True, confirm_text="Send a reply to the email about '{query}'?")
        t.add("list_upcoming_events", "List upcoming Outlook calendar events.", ol.list_upcoming_events,
              params(days=("integer", "How many days ahead to look")))
