"""OutlookManager: email and calendar via Outlook COM automation, with
win32com.client mocked so these run without Windows or Outlook installed."""
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

from skills.outlook_manager import OutlookManager


def _fake_win32com(app_mock):
    fake_client = types.ModuleType("win32com.client")
    fake_client.Dispatch = Mock(return_value=app_mock)
    fake_win32com = types.ModuleType("win32com")
    fake_win32com.client = fake_client
    return {"win32com": fake_win32com, "win32com.client": fake_client}


def _mail_item(subject="Budget review", sender="Alice", received="9/20/2026", unread=False, body="Hello there"):
    item = Mock()
    item.Subject = subject
    item.SenderName = sender
    item.ReceivedTime = received
    item.UnRead = unread
    item.Body = body
    return item


class EmailTests(unittest.TestCase):
    def setUp(self):
        self.ol = OutlookManager()

    def _app_with_inbox(self, items):
        namespace = MagicMock()
        folder = MagicMock()
        folder.Items = MagicMock()
        folder.Items.__iter__ = Mock(return_value=iter(items))
        folder.Items.Restrict.return_value = folder.Items
        namespace.GetDefaultFolder.return_value = folder
        app = MagicMock()
        app.GetNamespace.return_value = namespace
        return app

    def test_list_recent_emails(self):
        items = [_mail_item("A"), _mail_item("B", unread=True)]
        app = self._app_with_inbox(items)
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.list_recent_emails()
        self.assertIn("A", result)
        self.assertIn("UNREAD B", result)

    def test_list_recent_emails_respects_limit(self):
        items = [_mail_item(f"Subject {i}") for i in range(5)]
        app = self._app_with_inbox(items)
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.list_recent_emails(limit=2)
        self.assertEqual(len(result.splitlines()), 2)

    def test_list_recent_emails_none(self):
        app = self._app_with_inbox([])
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.list_recent_emails()
        self.assertIn("No emails found", result)

    def test_list_recent_emails_connect_error(self):
        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = Mock(side_effect=Exception("not installed"))
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        with patch.dict(sys.modules, {"win32com": fake_win32com, "win32com.client": fake_client}):
            result = self.ol.list_recent_emails()
        self.assertIn("Couldn't connect to Outlook", result)

    def test_read_email_found(self):
        items = [_mail_item("Budget review", body="Please review the numbers.")]
        app = self._app_with_inbox(items)
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.read_email("budget")
        self.assertIn("Budget review", result)
        self.assertIn("Please review the numbers.", result)

    def test_read_email_not_found(self):
        app = self._app_with_inbox([_mail_item("Unrelated")])
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.read_email("budget")
        self.assertIn("No email matching", result)

    def test_read_email_truncates_long_body(self):
        items = [_mail_item("Budget review", body="x" * 3000)]
        app = self._app_with_inbox(items)
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.read_email("budget")
        self.assertIn("...", result)

    def test_send_email_success(self):
        mail = Mock()
        app = MagicMock()
        app.CreateItem.return_value = mail
        namespace = MagicMock()
        app.GetNamespace.return_value = namespace
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.send_email("bob@x.com", "Hi", "body text")
        self.assertIn("Sent an email to bob@x.com", result)
        mail.Send.assert_called_once()
        self.assertEqual(mail.To, "bob@x.com")
        self.assertEqual(mail.Subject, "Hi")

    def test_send_email_with_cc(self):
        mail = Mock()
        app = MagicMock()
        app.CreateItem.return_value = mail
        with patch.dict(sys.modules, _fake_win32com(app)):
            self.ol.send_email("bob@x.com", "Hi", "body", cc="carol@x.com")
        self.assertEqual(mail.CC, "carol@x.com")

    def test_send_email_error(self):
        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = Mock(side_effect=Exception("no outlook"))
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        with patch.dict(sys.modules, {"win32com": fake_win32com, "win32com.client": fake_client}):
            result = self.ol.send_email("bob@x.com", "Hi", "body")
        self.assertIn("Couldn't send the email", result)

    def test_draft_email_success(self):
        mail = Mock()
        app = MagicMock()
        app.CreateItem.return_value = mail
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.draft_email("bob@x.com", "Hi", "body")
        self.assertIn("Saved a draft to bob@x.com", result)
        mail.Save.assert_called_once()
        mail.Send.assert_not_called()

    def test_reply_to_email_success(self):
        reply = Mock(Body="original text")
        item = _mail_item("Budget review")
        item.Reply.return_value = reply
        app = self._app_with_inbox([item])
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.reply_to_email("budget", "sounds good")
        self.assertIn("Sent the reply to 'Budget review'", result)
        reply.Send.assert_called_once()
        self.assertIn("sounds good", reply.Body)

    def test_empty_query_never_replies_to_the_newest_email(self):
        item = _mail_item("Latest")
        app = self._app_with_inbox([item])
        with patch.dict(sys.modules, _fake_win32com(app)):
            self.assertIn("No email matching", self.ol.reply_to_email("  ", "ok"))
        item.Reply.assert_not_called()

    def test_reply_to_email_not_found(self):
        app = self._app_with_inbox([_mail_item("Unrelated")])
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.reply_to_email("budget", "sounds good")
        self.assertIn("No email matching", result)


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.ol = OutlookManager()

    def _event(self, subject="Standup", start="9/22/2026 9:00 AM", location=""):
        e = Mock()
        e.Subject = subject
        e.Start = start
        e.Location = location
        return e

    def test_list_upcoming_events(self):
        from datetime import datetime, timedelta
        import itertools
        now = datetime.now()
        past = self._event("Old", start=now - timedelta(days=1))
        soon = [self._event("Standup", start=now + timedelta(hours=2)),
                self._event("Review", start=now + timedelta(days=1), location="Room 2")]
        # An open-ended recurring series: sorted iteration must stop at the window's end.
        forever = (self._event("Weekly", start=now + timedelta(days=30 + 7 * i)) for i in itertools.count())
        namespace = MagicMock()
        folder = MagicMock()
        folder.Items = MagicMock()
        folder.Items.__iter__ = lambda _self: itertools.chain([past], soon, forever)
        namespace.GetDefaultFolder.return_value = folder
        app = MagicMock()
        app.GetNamespace.return_value = namespace
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.list_upcoming_events(days=7)
        self.assertIn("Standup", result)
        self.assertIn("Review", result)
        self.assertIn("Room 2", result)
        self.assertNotIn("Old", result)
        self.assertNotIn("Weekly", result)
        folder.Items.Restrict.assert_not_called()      # no locale-dependent date strings

    def test_list_upcoming_events_none(self):
        namespace = MagicMock()
        folder = MagicMock()
        folder.Items = MagicMock()
        folder.Items.Restrict.return_value = []
        namespace.GetDefaultFolder.return_value = folder
        app = MagicMock()
        app.GetNamespace.return_value = namespace
        with patch.dict(sys.modules, _fake_win32com(app)):
            result = self.ol.list_upcoming_events()
        self.assertIn("No upcoming events", result)

    def test_list_upcoming_events_connect_error(self):
        fake_client = types.ModuleType("win32com.client")
        fake_client.Dispatch = Mock(side_effect=Exception("no outlook"))
        fake_win32com = types.ModuleType("win32com")
        fake_win32com.client = fake_client
        with patch.dict(sys.modules, {"win32com": fake_win32com, "win32com.client": fake_client}):
            result = self.ol.list_upcoming_events()
        self.assertIn("Couldn't connect to Outlook", result)


if __name__ == "__main__":
    unittest.main()
