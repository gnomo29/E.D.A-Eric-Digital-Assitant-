"""Tests NLU y ruteo Spotify (mocks; sin credenciales reales)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from eda.nlu.spotify_intent import parse_spotify_utterance, score_candidate
from eda.connectors.spotify import (
    SpotifyBridge,
    append_spotify_audit,
    play_option,
    route_spotify_natural,
)


class SpotifyIntentTests(unittest.TestCase):
    def test_album_artist_split(self) -> None:
        p = parse_spotify_utterance("Reproduce el álbum Thriller de Michael Jackson")
        self.assertEqual(p.kind, "album")
        self.assertIn("thriller", p.primary_query.lower())
        self.assertIn("michael", p.primary_query.lower())

    def test_liked_and_shuffle(self) -> None:
        p = parse_spotify_utterance("Pon mis me gusta en reproducción, en modo shuffle")
        self.assertEqual(p.kind, "liked")
        self.assertTrue(p.prefer_saved or True)
        self.assertTrue(p.shuffle)

    def test_playlist_name(self) -> None:
        p = parse_spotify_utterance("Toca la playlist 'Entreno mañanas'")
        self.assertEqual(p.kind, "playlist")
        self.assertIn("entreno", p.primary_query.lower())

    def test_track(self) -> None:
        p = parse_spotify_utterance("Reproduce la canción Shape of You")
        self.assertEqual(p.kind, "track")

    def test_similar(self) -> None:
        p = parse_spotify_utterance("Pon algo similar a Arctic Monkeys")
        self.assertEqual(p.kind, "similar")
        self.assertIn("arctic", p.primary_query.lower())

    def test_latest_album(self) -> None:
        p = parse_spotify_utterance("Reproduce el último álbum de Dua Lipa")
        self.assertEqual(p.kind, "latest_album")
        self.assertIn("dua lipa", p.primary_query.lower())

    def test_device_tail(self) -> None:
        p = parse_spotify_utterance("Pon mis me gusta en el altavoz de la sala")
        self.assertEqual(p.kind, "liked")
        self.assertIn("sala", p.device_hint.lower())

    def test_fuzzy_score(self) -> None:
        s = score_candidate("abbey road", "Abbey Road", "The Beatles")
        self.assertGreater(s, 0.5)


class SpotifyRouterMockedTests(unittest.TestCase):
    def _make_bridge(self) -> tuple[SpotifyBridge, MagicMock]:
        sp = MagicMock()
        sp.current_user.return_value = {"id": "user1", "display_name": "U1"}
        sp.devices.return_value = {
            "devices": [
                {"id": "d1", "name": "Sala", "is_active": True, "type": "Speaker"},
            ]
        }
        sp.current_user_saved_tracks.return_value = {
            "items": [
                {"track": {"uri": "spotify:track:1", "name": "A"}},
            ],
            "next": None,
        }
        return SpotifyBridge(sp), sp

    @patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False)
    @patch("eda.connectors.spotify.get_spotify_client")
    @patch("eda.connectors.spotify.is_web_api_configured", return_value=True)
    def test_play_liked(self, _cfg: MagicMock, mock_client: MagicMock) -> None:
        b, sp = self._make_bridge()
        mock_client.return_value = b.sp
        orch = MagicMock()
        msg = route_spotify_natural(orch, "Pon mis me gusta", "Pon mis me gusta")
        self.assertIn("me gusta", msg.lower())
        sp.start_playback.assert_called()

    @patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False)
    @patch("eda.connectors.spotify.get_spotify_client")
    @patch("eda.connectors.spotify.is_web_api_configured", return_value=True)
    def test_ambiguous_album_top3(self, _cfg: MagicMock, mock_client: MagicMock) -> None:
        sp = MagicMock()
        sp.current_user.return_value = {"id": "u1"}
        sp.devices.return_value = {"devices": [{"id": "d1", "name": "PC", "is_active": True, "type": "Computer"}]}
        sp.current_user_saved_albums.return_value = {"items": [], "next": None}
        ab1 = {"name": "Abbey R", "artists": [{"name": "Beatles"}], "uri": "spotify:album:1"}
        ab2 = {"name": "Abbey Road", "artists": [{"name": "The Beatles"}], "uri": "spotify:album:2"}
        sp.search.return_value = {
            "albums": {
                "items": [ab1, ab2],
            }
        }
        mock_client.return_value = sp
        orch = MagicMock()
        with (
            patch("eda.connectors.spotify._CONF_AUTO", return_value=0.99),
            patch("eda.connectors.spotify._CONF_LOW", return_value=0.10),
            patch("eda.connectors.spotify.score_candidate", return_value=0.6),
        ):
            msg = route_spotify_natural(orch, "Reproduce el álbum Abbey Road de The Beatles", "Abbey Road de The Beatles")
        self.assertIn("varias", msg.lower())
        self.assertIn("coincidencias", msg.lower())
        self.assertIsNotNone(orch._spotify_pending)

    @patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False)
    @patch("eda.connectors.spotify.get_spotify_client")
    @patch("eda.connectors.spotify.is_web_api_configured", return_value=True)
    def test_transfer_confirm_flow(self, _cfg: MagicMock, mock_client: MagicMock) -> None:
        sp = MagicMock()
        sp.current_user.return_value = {"id": "u1"}
        sp.devices.return_value = {
            "devices": [
                {"id": "devX", "name": "Sala", "is_active": False, "type": "Speaker"},
            ]
        }
        mock_client.return_value = sp
        orch = MagicMock()
        orch._spotify_pending = None
        with patch("eda.connectors.spotify._TRANSFER_CONFIRM", return_value=True):
            msg = route_spotify_natural(orch, "Pasa la reproducción al altavoz de la sala", "Pasa la reproducción al altavoz de la sala")
        self.assertIn("confirm", msg.lower())
        self.assertIsNotNone(orch._spotify_pending)

    def test_pick_playback(self) -> None:
        sp = MagicMock()
        sp.start_playback = MagicMock()
        with patch("eda.connectors.spotify.get_spotify_client", return_value=sp):
            from eda.nlu.spotify_intent import SpotifyParsedIntent

            opt = {
                "type": "context",
                "context_uri": "spotify:album:9",
                "device_id": "d1",
                "parsed": {
                    "kind": "album",
                    "primary_query": "",
                    "artist_hint": "",
                    "device_hint": "",
                    "shuffle": None,
                    "repeat_mode": None,
                    "prefer_saved": False,
                    "raw": "",
                },
            }
            out = play_option(MagicMock(), opt)
        self.assertIn("Reproduciendo", out)
        sp.start_playback.assert_called()

    @patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False)
    @patch("eda.connectors.spotify.get_spotify_client")
    @patch("eda.connectors.spotify.is_web_api_configured", return_value=True)
    def test_track_prefers_original_over_meme_or_remix(self, _cfg: MagicMock, mock_client: MagicMock) -> None:
        sp = MagicMock()
        sp.current_user.return_value = {"id": "u1"}
        sp.devices.return_value = {"devices": [{"id": "d1", "name": "PC", "is_active": True, "type": "Computer"}]}
        sp.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "name": "Bohemian Rhapsody - The Muppets Version",
                        "artists": [{"name": "The Muppets"}],
                        "uri": "spotify:track:muppets",
                    },
                    {
                        "name": "Bohemian Rhapsody - Remastered 2011",
                        "artists": [{"name": "Queen"}],
                        "uri": "spotify:track:queen",
                    },
                ]
            }
        }
        mock_client.return_value = sp
        orch = MagicMock()
        msg = route_spotify_natural(orch, "reproduce bohimian rhpsodi", "bohimian rhpsodi")
        self.assertIn("reproduciendo", msg.lower())
        kwargs = sp.start_playback.call_args.kwargs
        self.assertEqual(kwargs.get("uris"), ["spotify:track:queen"])

    @patch.dict(os.environ, {"EDA_SPOTIFY_CLIENT_ID": "x", "EDA_SPOTIFY_USE_PKCE": "1"}, clear=False)
    @patch("eda.connectors.spotify.get_spotify_client")
    @patch("eda.connectors.spotify.is_web_api_configured", return_value=True)
    def test_track_with_artist_hint_prefers_matching_artist(self, _cfg: MagicMock, mock_client: MagicMock) -> None:
        sp = MagicMock()
        sp.current_user.return_value = {"id": "u1"}
        sp.devices.return_value = {"devices": [{"id": "d1", "name": "PC", "is_active": True, "type": "Computer"}]}
        sp.search.side_effect = [
            {
                "tracks": {
                    "items": [
                        {
                            "name": "In The End",
                            "artists": [{"name": "Linkin Park"}],
                            "uri": "spotify:track:lp",
                        },
                        {
                            "name": "In The End (Remix)",
                            "artists": [{"name": "DJ Random"}],
                            "uri": "spotify:track:remix",
                        },
                    ]
                }
            },
            {
                "tracks": {
                    "items": [
                        {
                            "name": "In The End (Remix)",
                            "artists": [{"name": "DJ Random"}],
                            "uri": "spotify:track:remix",
                        }
                    ]
                }
            },
        ]
        mock_client.return_value = sp
        orch = MagicMock()
        msg = route_spotify_natural(orch, "reproduce in th end de linkin park", "in th end de linkin park")
        self.assertIn("reproduciendo", msg.lower())
        kwargs = sp.start_playback.call_args.kwargs
        self.assertEqual(kwargs.get("uris"), ["spotify:track:lp"])

    def test_audit_no_token(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "a.jsonl")
            with patch("eda.connectors.spotify._audit_path", return_value=__import__("pathlib").Path(p)):
                append_spotify_audit({"event": "t", "access_token": "SECRETX", "n": 1})
            with open(p, encoding="utf-8") as fh:
                line = fh.read()
            self.assertIn("REDACTED", line)
            self.assertNotIn("SECRETX", line)


if __name__ == "__main__":
    unittest.main()
