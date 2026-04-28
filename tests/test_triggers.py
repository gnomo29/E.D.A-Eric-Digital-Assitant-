from __future__ import annotations

import unittest

from eda.triggers import TriggerStore


class TriggerTests(unittest.TestCase):
    def test_create_and_match_exact(self) -> None:
        store = TriggerStore()
        tid = store.create_trigger(
            phrase="ir al gym",
            match_type="exact",
            action_type="play_spotify",
            action_payload={"query": "gym"},
            require_confirm=True,
        )
        self.assertGreater(tid, 0)
        hit = store.match("ir al gym")
        self.assertIsNotNone(hit)
        self.assertEqual(tid, hit["trigger"]["id"])

    def test_match_fuzzy(self) -> None:
        store = TriggerStore()
        tid = store.create_trigger(
            phrase="ironman",
            match_type="fuzzy",
            action_type="play_spotify",
            action_payload={"query": "acdc"},
            require_confirm=True,
            fuzzy_threshold=70,
        )
        hit = store.match("ironnman")
        self.assertIsNotNone(hit)
        self.assertEqual(tid, hit["trigger"]["id"])


if __name__ == "__main__":
    unittest.main()
