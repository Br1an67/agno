"""Unit tests for CommuneTools."""

from unittest.mock import MagicMock, patch
import pytest


def _make_tools(
    api_key: str = "test-key",
    from_address: str | None = None,
    enable_email: bool = True,
    enable_sms: bool = True,
):
    """Create a CommuneTools instance with a mocked Commune client."""
    with patch("agno.tools.commune.Commune") as MockCommune:
        mock_client = MagicMock()
        MockCommune.return_value = mock_client
        tools = CommuneTools(
            api_key=api_key,
            from_address=from_address,
            enable_email=enable_email,
            enable_sms=enable_sms,
        )
        return tools, mock_client


from agno.tools.commune import CommuneTools


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


class TestSendEmail:
    def test_send_email_success(self):
        tools, client = _make_tools()
        client.emails.send.return_value = {"id": "msg_001", "status": "sent"}

        result = tools.send_email(
            to="alice@example.com",
            subject="Hello",
            body="Hi there!",
        )

        assert "msg_001" in result
        assert "sent" in result
        client.emails.send.assert_called_once_with(
            to="alice@example.com", subject="Hello", body="Hi there!"
        )

    def test_send_email_uses_instance_from_address(self):
        tools, client = _make_tools(from_address="agent@example.com")
        client.emails.send.return_value = {"id": "msg_002", "status": "sent"}

        tools.send_email(to="bob@example.com", subject="S", body="B")

        call_kwargs = client.emails.send.call_args[1]
        assert call_kwargs["from_address"] == "agent@example.com"

    def test_send_email_per_call_from_address_overrides(self):
        tools, client = _make_tools(from_address="default@example.com")
        client.emails.send.return_value = {"id": "msg_003", "status": "sent"}

        tools.send_email(
            to="bob@example.com",
            subject="S",
            body="B",
            from_address="override@example.com",
        )

        call_kwargs = client.emails.send.call_args[1]
        assert call_kwargs["from_address"] == "override@example.com"

    def test_send_email_empty_to(self):
        tools, client = _make_tools()
        result = tools.send_email(to="", subject="S", body="B")
        assert result.startswith("Error:")
        client.emails.send.assert_not_called()

    def test_send_email_empty_subject(self):
        tools, client = _make_tools()
        result = tools.send_email(to="x@example.com", subject="", body="B")
        assert result.startswith("Error:")
        client.emails.send.assert_not_called()

    def test_send_email_empty_body(self):
        tools, client = _make_tools()
        result = tools.send_email(to="x@example.com", subject="S", body="")
        assert result.startswith("Error:")
        client.emails.send.assert_not_called()

    def test_send_email_api_error(self):
        tools, client = _make_tools()
        client.emails.send.side_effect = RuntimeError("network timeout")

        result = tools.send_email(to="x@example.com", subject="S", body="B")

        assert result.startswith("Error")
        assert "network timeout" in result


# ---------------------------------------------------------------------------
# read_inbox
# ---------------------------------------------------------------------------


