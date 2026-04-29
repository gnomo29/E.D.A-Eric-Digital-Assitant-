from __future__ import annotations

import unittest

from eda.triggers import TriggerStore


class TriggerTests(unittest.TestCase):
    def test_set_active_all(self) -> None:
        store = TriggerStore()
        t1 = store.create_trigger(
            phrase="estudio intenso",
            match_type="exact",
            action_type="open_app",
            action_payload={"app": "notepad"},
            require_confirm=False,
        )
        t2 = store.create_trigger(
            phrase="pausa corta",
            match_type="exact",
            action_type="open_app",
            action_payload={"app": "calc"},
            require_confirm=False,
        )
        self.assertGreater(t1, 0)
        self.assertGreater(t2, 0)
        changed = store.set_active_all(False)
        self.assertGreaterEqual(changed, 2)
        rows = store.list_triggers(active_only=False)
        self.assertTrue(rows)
        self.assertTrue(all(not r["active"] for r in rows[:2]))

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

    def test_update_trigger(self) -> None:
        store = TriggerStore()
        tid = store.create_trigger(
            phrase="modo enfoque",
            match_type="exact",
            action_type="open_app",
            action_payload={"app": "notepad"},
            require_confirm=True,
        )
        ok = store.update_trigger(
            tid,
            phrase="modo foco",
            action_type="open_app",
            action_payload={"app": "code"},
            require_confirm=False,
            match_type="exact",
            fuzzy_threshold=80,
        )
        self.assertTrue(ok)
        row = store.get_trigger(tid)
        self.assertIsNotNone(row)
        self.assertEqual("modo foco", row["phrase"])
        self.assertEqual({"app": "code"}, row["action_payload"])
        self.assertFalse(row["require_confirm"])

    def test_log_and_read_last_run(self) -> None:
        store = TriggerStore()
        tid = store.create_trigger(
            phrase="ir al gym",
            match_type="exact",
            action_type="play_spotify",
            action_payload={"query": "gym"},
            require_confirm=True,
        )
        store.log_trigger_run(tid, status="ok", detail="ejecutado", source="auto")
        run_map = store.get_last_run_map()
        self.assertIn(tid, run_map)
        self.assertEqual("ok", run_map[tid]["status"])
        rows = store.list_trigger_runs(tid, limit=5)
        self.assertTrue(rows)
        self.assertEqual(tid, rows[0]["trigger_id"])


if __name__ == "__main__":
    unittest.main()
