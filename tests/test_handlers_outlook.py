"""OutlookHandler: reads/drafts run immediately; sending an email or a reply
confirms first."""
import unittest
from unittest.mock import Mock

from core.tools import ToolRegistry
from handlers.outlook import OutlookHandler


class FakeApp:
    def __init__(self):
        self.outlook = Mock()
        self.pending = []

    def _ask_to_confirm(self, prompt, action, label=""):
        self.pending.append((label, action))
        return f"{prompt} Reply yes to confirm, or no to cancel."


class OutlookHandlerTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.h = OutlookHandler(self.app)

    def test_list_emails_runs_immediately(self):
        self.app.outlook.list_recent_emails.return_value = "1. Hi — Bob — today"
        reply = self.h.handle("list my recent emails", "EMAIL")
        self.assertFalse(self.app.pending)
        self.app.outlook.list_recent_emails.assert_called_once_with(unread_only=False)
        self.assertEqual(reply, "1. Hi — Bob — today")

    def test_list_unread_emails(self):
        self.h.handle("show unread emails", "EMAIL")
        self.app.outlook.list_recent_emails.assert_called_once_with(unread_only=True)

    def test_read_email_runs_immediately(self):
        self.app.outlook.read_email.return_value = "From: Bob\nSubject: Budget"
        reply = self.h.handle("read the email about budget", "EMAIL")
        self.assertFalse(self.app.pending)
        self.app.outlook.read_email.assert_called_once_with("budget")
        self.assertIn("Budget", reply)

    def test_send_email_confirms(self):
        self.h.handle("send an email to bob@x.com with subject Hi saying lets meet", "EMAIL")
        self.assertEqual(self.app.pending[-1][0], "send_email")
        self.app.outlook.send_email.assert_not_called()
        self.app.pending[-1][1]()
        self.app.outlook.send_email.assert_called_once_with("bob@x.com", "Hi", "lets meet")

    def test_draft_email_runs_immediately(self):
        self.app.outlook.draft_email.return_value = "Saved a draft to bob@x.com."
        reply = self.h.handle("draft an email to bob@x.com with subject Hi saying lets meet", "EMAIL")
        self.assertFalse(self.app.pending)
        self.app.outlook.draft_email.assert_called_once_with("bob@x.com", "Hi", "lets meet")
        self.assertEqual(reply, "Saved a draft to bob@x.com.")

    def test_reply_confirms(self):
        self.h.handle("reply to the email about budget saying sounds good", "EMAIL")
        self.assertEqual(self.app.pending[-1][0], "reply_to_email")
        self.app.outlook.reply_to_email.assert_not_called()
        self.app.pending[-1][1]()
        self.app.outlook.reply_to_email.assert_called_once_with("budget", "sounds good")

    def test_list_events_runs_immediately(self):
        self.app.outlook.list_upcoming_events.return_value = "• Standup — today"
        reply = self.h.handle("what is on my calendar", "EMAIL")
        self.assertFalse(self.app.pending)
        self.assertEqual(reply, "• Standup — today")

    def test_unrelated_text_returns_none(self):
        self.assertIsNone(self.h.handle("what time is it", "EMAIL"))

    def test_no_outlook(self):
        app = FakeApp()
        app.outlook = None
        h = OutlookHandler(app)
        self.assertEqual(h.handle("list my recent emails", "EMAIL"), "Outlook integration isn't available.")

    def test_register_tools_confirm_gating(self):
        t = ToolRegistry()
        self.h.register_tools(t)
        writes = ("send_email", "reply_to_email")
        reads = ("list_recent_emails", "read_email", "draft_email", "list_upcoming_events")
        for name in writes:
            self.assertTrue(t.get(name).confirm, name)
        for name in reads:
            self.assertFalse(t.get(name).confirm, name)

    def test_register_tools_no_outlook(self):
        app = FakeApp()
        app.outlook = None
        h = OutlookHandler(app)
        t = ToolRegistry()
        h.register_tools(t)
        self.assertIsNone(t.get("list_recent_emails"))


if __name__ == "__main__":
    unittest.main()
