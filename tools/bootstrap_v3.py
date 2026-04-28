"""Bootstrap operativo v3.0 para E.D.A con modo CLI."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from eda import config
from eda.plugin_loader import PluginLoader
from eda.utils.security import load_signatures, verify_file_signature


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap v3 de operaciones E.D.A.")
    parser.add_argument("--only-sign", action="store_true", help="Solo firmar skills (con backup), sin validación/tests/smoke.")
    parser.add_argument("--no-tests", action="store_true", help="Ejecutar todo excepto la suite de tests.")
    parser.add_argument("--telegram-smoke", action="store_true", help="Forzar smoke test de Telegram.")
    parser.add_argument("--telegram-token", default="", help="Token Telegram para smoke test (opcional).")
    parser.add_argument("--telegram-chat", default="", help="Chat ID Telegram para smoke test (opcional).")
    parser.add_argument("--skip-logs", action="store_true", help="Omitir rotación/compresión de logs.")
    parser.add_argument("--dry-run", action="store_true", help="Simular pasos sin modificar archivos.")
    parser.add_argument("--yes", action="store_true", help="Modo no interactivo para CI.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Salida detallada.")
    return parser.parse_args(argv)


def _print_step(title: str) -> None:
    print(f"\n==> {title}")


def _log(msg: str, *, verbose: bool = True, enabled: bool = True) -> None:
    if enabled and verbose:
        print(msg)


def _rotate_audit_if_needed(audit_file: Path, max_bytes: int = 1_000_000) -> None:
    if not audit_file.exists():
        return
    if audit_file.stat().st_size < max_bytes:
        return
    rotated = audit_file.with_suffix(audit_file.suffix + ".1")
    rotated.unlink(missing_ok=True)
    audit_file.replace(rotated)


def _append_audit(
    root: Path,
    *,
    action: str,
    mode: str,
    outcome: str,
    dry_run: bool,
    detail: str = "",
) -> None:
    """Escribe una línea JSON en logs/bootstrap_actions.log."""
    if dry_run:
        # En dry-run no escribimos auditoría para no modificar archivos.
        return
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    audit_file = logs_dir / "bootstrap_actions.log"
    _rotate_audit_if_needed(audit_file)
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "mode": mode,
        "outcome": outcome,
    }
    if detail:
        payload["detail"] = detail[:500]
    with audit_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def backup_signatures(root: Path, *, dry_run: bool, verbose: bool) -> None:
    _print_step("Backup de firmas")
    skills_dir = root / "skills"
    signatures = skills_dir / "signatures.json"
    if not signatures.exists():
        print("No existe signatures.json todavía; se generará en el firmado.")
        return
    backup_dir = root / "data" / "backups" / "signatures"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / f"signatures_{stamp}.json"
    if dry_run:
        print(f"[dry-run] Haría backup: {signatures} -> {dst}")
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(signatures, dst)
    _log(f"Backup creado: {dst}", enabled=verbose)


def sign_all_skills(root: Path, *, dry_run: bool, verbose: bool) -> None:
    _print_step("Firmado de skills")
    cmd = [sys.executable, str(root / "tools" / "sign_skill.py")]
    if dry_run:
        print(f"[dry-run] Ejecutaría: {' '.join(cmd)}")
        return
    _log(f"Ejecutando firmado: {' '.join(cmd)}", enabled=verbose)
    subprocess.run(cmd, check=True)


def validate_integrity(root: Path, *, dry_run: bool, verbose: bool) -> None:
    _print_step("Validación de integridad")
    if dry_run:
        print("[dry-run] Omito validación real de integridad.")
        return
    loader = PluginLoader(plugins_dir=root / "skills")
    loaded = loader.load_enabled()
    if not loaded:
        raise RuntimeError("No se cargó ninguna skill firmada. Revisa llaves/firmas.")
    _log(f"Skills válidas cargadas: {', '.join(sorted(loaded.keys())[:8])}", enabled=verbose)

    signatures_path = root / "skills" / "signatures.json"
    signatures = load_signatures(signatures_path).get("files", {})
    if not isinstance(signatures, dict):
        raise RuntimeError("Formato de signatures.json inválido.")
    sample_name = next((n for n in signatures.keys() if n.endswith(".py")), "")
    if not sample_name:
        raise RuntimeError("No encontré firma de skill .py para prueba.")
    sample_path = root / "skills" / sample_name
    content = sample_path.read_text(encoding="utf-8")
    tampered_path = root / "temp" / f"{sample_name}.tampered"
    tampered_path.parent.mkdir(parents=True, exist_ok=True)
    tampered_path.write_text(content + "\n# tamper-check\n", encoding="utf-8")
    public_key = root / "config" / "keys" / "skills_public.pem"
    is_valid = verify_file_signature(tampered_path, str(signatures[sample_name]), public_key)
    tampered_path.unlink(missing_ok=True)
    if is_valid:
        raise RuntimeError("La validación anti-manipulación falló: archivo alterado fue aceptado.")
    print("Validación OK: archivos alterados son rechazados.")


def rotate_and_compress_logs(root: Path, *, dry_run: bool, verbose: bool) -> None:
    _print_step("Rotación/compresión de logs")
    candidate_dirs = [root / "logs", config.LOGS_DIR]
    compressed = 0
    for log_dir in candidate_dirs:
        if not log_dir.exists():
            continue
        files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[5:]:
            gz = old.with_suffix(old.suffix + ".gz")
            if dry_run:
                _log(f"[dry-run] Comprimiría {old} -> {gz}", enabled=verbose)
                continue
            with old.open("rb") as src, gzip.open(gz, "wb") as dst:
                shutil.copyfileobj(src, dst)
            old.unlink(missing_ok=True)
            compressed += 1
    print(f"Logs comprimidos: {compressed}")


def _obfuscate_secret(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) <= 4:
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:6]
        return f"***{digest}"
    return f"{cleaned[:2]}****{cleaned[-2:]}"


def resolve_telegram_credentials(args: argparse.Namespace) -> tuple[str, str]:
    token_arg = (args.telegram_token or "").strip()
    chat_arg = (args.telegram_chat or "").strip()
    if args.telegram_smoke and not token_arg and not chat_arg:
        # En smoke forzado, no usar env implícitamente para mantener comportamiento explícito en CI/tests.
        return "", ""
    token = token_arg or os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_id = chat_arg or os.getenv("TELEGRAM_CHATID", "").strip()
    return token, chat_id


def telegram_smoke_test(
    *,
    force: bool,
    token: str,
    chat_id: str,
    dry_run: bool,
    verbose: bool,
) -> None:
    _print_step("Smoke test Telegram (opcional)")
    if not force and (not token or not chat_id):
        print("Variables TELEGRAM_TOKEN/TELEGRAM_CHATID no definidas; se omite smoke test.")
        return
    if not token or not chat_id:
        raise ValueError("Faltan credenciales Telegram: usa --telegram-token/--telegram-chat o TELEGRAM_*.")
    if verbose:
        print(f"Telegram token(obfuscated)={_obfuscate_secret(token)} chat={chat_id}")
    if dry_run:
        print("[dry-run] Enviaría mensaje: 'E.D.A. v3.0 Online'")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": "E.D.A. v3.0 Online"}
        response = requests.post(url, json=payload, timeout=8)
        if response.status_code >= 400:
            print(f"Telegram smoke test falló: HTTP {response.status_code}")
            return
        print("Telegram smoke test OK.")
    except Exception as exc:
        print(f"Telegram smoke test con error (no bloqueante): {exc}")


def run_tests(*, dry_run: bool, verbose: bool) -> None:
    _print_step("Ejecución de tests")
    cmd = [sys.executable, "-m", "unittest", "discover"]
    if dry_run:
        print(f"[dry-run] Ejecutaría: {' '.join(cmd)}")
        return
    _log(f"Corriendo tests: {' '.join(cmd)}", enabled=verbose)
    subprocess.run(cmd, check=True)


def run_bootstrap(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    mode = "yes" if args.yes else "interactive"
    print(f"Modo CI/non-interactive (--yes): {'activo' if args.yes else 'inactivo'}")
    if args.yes:
        print("modo CI confirmado")
        _append_audit(root, action="bootstrap_start", mode=mode, outcome="ok", dry_run=args.dry_run, detail="modo CI confirmado")

    try:
        backup_signatures(root, dry_run=args.dry_run, verbose=args.verbose)
        _append_audit(root, action="backup_signatures", mode=mode, outcome="ok", dry_run=args.dry_run)
        sign_all_skills(root, dry_run=args.dry_run, verbose=args.verbose)
        _append_audit(root, action="sign_all_skills", mode=mode, outcome="ok", dry_run=args.dry_run)
    except Exception as exc:
        failures.append(f"signing: {exc}")
        _append_audit(root, action="signing", mode=mode, outcome="error", dry_run=args.dry_run, detail=str(exc))

    if not args.only_sign:
        try:
            validate_integrity(root, dry_run=args.dry_run, verbose=args.verbose)
            _append_audit(root, action="validate_integrity", mode=mode, outcome="ok", dry_run=args.dry_run)
        except Exception as exc:
            failures.append(f"validate_integrity: {exc}")
            _append_audit(root, action="validate_integrity", mode=mode, outcome="error", dry_run=args.dry_run, detail=str(exc))

        if not args.skip_logs:
            try:
                rotate_and_compress_logs(root, dry_run=args.dry_run, verbose=args.verbose)
                _append_audit(root, action="rotate_logs", mode=mode, outcome="ok", dry_run=args.dry_run)
            except Exception as exc:
                failures.append(f"rotate_logs: {exc}")
                _append_audit(root, action="rotate_logs", mode=mode, outcome="error", dry_run=args.dry_run, detail=str(exc))
        else:
            _print_step("Rotación/compresión de logs")
            print("Paso omitido por --skip-logs.")
            _append_audit(root, action="rotate_logs", mode=mode, outcome="skipped", dry_run=args.dry_run, detail="--skip-logs")

        token, chat_id = resolve_telegram_credentials(args)
        try:
            telegram_smoke_test(
                force=args.telegram_smoke,
                token=token,
                chat_id=chat_id,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            _append_audit(root, action="telegram_smoke_test", mode=mode, outcome="ok", dry_run=args.dry_run)
        except Exception as exc:
            failures.append(f"telegram_smoke_test: {exc}")
            _append_audit(root, action="telegram_smoke_test", mode=mode, outcome="error", dry_run=args.dry_run, detail=str(exc))

        if not args.no_tests:
            try:
                run_tests(dry_run=args.dry_run, verbose=args.verbose)
                _append_audit(root, action="run_tests", mode=mode, outcome="ok", dry_run=args.dry_run)
            except Exception as exc:
                failures.append(f"run_tests: {exc}")
                _append_audit(root, action="run_tests", mode=mode, outcome="error", dry_run=args.dry_run, detail=str(exc))
        else:
            _print_step("Ejecución de tests")
            print("Paso omitido por --no-tests.")
            _append_audit(root, action="run_tests", mode=mode, outcome="skipped", dry_run=args.dry_run, detail="--no-tests")

    print("\n==> Resumen bootstrap v3")
    if failures:
        print("Se detectaron incidencias:")
        for item in failures:
            print(f" - {item}")
        return 1
    print("Bootstrap completado correctamente.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    return run_bootstrap(args)


if __name__ == "__main__":
    raise SystemExit(main())

