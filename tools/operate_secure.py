"""Flujo operativo seguro: dry-run -> rotate -> smoke -> revoke -> rollback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda.plugin_loader import PluginLoader
from eda.utils import safe_json_load
from eda.utils.revocation import revoke_skill
from tools.rotate_keys import rollback_rotation, run_rotation

try:
    from eda.connectors.mobile import TelegramConnector
except Exception:
    TelegramConnector = None  # type: ignore[assignment]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operación segura de rotación/revocación con rollback automático")
    parser.add_argument("--dry-run", action="store_true", help="Simula todo sin modificar archivos.")
    parser.add_argument("--rotate-keys", action="store_true", help="Ejecuta rotación segura de llaves.")
    parser.add_argument("--smoke-loader", action="store_true", help="Valida carga de PluginLoader con firmas activas.")
    parser.add_argument("--revoke", default="", help="Revoca skill al final si smoke es exitoso.")
    parser.add_argument("--revoke-reason", default="operate_secure", help="Motivo de revocación.")
    parser.add_argument("--rollback-on-fail", action="store_true", help="Hace rollback automático en fallos críticos.")
    parser.add_argument("--yes", action="store_true", help="Modo no interactivo.")
    parser.add_argument("--telegram-smoke", action="store_true", help="Envía resumen por Telegram al finalizar.")
    parser.add_argument("--telegram-token", default="", help="Token Telegram opcional.")
    parser.add_argument("--telegram-chat", default="", help="Chat ID Telegram opcional.")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout global en segundos.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Salida detallada.")
    parser.add_argument("--force", action="store_true", help="Fuerza rotación ignorando residuos temporales.")
    parser.add_argument("--no-tests", action="store_true", help="Compat CI: flag aceptado (sin efecto en este script).")
    return parser.parse_args(argv)


def _obfuscate(value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        return ""
    if len(clean) <= 4:
        return "***"
    return f"{clean[:2]}****{clean[-2:]}"


def _append_audit(log_path: Path, payload: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _log(msg: str, *, verbose: bool) -> None:
    if verbose:
        print(msg)


def _backup_targets(root: Path) -> dict[str, Path]:
    return {
        "private": root / "config" / "keys" / "skills_private.pem",
        "public": root / "config" / "keys" / "skills_public.pem",
        "signatures": root / "skills" / "signatures.json",
        "revocations": root / "skills" / "revocations.json",
    }


def create_backup(root: Path, *, dry_run: bool, verbose: bool) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = root / "data" / "backups" / f"operate_{stamp}"
    if dry_run:
        _log(f"[dry-run] Backup planeado: {backup_dir}", verbose=verbose)
        return backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name, target in _backup_targets(root).items():
        if target.exists():
            shutil.copy2(target, backup_dir / target.name)
            _log(f"Backup {name}: {target.name}", verbose=verbose)
    return backup_dir


def restore_backup(root: Path, backup_dir: Path, *, verbose: bool) -> dict[str, str]:
    mapping = _backup_targets(root)
    for _, target in mapping.items():
        src = backup_dir / target.name
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            _log(f"Restaurado: {target}", verbose=verbose)
    return {"status": "ok", "message": f"Restore desde backup {backup_dir}"}


def smoke_loader(root: Path) -> dict[str, Any]:
    skills_dir = root / "skills"
    manifest = safe_json_load(skills_dir / "manifest.json", {"plugins": []})
    plugins = manifest.get("plugins", [])
    expected: set[str] = set()
    if isinstance(plugins, list):
        for item in plugins:
            if not isinstance(item, dict):
                continue
            if not item.get("enabled", True):
                continue
            name = str(item.get("name", "")).strip()
            file_name = str(item.get("file", "")).strip()
            if file_name.endswith(".py") and name:
                expected.add(name)
    loader = PluginLoader(plugins_dir=skills_dir)
    loaded = loader.load_enabled()
    loaded_names = set(loaded.keys())
    missing = sorted(expected - loaded_names)
    return {"ok": len(missing) == 0, "missing": missing, "loaded": sorted(loaded_names)}


def send_telegram_summary(args: argparse.Namespace, summary: str, *, dry_run: bool, verbose: bool) -> None:
    if not args.telegram_smoke:
        return
    token = (args.telegram_token or "").strip() or os.getenv("TELEGRAM_TOKEN", "").strip()
    chat = (args.telegram_chat or "").strip() or os.getenv("TELEGRAM_CHATID", "").strip()
    if verbose and token:
        print(f"telegram_token={_obfuscate(token)} chat={_obfuscate(chat)}")
    if dry_run:
        _log("[dry-run] Resumen Telegram omitido.", verbose=verbose)
        return
    if TelegramConnector is None:
        raise RuntimeError("TelegramConnector no disponible.")
    if token and chat:
        connector = TelegramConnector()
        connector.save_opt_in(token=token, telegram_chat_id=chat)
    else:
        connector = TelegramConnector()
    connector.enviar_mensaje(summary[:3000])


def run_operate_secure(args: argparse.Namespace, *, root: Path | None = None) -> int:
    base = root or ROOT
    started = time.monotonic()
    user = os.getenv("USERNAME") or os.getenv("USER") or "unknown"
    audit_file = base / "logs" / "operate_secure_audit.jsonl"
    warnings: list[str] = []
    backup_dir: Path | None = None
    rollback_done = False

    def step(name: str, fn, *, critical: bool = False) -> dict[str, Any]:
        nonlocal rollback_done
        if (time.monotonic() - started) > args.timeout:
            raise TimeoutError(f"Timeout global alcanzado ({args.timeout}s)")
        t0 = time.monotonic()
        outcome = "ok"
        detail = ""
        try:
            result = fn()
            if isinstance(result, dict) and result.get("status") == "error":
                raise RuntimeError(str(result.get("message", "error")))
            return result if isinstance(result, dict) else {"status": "ok"}
        except Exception as exc:
            outcome = "error"
            detail = str(exc)
            if critical:
                if args.rollback_on_fail and not args.dry_run:
                    try:
                        rollback_rotation(base)
                        if backup_dir is not None:
                            restore_backup(base, backup_dir, verbose=args.verbose)
                        rollback_done = True
                    except Exception as rb_exc:
                        _append_audit(
                            audit_file,
                            {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "step": f"{name}_rollback",
                                "outcome": "error",
                                "detail": str(rb_exc),
                                "elapsed_seconds": round(time.monotonic() - t0, 3),
                                "user": user,
                            },
                            dry_run=args.dry_run,
                        )
                        raise RuntimeError(f"{detail} | rollback_failed: {rb_exc}") from exc
                raise
            warnings.append(f"{name}: {detail}")
            return {"status": "warning", "message": detail}
        finally:
            _append_audit(
                audit_file,
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "step": name,
                    "outcome": outcome,
                    "detail": detail[:500],
                    "elapsed_seconds": round(time.monotonic() - t0, 3),
                    "user": user,
                    "telegram_token": _obfuscate((args.telegram_token or "").strip()),
                    "telegram_chat": _obfuscate((args.telegram_chat or "").strip()),
                },
                dry_run=args.dry_run,
            )

    try:
        backup_box: dict[str, Any] = {}
        def _do_backup() -> dict[str, Any]:
            backup_box["path"] = create_backup(base, dry_run=args.dry_run, verbose=args.verbose)
            return {"status": "ok", "path": str(backup_box["path"])}
        step("backup", _do_backup, critical=True)
        backup_dir = backup_box.get("path")
        if args.dry_run:
            print("Dry-run: pasos planeados -> backup, rotate(optional), smoke(optional), revoke(optional), telegram(optional).")
            return 0

        if args.rotate_keys:
            step("rotate_keys", lambda: run_rotation(base, dry_run=False, force=args.force), critical=True)
        if args.smoke_loader:
            def _smoke_checked() -> dict[str, Any]:
                data = smoke_loader(base)
                if not data.get("ok", False):
                    raise RuntimeError(f"Smoke loader falló. Missing={data.get('missing', [])}")
                return data
            step("smoke_loader", _smoke_checked, critical=True)
        if args.revoke:
            step(
                "revoke_skill",
                lambda: {"status": "ok" if revoke_skill(args.revoke, reason=args.revoke_reason) else "error", "message": "revoke_failed"},
                critical=False,
            )

        status_label = "OK" if not warnings else "WARN"
        summary = f"[operate_secure] {status_label} backup={backup_dir}"
        step("telegram_summary", lambda: send_telegram_summary(args, summary, dry_run=args.dry_run, verbose=args.verbose), critical=False)
        return 0 if not warnings else 1
    except Exception as exc:
        fail_summary = f"[operate_secure] FAIL backup={backup_dir} reason={str(exc)[:180]}"
        try:
            send_telegram_summary(args, fail_summary, dry_run=args.dry_run, verbose=args.verbose)
        except Exception:
            pass
        if "rollback_failed" in str(exc):
            return 3
        return 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_operate_secure(args)


if __name__ == "__main__":
    raise SystemExit(main())

