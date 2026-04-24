import unittest
from datetime import datetime

from scheduler import ReminderScheduler, parse_reminder_request


class SchedulerReminderTests(unittest.TestCase):
    def test_parse_reminder_allows_apagar_in_future_message(self) -> None:
        """El recordatorio describe una acción futura; debe parsearse aunque diga 'apagar'."""
        req = parse_reminder_request("recuérdame pedirte apagar la música en un minuto")
        self.assertIsNotNone(req)
        self.assertEqual(req.mode, "relative")
        self.assertIn("apagar", (req.message or "").lower())

    def test_parse_relative_one_hour(self) -> None:
        now = datetime(2026, 4, 23, 14, 0, 0)
        req = parse_reminder_request("recuérdame en una hora de empezar mi proyecto", now=now)
        self.assertIsNotNone(req)
        self.assertEqual(req.mode, "relative")
        self.assertEqual(req.message, "empezar mi proyecto")
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 15, 0, 0))

    def test_parse_relative_20_min(self) -> None:
        now = datetime(2026, 4, 23, 10, 10, 0)
        req = parse_reminder_request("recuérdame en 20 min que revise correos", now=now)
        self.assertIsNotNone(req)
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 10, 30, 0))
        self.assertEqual(req.message, "revise correos")

    def test_parse_relative_one_minute_natural_phrase(self) -> None:
        now = datetime(2026, 4, 23, 10, 10, 0)
        req = parse_reminder_request("recuérdame en un minuto conectar batería", now=now)
        self.assertIsNotNone(req)
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 10, 11, 0))
        self.assertEqual(req.message, "conectar bateria")

    def test_parse_relative_seconds(self) -> None:
        now = datetime(2026, 4, 23, 10, 10, 0)
        req = parse_reminder_request("recuérdame en 90 segundos revisar horno", now=now)
        self.assertIsNotNone(req)
        # Se redondea a minutos (mínimo 1).
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 10, 12, 0))
        self.assertEqual(req.message, "revisar horno")

    def test_parse_relative_un_ratito(self) -> None:
        now = datetime(2026, 4, 23, 10, 10, 0)
        req = parse_reminder_request("recuérdame en un ratito tomar agua", now=now)
        self.assertIsNotNone(req)
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 10, 20, 0))
        self.assertEqual(req.message, "tomar agua")

    def test_parse_relative_half_hour_default_text(self) -> None:
        now = datetime(2026, 4, 23, 10, 10, 0)
        req = parse_reminder_request("recuérdame en media hora", now=now)
        self.assertIsNotNone(req)
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 10, 40, 0))
        self.assertIn("recordatorio", req.message)

    def test_parse_absolute_afternoon(self) -> None:
        now = datetime(2026, 4, 23, 11, 0, 0)
        req = parse_reminder_request("recuérdame a las 3 de la tarde de empezar mi proyecto", now=now)
        self.assertIsNotNone(req)
        self.assertEqual(req.mode, "absolute")
        self.assertEqual(req.remind_at, datetime(2026, 4, 23, 15, 0, 0))
        self.assertEqual(req.message, "empezar mi proyecto")

    def test_scheduler_list_and_cancel(self) -> None:
        scheduler = ReminderScheduler(on_due=lambda _payload: None)
        now = datetime(2026, 4, 23, 11, 0, 0)
        req = parse_reminder_request("recuérdame en una hora de probar", now=now)
        assert req is not None
        created = scheduler.add(req)
        pending = scheduler.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], created["id"])
        self.assertTrue(scheduler.cancel(created["id"]))
        self.assertEqual(scheduler.list_pending(), [])


if __name__ == "__main__":
    unittest.main()
