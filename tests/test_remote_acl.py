from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eda.security.remote_acl import RemoteACL


class RemoteACLTests(unittest.TestCase):
    def test_acl_levels_and_disabled_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            acl_path = Path(td) / "remote_acl.json"
            acl_path.write_text(
                json.dumps(
                    {
                        "default_level": "info",
                        "commands": [
                            {"pattern": "estado", "level": "info", "enabled": True},
                            {"pattern": "reproduce", "level": "safe", "enabled": True},
                            {"pattern": "borra", "level": "critical", "enabled": False},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            acl = RemoteACL(acl_path=acl_path)
            self.assertEqual(acl.classify("estado general").level, "info")
            self.assertEqual(acl.classify("reproduce jazz").level, "safe")
            blocked = acl.classify("borra archivo")
            self.assertFalse(blocked.allowed)
            self.assertEqual(blocked.reason, "command_disabled")


if __name__ == "__main__":
    unittest.main()

