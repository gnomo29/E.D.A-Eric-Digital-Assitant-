"""Tests para integración opcional Spotify Web API."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

try:
    from spotipy.exceptions import SpotifyException
except ImportError:  # pragma: no cover
    SpotifyException = None  # type: ignore[misc, assignment]


def _fake_fat_cache_path() -> MagicMock:
    p = MagicMock()
    p.is_file.return_value = True
    p.stat.return_value = MagicMock(st_size=500)
    return p


class SpotifyWebTests(unittest.TestCase):
    @patch("eda.spotify_web.client_id", return_value="")
    def test_skip_when_not_configured(self, _mock_cid: MagicMock) -> None:
        from eda.spotify_web import try_play_via_web_api

        status, detail = try_play_via_web_api("queen")
        self.assertEqual(status, "skip")
        self.assertIn("not_configured", detail)

    @unittest.skipIf(SpotifyException is None, "spotipy no instalado")
    def test_ok_start_playback(self) -> None:
        from eda.spotify_web import try_play_via_web_api

        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:abc123"}]}}
        sp.devices.return_value = {"devices": [{"id": "d1", "is_active": True, "type": "Computer"}]}
        sp.track.return_value = {"name": "Test Track"}

        with patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "test_id", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False):
            with patch("eda.spotify_web.token_cache_path", return_value=_fake_fat_cache_path()):
                with patch("eda.spotify_web.run_interactive_spotify_login") as mock_login:
                    with patch("eda.spotify_web.get_spotify_client", return_value=sp):
                        status, detail = try_play_via_web_api("test query")
        self.assertEqual(status, "ok")
        self.assertIn("Test", detail)
        sp.start_playback.assert_called_once()
        kwargs = sp.start_playback.call_args.kwargs
        self.assertEqual(kwargs.get("uris"), ["spotify:track:abc123"])
        self.assertEqual(kwargs.get("device_id"), "d1")
        mock_login.assert_not_called()

    @unittest.skipIf(SpotifyException is None, "spotipy no instalado")
    def test_fail_no_active_device(self) -> None:
        from eda.spotify_web import try_play_via_web_api

        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": [{"uri": "spotify:track:z"}]}}
        sp.devices.return_value = {"devices": []}
        sp.start_playback.side_effect = SpotifyException(404, -1, "no active device", reason="")

        with patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False):
            with patch("eda.spotify_web.token_cache_path", return_value=_fake_fat_cache_path()):
                with patch("eda.spotify_web.run_interactive_spotify_login") as mock_login:
                    with patch("eda.spotify_web.get_spotify_client", return_value=sp):
                        status, detail = try_play_via_web_api("bohemian rhapsody queen")
        self.assertEqual(status, "fail")
        self.assertEqual(detail, "no_active_device")
        mock_login.assert_not_called()

    @unittest.skipIf(SpotifyException is None, "spotipy no instalado")
    def test_reauth_runs_login_and_retries(self) -> None:
        from eda.spotify_web import try_play_via_web_api

        with patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False):
            with patch("eda.spotify_web.token_cache_path", return_value=_fake_fat_cache_path()):
                with patch("eda.spotify_web.run_interactive_spotify_login", return_value=True) as mock_login:
                    with patch("eda.spotify_web._attempt_play") as mock_attempt:
                        mock_attempt.side_effect = [
                            ("fail", "auth_error_playback", True),
                            ("ok", "Canción", False),
                        ]
                        status, detail = try_play_via_web_api("algo")
        self.assertEqual(status, "ok")
        self.assertEqual(detail, "Canción")
        self.assertEqual(mock_attempt.call_count, 2)
        mock_login.assert_called_once()

    def test_describe_returns_nonempty_string(self) -> None:
        from eda import spotify_web

        s = spotify_web.describe_integration_status()
        self.assertIsInstance(s, str)
        self.assertGreater(len(s), 2)


if __name__ == "__main__":
    unittest.main()