class TestReadInbox:
    def _sample_emails(self):
        return [
            {
                "id": "msg_a",
                "from_address": "alice@example.com",
                "subject": "Meeting tomorrow",
                "body": "Can we move our 3pm meeting to 4pm?",
                "received_at": "2024-01-01T10:00:00Z",
                "read": False,
            },
            {
                "id": "msg_b",
                "from_address": "bob@co.com",
                "subject": "Invoice #1042",
                "body": "Please find attached invoice for services rendered.",
                "received_at": "2024-01-01T09:00:00Z",
                "read": True,
            },
        ]

    def test_read_inbox_returns_formatted_string(self):
        tools, client = _make_tools()
        client.emails.list.return_value = self._sample_emails()

        result = tools.read_inbox()

        assert "[1]" in result
        assert "[2]" in result
        assert "alice@example.com" in result
        assert "Meeting tomorrow" in result
        assert "UNREAD" in result
        assert "bob@co.com" in result

    def test_read_inbox_empty(self):
        tools, client = _make_tools()
        client.emails.list.return_value = []

        result = tools.read_inbox()

        assert result == "No emails found."

    def test_read_inbox_passes_limit(self):
        tools, client = _make_tools()
        client.emails.list.return_value = []

        tools.read_inbox(limit=25)

        client.emails.list.assert_called_once_with(limit=25, unread_only=False)

    def test_read_inbox_unread_only(self):
        tools, client = _make_tools()
        client.emails.list.return_value = []

        tools.read_inbox(unread_only=True)

        client.emails.list.assert_called_once_with(limit=10, unread_only=True)

    def test_read_inbox_preview_truncated(self):
        tools, client = _make_tools()
        long_body = "A" * 200
        client.emails.list.return_value = [
            {
                "id": "msg_long",
                "from_address": "x@example.com",
                "subject": "Long",
                "body": long_body,
                "received_at": "2024-01-01T10:00:00Z",
                "read": True,
            }
        ]

        result = tools.read_inbox()

        # Preview must be truncated with ellipsis
        assert "..." in result
        # Full body should not appear
        assert long_body not in result

    def test_read_inbox_api_error(self):
        tools, client = _make_tools()
        client.emails.list.side_effect = RuntimeError("server error")

        result = tools.read_inbox()

        assert result.startswith("Error")


# ---------------------------------------------------------------------------
# search_emails
# ---------------------------------------------------------------------------


class TestSearchEmails:
    def test_search_returns_results(self):
        tools, client = _make_tools()
        client.emails.search.return_value = [
            {
                "id": "msg_s1",
                "from_address": "vendor@example.com",
                "subject": "Invoice #999",
                "body": "Please pay invoice 999.",
                "received_at": "2024-01-01T08:00:00Z",
                "read": False,
            }
        ]

        result = tools.search_emails(query="invoice")

        assert "[1]" in result
        assert "Invoice #999" in result
        client.emails.search.assert_called_once_with(query="invoice", limit=5)

    def test_search_empty_query(self):
        tools, client = _make_tools()

        result = tools.search_emails(query="")

        assert result.startswith("Error:")
        client.emails.search.assert_not_called()

    def test_search_no_results(self):
        tools, client = _make_tools()
        client.emails.search.return_value = []

        result = tools.search_emails(query="nonexistent")

        assert result == "No emails found."


# ---------------------------------------------------------------------------
# send_sms — E.164 validation
# ---------------------------------------------------------------------------


class TestSendSms:
    def test_send_sms_valid_number(self):
        tools, client = _make_tools()
        client.sms.send.return_value = {"id": "sms_001", "status": "sent"}

        result = tools.send_sms(to="+15551234567", body="Hello!")

        assert "sms_001" in result
        assert "sent" in result
        client.sms.send.assert_called_once_with(to="+15551234567", body="Hello!")

    def test_send_sms_missing_plus(self):
        tools, client = _make_tools()

        result = tools.send_sms(to="15551234567", body="Hello!")

        assert result.startswith("Error:")
        assert "E.164" in result
        client.sms.send.assert_not_called()

    def test_send_sms_letters_in_number(self):
        tools, client = _make_tools()

        result = tools.send_sms(to="+1555ABC4567", body="Hello!")

        assert result.startswith("Error:")
        client.sms.send.assert_not_called()

    def test_send_sms_empty_to(self):
        tools, client = _make_tools()

        result = tools.send_sms(to="", body="Hello!")

        assert result.startswith("Error:")
        client.sms.send.assert_not_called()

    def test_send_sms_empty_body(self):
        tools, client = _make_tools()

        result = tools.send_sms(to="+15551234567", body="")

        assert result.startswith("Error:")
        client.sms.send.assert_not_called()

    def test_send_sms_api_error(self):
        tools, client = _make_tools()
        client.sms.send.side_effect = RuntimeError("carrier rejected")

        result = tools.send_sms(to="+15551234567", body="Hi")

        assert result.startswith("Error")
        assert "carrier rejected" in result

    @pytest.mark.parametrize(
        "number",
        [
            "+15551234567",  # US
            "+442071234567",  # UK
            "+819012345678",  # Japan
            "+61412345678",  # Australia
        ],
    )
    def test_send_sms_valid_e164_numbers(self, number):
        tools, client = _make_tools()
        client.sms.send.return_value = {"id": "sms_x", "status": "sent"}

        result = tools.send_sms(to=number, body="test")

        assert "Error" not in result

    @pytest.mark.parametrize(
        "number",
        [
            "0015551234567",  # No leading +
            "+1",  # Too short
            "+",  # Just a plus
            "555-123-4567",  # Dashes, no plus
            "+0155512345678",  # Leading zero after +
        ],
    )
    def test_send_sms_invalid_e164_numbers(self, number):
        tools, client = _make_tools()

        result = tools.send_sms(to=number, body="test")

        assert result.startswith("Error:")


