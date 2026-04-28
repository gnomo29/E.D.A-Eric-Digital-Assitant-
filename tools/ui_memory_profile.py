#!/usr/bin/env python3
"""Benchmark de RSS (pico) para la UI: arranca Tk, simula mensajes/acciones mock, muestrea psutil."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import psutil

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Medir pico RSS de ui_main (Tk + cola UI).")
    p.add_argument("--duration", type=float, default=60.0, help="Segundos de muestreo tras la carga inicial.")
    p.add_argument("--backend", choices=["tk"], default="tk", help="Solo Tk está soportado para perfil estable en CI.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    import ui_main

    mock_agent = MagicMock()
    mock_agent.try_handle.return_value = (True, "[mock] acción simulada")

    app = ui_main.build_app(metrics_interval_ms=2000, prefer=args.backend)
    app.action_agent = mock_agent

    try:
        app.withdraw()
    except Exception:
        pass

    stop = threading.Event()

    def _pump() -> None:
        while not stop.is_set():
            try:
                app.pump_ui(max_items=80)
            except Exception:
                pass
            time.sleep(0.04)

    pump_th = threading.Thread(target=_pump, daemon=True)
    pump_th.start()

    for i in range(10):
        app.submit_command(f"mensaje simulado {i}", display_user=f"mensaje simulado {i}")
    for i in range(5):
        app.submit_command("abre notepad", display_user=f"acción mock {i}")

    proc = psutil.Process()
    peak = proc.memory_info().rss
    t_end = time.time() + float(args.duration)
    while time.time() < t_end:
        peak = max(peak, proc.memory_info().rss)
        try:
            app.update_idletasks()
            app.update()
        except Exception:
            pass
        time.sleep(0.2)

    stop.set()

    mb = peak / (1024**2)
    lines = [
        f"duration_s={args.duration}",
        f"peak_rss_bytes={peak}",
        f"peak_rss_mb={mb:.2f}",
        f"backend={args.backend}",
        "load=10_messages_plus_5_mock_actions",
    ]
    report_text = "\n".join(lines) + "\n"

    out_dir = ROOT / "tools" / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "ui_peak_report.txt"
    out_file.write_text(report_text, encoding="utf-8")
    print(report_text, end="")
    app.on_close()
    try:
        app.destroy()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
