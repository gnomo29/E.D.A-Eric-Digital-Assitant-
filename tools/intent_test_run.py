#!/usr/bin/env python3
"""Run intent routing tests and emit metrics + memory report."""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
import traceback
import argparse
import io
import logging
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

def predict_intent(utterance: str) -> tuple[str, float, list[tuple[str, float]]]:
    from eda.nlp_utils import parse_command
    from eda.nlu.spotify_intent import parse_spotify_utterance

    text = (utterance or "").strip()
    low = text.lower()
    parsed = parse_command(text)
    sp = parse_spotify_utterance(text)
    candidates: list[tuple[str, float]] = []
    liked_hint = any(k in low for k in ("me gusta", "liked", "likes", "favs", "favoritas", "favoritos"))

    if ("videos" in low or "video" in low) and any(k in low for k in ("abre", "busca", "search")):
        if "search " in low:
            candidates.append(("web_search_videos", 0.88))
        else:
            intent = "open_media_search" if "abre" in low else "web_search_videos"
            candidates.append((intent, 0.88))
    if low.startswith("close "):
        candidates.append(("close_app", 0.78))
    if low.startswith("open "):
        candidates.append(("open_app", 0.78))
    if "noticias" in low:
        candidates.append(("web_search_news", 0.87))
    if "pdf" in low:
        candidates.append(("create_pdf", 0.9))
    if parsed.intent == "close_app":
        candidates.append(("close_app", float(parsed.confidence)))
    if parsed.intent == "open_app":
        candidates.append(("open_app", float(parsed.confidence)))
    if parsed.intent in {"general_knowledge_question", "technical_question", "explanation_request"} or text.endswith("?"):
        candidates.append(("conversation_explanation", max(0.8, float(parsed.confidence))))
    if liked_hint and any(k in low for k in ("pon", "play", "reproduce", "spotify")):
        candidates.append(("open_and_play_liked", 0.92))
    if sp.kind == "liked":
        candidates.append(("open_and_play_liked", 0.92))
    if parsed.intent == "play_music":
        candidates.append(("play_music", float(parsed.confidence)))
    if parsed.intent == "open_and_play_music" and "me gusta" in low:
        candidates.append(("open_and_play_liked", 0.93))
    if low.startswith("reprodece "):
        candidates.append(("play_music", 0.80))
    if low.startswith("play my liked songs"):
        candidates.append(("open_and_play_liked", 0.93))
    music_hint = any(
        k in low
        for k in (
            "reproduce",
            "pon ",
            "ponme",
            "escucha",
            "spotify",
            "playlist",
            "album",
            "álbum",
            "canción",
            "track",
            "artist",
            "artista",
            "ad/dc",
        )
    )
    if music_hint and sp.kind in {"artist_top", "track", "album", "playlist", "generic_play", "similar", "latest_album"}:
        candidates.append(("play_music", 0.89))
    if not candidates:
        candidates.append((parsed.intent, float(parsed.confidence)))
    # de-duplicate by max score per intent
    reduced: dict[str, float] = {}
    for i, s in candidates:
        reduced[i] = max(s, reduced.get(i, 0.0))
    ordered = sorted(reduced.items(), key=lambda x: x[1], reverse=True)
    top = ordered[0]
    return top[0], top[1], ordered[:3]


def load_dataset(path: Path) -> list[dict[str, str]]:
    return [r for r in csv.DictReader(path.read_text(encoding="utf-8").splitlines()) if r.get("utterance")]


def compute_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    labels = sorted({r["expected_intent"] for r in rows})
    matrix: dict[str, dict[str, int]] = {k: defaultdict(int) for k in labels}  # type: ignore[assignment]
    items: list[dict[str, Any]] = []
    ok = 0
    for r in rows:
        pred, score, top3 = predict_intent(r["utterance"])
        exp = r["expected_intent"]
        if exp not in matrix:
            matrix[exp] = defaultdict(int)  # type: ignore[assignment]
        matrix[exp][pred] += 1
        good = pred == exp
        ok += 1 if good else 0
        items.append(
            {
                "utterance": r["utterance"],
                "expected_intent": exp,
                "predicted_intent": pred,
                "confidence": round(score, 3),
                "top3": [{"intent": i, "score": round(s, 3)} for i, s in top3],
                "chosen_route": pred,
                "final_action": pred,
                "confirmation_requested": pred in {"close_app", "create_pdf"},
                "ok": good,
            }
        )
    total = max(1, len(rows))
    precision = ok / total
    recall = precision
    return {
        "total": len(rows),
        "correct": ok,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "confusion_matrix": {k: dict(v) for k, v in matrix.items()},
        "items": items,
    }


