"""Sistema básico de plugins skills/*.py con manifest.json."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

from . import config
from .utils import safe_json_load
from .utils.security import load_signatures, verify_file_signature


class PluginLoader:
    def __init__(self, plugins_dir: Path | None = None) -> None:
        self.plugins_dir = plugins_dir or (config.PROJECT_ROOT / "skills")

    def discover(self) -> List[Dict[str, Any]]:
        manifest_path = self.plugins_dir / "manifest.json"
        if not self._is_signed(manifest_path):
            return []
        manifest = safe_json_load(manifest_path, {"plugins": []})
        plugins = manifest.get("plugins", [])
        return plugins if isinstance(plugins, list) else []

    def load_enabled(self) -> Dict[str, Any]:
        loaded: Dict[str, Any] = {}
        for item in self.discover():
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            file_name = str(item.get("file", "")).strip()
            plugin_name = str(item.get("name", "")).strip() or file_name
            if not file_name.endswith(".py"):
                continue
            plugin_path = self.plugins_dir / file_name
            if not plugin_path.exists():
                continue
            if not self._is_signed(plugin_path):
                continue
            spec = importlib.util.spec_from_file_location(f"eda_plugin_{plugin_name}", plugin_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            loaded[plugin_name] = module
        return loaded

    def _is_signed(self, path: Path) -> bool:
        signatures_path = self.plugins_dir / "signatures.json"
        public_key_path = config.CONFIG_DIR / "keys" / "skills_public.pem"
        signatures = load_signatures(signatures_path).get("files", {})
        signature = signatures.get(path.name) if isinstance(signatures, dict) else None
        if not signature or not public_key_path.exists():
            return False
        return verify_file_signature(path, str(signature), public_key_path)

