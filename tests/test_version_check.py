"""Tests for supervisor.version_check module."""

import json
from unittest.mock import MagicMock, patch

from supervisor.version_check import _fetch_latest, check_for_update_sync


class TestFetchLatest:
    def test_returns_version(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"info": {"version": "2.0.0"}}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("supervisor.version_check.urlopen", return_value=mock_resp):
            result = _fetch_latest()
        assert result == "2.0.0"

    def test_returns_none_on_network_error(self):
        with patch("supervisor.version_check.urlopen", side_effect=OSError("no network")):
            result = _fetch_latest()
        assert result is None

    def test_returns_none_on_bad_json(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("supervisor.version_check.urlopen", return_value=mock_resp):
            result = _fetch_latest()
        assert result is None


class TestCheckSync:
    def test_update_available(self):
        with patch("supervisor.version_check._fetch_latest", return_value="9.9.9"):
            current, latest = check_for_update_sync()
        assert latest == "9.9.9"

    def test_up_to_date(self):
        with patch("supervisor.version_check._fetch_latest") as mock:
            with patch("supervisor.version_check.__version__", "1.0.1"):
                mock.return_value = "1.0.1"
                current, latest = check_for_update_sync()
        assert latest is None

    def test_network_failure(self):
        with patch("supervisor.version_check._fetch_latest", return_value=None):
            current, latest = check_for_update_sync()
        assert latest is None
