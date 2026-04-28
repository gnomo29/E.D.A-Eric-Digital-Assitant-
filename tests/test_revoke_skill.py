from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eda.plugin_loader import PluginLoader
from eda.utils.revocation import revoke_skill, unrevoke_skill
from eda.utils.security import generate_skill_keypair, sign_file


class RevokeSkillTests(unittest.TestCase):
    def _seed_signed_skill(self, root: Path) -> None:
        skills = root / "skills"
        keys = root / "config" / "keys"
        skills.mkdir(parents=True, exist_ok=True)
        keys.mkdir(parents=True, exist_ok=True)
        (skills / "example.py").write_text("x = 1\n", encoding="utf-8")
        (skills / "manifest.json").write_text(
            json.dumps({"plugins": [{"name": "example", "file": "example.py", "enabled": True}]}),
            encoding="utf-8",
        )
        prv = keys / "skills_private.pem"
        pub = keys / "skills_public.pem"
        generate_skill_keypair(prv, pub)
        sig = {
            "files": {
                "manifest.json": sign_file(skills / "manifest.json", prv),
                "example.py": sign_file(skills / "example.py", prv),
            }
        }
        (skills / "signatures.json").write_text(json.dumps(sig), encoding="utf-8")

    def test_loader_rejects_revoked_and_allows_unrevoked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_signed_skill(root)
            revocations = root / "skills" / "revocations.json"
            with patch("eda.plugin_loader.config.CONFIG_DIR", root / "config"):
                with patch("eda.plugin_loader.config.REVOCATIONS_FILE", revocations):
                    loader = PluginLoader(plugins_dir=root / "skills")
                    self.assertIn("example", loader.load_enabled())
                    revoke_skill("example.py", reason="audit", path=revocations)
                    self.assertNotIn("example", loader.load_enabled())
                    unrevoke_skill("example.py", path=revocations)
                    self.assertIn("example", loader.load_enabled())


if __name__ == "__main__":
    unittest.main()

