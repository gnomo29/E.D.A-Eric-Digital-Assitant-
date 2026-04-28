"""Escaneo simple de archivos potencialmente obsoletos."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SAFE_RUNTIME_DIRS = [
    ROOT / "data" / "logs",
    ROOT / "temp",
    ROOT / "__pycache__",
]
IGNORE_DIR_NAMES = {".git", ".cursor", ".vscode", ".idea", "venv312", ".venv", "__pycache__"}


def _old_files_report() -> list[str]:
    candidates: list[str] = []
    for folder in SAFE_RUNTIME_DIRS:
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                candidates.append(str(path.relative_to(ROOT)))
    return candidates


def _empty_dirs_report() -> list[str]:
    out: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_dir():
            continue
        if any(part in IGNORE_DIR_NAMES for part in path.parts):
            continue
        if not any(path.iterdir()):
            out.append(str(path.relative_to(ROOT)))
    return out


def main() -> None:
    report = ROOT / "docs" / "CLEANUP_CANDIDATES.md"
    old_files = _old_files_report()
    empty_dirs = _empty_dirs_report()

    lines = [
        "# Cleanup Candidates",
        "",
        "Estos elementos son candidatos seguros para limpieza manual.",
        "",
        "## Runtime files (seguros de borrar si no se necesitan)",
    ]
    if old_files:
        lines.extend([f"- `{item}`" for item in old_files])
    else:
        lines.append("- No detectados.")

    lines.extend(
        [
            "",
            "## Empty directories (revisar antes de borrar)",
        ]
    )
    if empty_dirs:
        lines.extend([f"- `{item}`" for item in empty_dirs])
    else:
        lines.append("- No detectados.")

    lines.extend(
        [
            "",
            "## Reglas rápidas",
            "- `data/logs`, `data/temp/`, `__pycache__/` son seguros de limpiar.",
            "- No borrar `src/`, `docs/`, `tests/`, `scripts/` ni `data/memory/*.example.json`.",
        ]
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Reporte generado en: {report}")


if __name__ == "__main__":
    main()
