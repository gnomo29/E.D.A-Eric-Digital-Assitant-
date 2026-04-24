import unittest

from eda import config
from eda.utils import build_http_session


class HttpSessionTests(unittest.TestCase):
    def test_build_http_session_sets_user_agent(self) -> None:
        session = build_http_session()
        self.assertEqual(session.headers.get("User-Agent"), config.USER_AGENT)
        self.assertIn("https://", session.adapters)
        self.assertIn("http://", session.adapters)


if __name__ == "__main__":
    unittest.main()
