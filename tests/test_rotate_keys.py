from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eda.plugin_loader import PluginLoader
from eda.utils.security import generate_skill_keypair, sign_file
from tools.rotate_keys import run_rotation


class RotateKeysTests(unittest.TestCase):
    def _seed_repo(self, root: Path) -> None:
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

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            result = run_rotation(root, dry_run=True, force=False)
            self.assertEqual(result.get("status"), "ok")
            self.assertFalse((root / "config" / "keys" / "skills_private_new.pem").exists())
            self.assertFalse((root / "skills" / "signatures.json.temp").exists())

    def test_rotation_updates_signatures_and_loader_works(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._seed_repo(root)
            result = run_rotation(root, dry_run=False, force=True)
            self.assertEqual(result.get("status"), "ok")
            self.assertTrue((root / "config" / "keys" / "skills_private.old.pem").exists())
            self.assertTrue((root / "skills" / "signatures.old.json").exists())
            with patch("eda.plugin_loader.config.CONFIG_DIR", root / "config"):
                with patch("eda.plugin_loader.config.REVOCATIONS_FILE", root / "skills" / "revocations.json"):
                    loader = PluginLoader(plugins_dir=root / "skills")
                    loaded = loader.load_enabled()
            self.assertIn("example", loaded)


if __name__ == "__main__":
    unittest.main()

