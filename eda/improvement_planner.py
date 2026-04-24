"""Planificación de mejoras: escaneo local (código + skills) y contexto para autoaprendizaje."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Set

from . import config
from .logger import get_logger

if TYPE_CHECKING:
    from .web_solver import WebSolver

log = get_logger("improvement_planner")

_TOKEN_RE = re.compile(r"[a-záéíóúñ0-9]{2,}", re.IGNORECASE)


def _tokens(text: str) -> Set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def _score_overlap(haystack: str, tokens: Set[str]) -> int:
    blob = (haystack or "").lower()
    return sum(1 for t in tokens if t and t in blob)


class ImprovementPlanner:
    """Busca en el proyecto módulos y skills relevantes; opcionalmente pistas web."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or config.BASE_DIR).resolve()
        self.eda_dir = self.project_root / "eda"

    def scan_eda_python(self, query: str, max_hits: int = 10) -> List[Dict[str, Any]]:
        tokens = _tokens(query)
        if not tokens:
            return []

        hits: List[Dict[str, Any]] = []
        if not self.eda_dir.is_dir():
            return hits

        for path in sorted(self.eda_dir.glob("*.py")):
            name = path.name
            if name.startswith("__"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.debug("No leer %s: %s", path, exc)
                continue

            score = _score_overlap(text, tokens) * 2 + _score_overlap(name, tokens) * 3
            if score < 2:
                continue

            snippet = ""
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("def ") and _score_overlap(stripped, tokens) >= 1:
                    snippet = stripped[:200]
                    break
            if not snippet:
                for line in text.splitlines()[:40]:
                    if _score_overlap(line, tokens) >= 2:
                        snippet = line.strip()[:200]
                        break

            rel = f"eda/{name}"
            hits.append({"path": rel, "score": score, "snippet": snippet})

        hits.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
        return hits[:max_hits]

    def scan_cursor_skills(self, query: str, max_files: int = 24, max_hits: int = 6) -> List[Dict[str, Any]]:
        tokens = _tokens(query)
        cursor_dir = self.project_root / ".cursor"
        if not tokens or not cursor_dir.is_dir():
            return []

        found: List[Dict[str, Any]] = []
        count = 0
        for path in cursor_dir.rglob("SKILL.md"):
            count += 1
            if count > max_files:
                break
            try:
                head = path.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            rel = str(path.relative_to(self.project_root)).replace("\\", "/")
            score = _score_overlap(rel + "\n" + head, tokens)
            if score < 1:
                continue
            title_line = head.splitlines()[0].strip("# ")[:120] if head else rel
            found.append({"path": rel, "score": score, "title": title_line})

        found.sort(key=lambda x: int(x.get("score", 0)), reverse=True)
        return found[:max_hits]

    def build_plan(
        self,
        user_request: str,
        *,
        include_web: bool,
        web_solver: WebSolver | None,
    ) -> Dict[str, Any]:
        req = (user_request or "").strip()
        local = self.scan_eda_python(req)
        skills = self.scan_cursor_skills(req)
        web: List[Dict[str, str]] = []
        if include_web and web_solver is not None and req:
            try:
                web = web_solver.intelligent_search(req, max_results=4)[:4]
            except Exception as exc:
                log.warning("[PLAN] intelligent_search falló: %s", exc)

        actions: List[str] = []
        if local:
            actions.append(f"Reutilizar o extender lógica en `{local[0]['path']}` antes de crear código nuevo.")
        if skills:
            actions.append(f"Revisar skill del proyecto: `{skills[0]['path']}` como guía de implementación.")
        if web:
            actions.append("Cruzar con documentación / foros (resultados web ya listados en el plan).")
        if not actions:
            actions.append("Formular la petición con pasos concretos o enseñar una regla «Quiero que…».")

        return {
            "request": req,
            "local": local,
            "skills_md": skills,
            "web": web,
            "suggested_actions": actions,
        }

    def compact_context_for_llm(self, plan: Dict[str, Any], max_chars: int = 1800) -> str:
        """Bloque breve para inyectar en el prompt de autoaprendizaje."""
        parts: List[str] = []
        parts.append("=== Análisis local del proyecto (no ejecutar; solo contexto) ===")

        for item in plan.get("local", [])[:6]:
            if not isinstance(item, dict):
                continue
            line = f"- {item.get('path', '')} (relevancia {item.get('score', 0)}): {item.get('snippet', '')}"
            parts.append(line[:400])

        for item in plan.get("skills_md", [])[:4]:
            if not isinstance(item, dict):
                continue
            parts.append(f"- Skill: {item.get('path', '')} — {item.get('title', '')}"[:400])

        for i, item in enumerate(plan.get("web", [])[:3]):
            if not isinstance(item, dict):
                continue
            t = (item.get("title") or "").strip()[:100]
            s = (item.get("snippet") or "").strip()[:220]
            parts.append(f"- Web {i + 1}: {t} | {s}")

        text = "\n".join(parts).strip()
        return text[:max_chars]

    def format_plan_for_user(self, plan: Dict[str, Any]) -> str:
        """Texto legible para el chat (sin aplicar cambios al disco)."""
        lines: List[str] = []
        req = plan.get("request", "")
        lines.append(f"Plan de capacidad para: «{req}»\n")

        loc = plan.get("local") or []
        if loc:
            lines.append("**Módulos E.D.A. relacionados:**")
            for item in loc[:8]:
                if isinstance(item, dict):
                    sn = (item.get("snippet") or "").strip()
                    lines.append(f"  • `{item.get('path', '')}` — {sn}"[:280])
            lines.append("")

        sk = plan.get("skills_md") or []
        if sk:
            lines.append("**Skills en `.cursor` (referencia):**")
            for item in sk[:5]:
                if isinstance(item, dict):
                    lines.append(f"  • `{item.get('path', '')}` — {item.get('title', '')}"[:260])
            lines.append("")

        w = plan.get("web") or []
        if w:
            lines.append("**Pistas web (resumen):**")
            for item in w[:4]:
                if isinstance(item, dict):
                    u = (item.get("url") or "").strip()
                    lines.append(f"  • {(item.get('title') or '')[:120]} — {u}"[:300])
            lines.append("")

        lines.append("**Pasos sugeridos:**")
        for step in plan.get("suggested_actions", [])[:5]:
            lines.append(f"  – {step}")

        lines.append(
            "\nEsto no modifica archivos. Para aplicar código: active autoaprendizaje con la misma petición "
            "o use «Quiero que…» para reglas seguras."
        )
        return "\n".join(lines).strip()