# ---------------------------------------------------------------------------
# get_credits — low balance warning
# ---------------------------------------------------------------------------


class TestGetCredits:
    def test_get_credits_normal_balance(self):
        tools, client = _make_tools()
        client.credits.get.return_value = {"balance": 42.50, "currency": "USD"}

        result = tools.get_credits()

        assert "$42.50" in result
        assert "USD" in result
        assert "Warning" not in result

    def test_get_credits_low_balance_warning(self):
        tools, client = _make_tools()
        client.credits.get.return_value = {"balance": 2.00, "currency": "USD"}

        result = tools.get_credits()

        assert "Warning" in result
        assert "$2.00" in result

    def test_get_credits_zero_balance(self):
        tools, client = _make_tools()
        client.credits.get.return_value = {"balance": 0.0, "currency": "USD"}

        result = tools.get_credits()

        assert "Warning" in result
        assert "$0.00" in result

    def test_get_credits_exactly_five_no_warning(self):
        """Balance of exactly $5.00 should NOT trigger the warning."""
        tools, client = _make_tools()
        client.credits.get.return_value = {"balance": 5.0, "currency": "USD"}

        result = tools.get_credits()

        assert "Warning" not in result

    def test_get_credits_api_error(self):
        tools, client = _make_tools()
        client.credits.get.side_effect = RuntimeError("auth failed")

        result = tools.get_credits()

        assert result.startswith("Error")
        assert "auth failed" in result


# ---------------------------------------------------------------------------
# get_email
# ---------------------------------------------------------------------------


class TestGetEmail:
    def test_get_email_success(self):
        tools, client = _make_tools()
        client.emails.get.return_value = {
            "id": "msg_xyz",
            "from_address": "sender@example.com",
            "to": "agent@commune.io",
            "subject": "Follow up",
            "body": "Just checking in.",
            "received_at": "2024-06-01T12:00:00Z",
            "read": False,
        }
        client.emails.mark_read.return_value = {"success": True}

        result = tools.get_email("msg_xyz")

        assert "msg_xyz" in result
        assert "sender@example.com" in result
        assert "Follow up" in result
        assert "Just checking in." in result
        client.emails.mark_read.assert_called_once_with("msg_xyz")

    def test_get_email_empty_id(self):
        tools, client = _make_tools()

        result = tools.get_email("")

        assert result.startswith("Error:")
        client.emails.get.assert_not_called()

    def test_get_email_mark_read_failure_is_nonfatal(self):
        """mark_read raising should not cause get_email to return an error."""
        tools, client = _make_tools()
        client.emails.get.return_value = {
            "id": "msg_abc",
            "from_address": "a@b.com",
            "to": "c@d.com",
            "subject": "Test",
            "body": "Body text.",
            "received_at": "2024-06-01T12:00:00Z",
            "read": False,
        }
        client.emails.mark_read.side_effect = RuntimeError("mark_read failed")

        result = tools.get_email("msg_abc")

        # Should still succeed
        assert "msg_abc" in result
        assert "Body text." in result

    def test_get_email_api_error(self):
        tools, client = _make_tools()
        client.emails.get.side_effect = RuntimeError("not found")

        result = tools.get_email("msg_missing")

        assert result.startswith("Error")
