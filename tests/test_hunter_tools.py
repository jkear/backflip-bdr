"""Unit tests for hunter_tools — campaign/sending functions."""
from unittest.mock import MagicMock, patch

import pytest


HUNTER_MODULE = "tools.hunter_tools"


class TestHunterCreateLead:
    @patch(f"{HUNTER_MODULE}.requests.post")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_creates_lead_successfully(self, mock_key, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"id": 42}}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from tools.hunter_tools import hunter_create_lead
        result = hunter_create_lead(
            email="jane@acme.com",
            first_name="Jane",
            last_name="Doe",
            company="Acme Corp",
        )

        assert result["lead_id"] == 42
        assert result["email"] == "jane@acme.com"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["email"] == "jane@acme.com"

    @patch(f"{HUNTER_MODULE}.requests.post")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_handles_error_gracefully(self, mock_key, mock_post):
        mock_post.side_effect = RuntimeError("network error")

        from tools.hunter_tools import hunter_create_lead
        result = hunter_create_lead(email="jane@acme.com")

        assert result["lead_id"] is None
        assert "error" in result


class TestHunterAddRecipient:
    @patch(f"{HUNTER_MODULE}.requests.post")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_adds_recipients_successfully(self, mock_key, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "recipients": [
                    {"email": "a@test.com", "sending_status": "pending"},
                    {"email": "b@test.com", "sending_status": "pending"},
                ],
                "skipped_recipients": [],
            }
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from tools.hunter_tools import hunter_add_recipient
        result = hunter_add_recipient(campaign_id=123, emails=["a@test.com", "b@test.com"])

        assert result["campaign_id"] == 123
        assert len(result["added"]) == 2
        assert len(result["skipped"]) == 0

    @patch(f"{HUNTER_MODULE}.requests.post")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_caps_at_50_emails(self, mock_key, mock_post):
        """Hunter API limit: 50 emails per call."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"recipients": [], "skipped_recipients": []}}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from tools.hunter_tools import hunter_add_recipient
        emails = [f"user{i}@test.com" for i in range(60)]
        hunter_add_recipient(campaign_id=1, emails=emails)

        sent_emails = mock_post.call_args.kwargs["json"]["emails"]
        assert len(sent_emails) == 50

    @patch(f"{HUNTER_MODULE}.requests.post")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_reports_skipped_recipients(self, mock_key, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "recipients": [{"email": "a@test.com"}],
                "skipped_recipients": [
                    {"email": "b@test.com", "reason": "duplicate"},
                ],
            }
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        from tools.hunter_tools import hunter_add_recipient
        result = hunter_add_recipient(campaign_id=1, emails=["a@test.com", "b@test.com"])

        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["reason"] == "duplicate"

    @patch(f"{HUNTER_MODULE}.requests.post")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_handles_error_gracefully(self, mock_key, mock_post):
        mock_post.side_effect = RuntimeError("network error")

        from tools.hunter_tools import hunter_add_recipient
        result = hunter_add_recipient(campaign_id=1, emails=["a@test.com"])

        assert result["added"] == []
        assert "error" in result


class TestHunterListCampaigns:
    @patch(f"{HUNTER_MODULE}.requests.get")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_lists_campaigns(self, mock_key, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "campaigns": [
                    {"id": 1, "name": "Q1 Outreach", "started": True},
                    {"id": 2, "name": "Q2 Outreach", "started": False},
                ]
            }
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        from tools.hunter_tools import hunter_list_campaigns
        result = hunter_list_campaigns()

        assert len(result["campaigns"]) == 2


class TestHunterStartCampaign:
    @patch(f"{HUNTER_MODULE}.requests.put")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_starts_campaign(self, mock_key, mock_put):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        from tools.hunter_tools import hunter_start_campaign
        result = hunter_start_campaign(campaign_id=42)

        assert result["started"] is True
        assert result["campaign_id"] == 42

    @patch(f"{HUNTER_MODULE}.requests.put")
    @patch(f"{HUNTER_MODULE}._api_key", return_value="test-key")
    def test_handles_error(self, mock_key, mock_put):
        mock_put.side_effect = RuntimeError("forbidden")

        from tools.hunter_tools import hunter_start_campaign
        result = hunter_start_campaign(campaign_id=42)

        assert result["started"] is False
        assert "error" in result