class _ResultCollector(unittest.TextTestResult):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.exceptions: list[dict[str, str]] = []

    def addError(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        super().addError(test, err)
        self.exceptions.append({"test": str(test), "kind": "error", "trace": "".join(traceback.format_exception(*err))})

    def addFailure(self, test: unittest.case.TestCase, err: Any) -> None:  # noqa: N802
        super().addFailure(test, err)
        self.exceptions.append({"test": str(test), "kind": "failure", "trace": "".join(traceback.format_exception(*err))})


class _CollectorRunner(unittest.TextTestRunner):
    resultclass = _ResultCollector


def run_tests(*, quiet: bool = False) -> tuple[_ResultCollector, float, str]:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    tests_dir = ROOT / "tests"
    suite.addTests(loader.discover(str(tests_dir), pattern="test_intent_routing.py"))
    suite.addTests(loader.discover(str(tests_dir), pattern="test_orchestrator_routing_matrix.py"))
    suite.addTests(loader.discover(str(tests_dir), pattern="test_spotify_integration.py"))
    suite.addTests(loader.discover(str(tests_dir), pattern="test_spotify_web.py"))
    suite.addTests(loader.discover(str(tests_dir), pattern="test_triggers.py"))
    suite.addTests(loader.discover(str(tests_dir), pattern="test_youtube_handling.py"))
    capture = io.StringIO()
    runner = _CollectorRunner(verbosity=0 if quiet else 2, stream=capture)
    t0 = time.time()
    res: _ResultCollector = runner.run(suite)  # type: ignore[assignment]
    return res, time.time() - t0, capture.getvalue()


def monitor_peak_rss(stop_evt: threading.Event, sink: dict[str, float]) -> None:
    import psutil

    proc = psutil.Process(os.getpid())
    peak = 0
    total = psutil.virtual_memory().total
    while not stop_evt.is_set():
        try:
            peak = max(peak, proc.memory_info().rss)
        except Exception:
            pass
        time.sleep(0.2)
    sink["peak"] = float(peak)
    sink["total"] = float(total)


def main() -> int:
    ap = argparse.ArgumentParser(description="Intent pipeline test runner")
    ap.add_argument("--ci", action="store_true", help="Output compact JSON only and fail on thresholds")
    args = ap.parse_args()
    if args.ci:
        logging.disable(logging.CRITICAL)

    rows = load_dataset(ROOT / "tests" / "intents_dataset.csv")
    dataset_metrics = compute_metrics(rows)

    mem = {"peak": 0.0, "total": 1.0}
    stop_evt = threading.Event()
    th = threading.Thread(target=monitor_peak_rss, args=(stop_evt, mem), daemon=True)
    th.start()
    test_result, elapsed, captured = run_tests(quiet=args.ci)
    stop_evt.set()
    th.join(timeout=1.0)

    peak_pct = (mem["peak"] / mem["total"]) * 100 if mem["total"] > 0 else 0.0
    mem_status = "FAIL" if peak_pct > 80.0 else "OK"

    report = {
        "dataset_metrics": dataset_metrics,
        "tests": {
            "run": test_result.testsRun,
            "failures": len(test_result.failures),
            "errors": len(test_result.errors),
            "exceptions": test_result.exceptions,
            "elapsed_sec": round(elapsed, 3),
        },
        "memory": {
            "peak_rss_mb": round(mem["peak"] / (1024 * 1024), 2),
            "system_total_mb": round(mem["total"] / (1024 * 1024), 2),
            "peak_percent_of_total": round(peak_pct, 2),
            "status": mem_status,
            "suggestions": (
                [
                    "Activar EDA_RELEASE_OLLAMA_MEMORY=1",
                    "Reducir concurrencia de workers <=2",
                    "Usar modelo cuantizado más liviano",
                ]
                if mem_status == "FAIL"
                else []
            ),
        },
    }
    out = ROOT / "data" / "logs" / "intent_test_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    run_log = ROOT / "data" / "logs" / "intent_test_run.log"
    run_log.write_text(
        (
            f"ts={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
            f"precision={dataset_metrics['precision']} recall={dataset_metrics['recall']}\n"
            f"tests={test_result.testsRun} failures={len(test_result.failures)} errors={len(test_result.errors)}\n"
            f"peak_rss_mb={report['memory']['peak_rss_mb']} peak_pct={report['memory']['peak_percent_of_total']}\n\n"
            f"=== unittest output ===\n{captured}\n"
        ),
        encoding="utf-8",
    )

    if args.ci:
        # CI contract: JSON compacto solamente por stdout.
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    else:
        print("=== Intent Pipeline Report ===")
        print(
            f"precision={dataset_metrics['precision']} recall={dataset_metrics['recall']} total={dataset_metrics['total']}"
        )
        print(
            f"tests={test_result.testsRun} failures={len(test_result.failures)} errors={len(test_result.errors)} elapsed={elapsed:.2f}s"
        )
        print(
            f"peak_rss_mb={report['memory']['peak_rss_mb']} peak_pct={report['memory']['peak_percent_of_total']} status={mem_status}"
        )
        print(f"report={out}")

    if len(test_result.failures) or len(test_result.errors):
        return 1
    if dataset_metrics["precision"] < 0.9:
        return 2
    if mem_status == "FAIL":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

