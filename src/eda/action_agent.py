"""Agente de acción ligero: aprendizaje general y ejecución dinámica."""

from __future__ import annotations

import gc
import json
import os
import re
import subprocess
import sys
import webbrowser
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote_plus

from .actions import ActionController
from . import config
from . import web_execution_gate
from .logger import get_logger
from .mouse_keyboard import MouseKeyboardController
from .system_observer import SystemObserver
from .task_membership import ExecutionLog, LearnedTask, TaskMembershipStore
from .utils.security import redact_sensitive_data, sanitize_app_target, validate_shell_command

log = get_logger("action_agent")


class ActionAgent:
    """Sistema general de aprendizaje/ejecución de tareas, sin catálogo cerrado."""

    LEARN_REGEX = re.compile(r"^\s*aprende tarea\s*:\s*(.+)$", flags=re.IGNORECASE)
    RUN_COMMAND_REGEX = re.compile(r"^\s*(?:ejecuta|corre)\s+comando\s*:\s*(.+)$", flags=re.IGNORECASE)
    TYPE_REGEX = re.compile(r"^\s*(?:escribe|teclea)\s*:\s*(.+)$", flags=re.IGNORECASE)
    MOVE_FILE_REGEX = re.compile(r"^\s*mueve archivo\s*:\s*(.+?)\s*->\s*(.+)\s*$", flags=re.IGNORECASE)
    OBSERVE_REGEX = re.compile(r"^\s*observar sistema(?:\s*:\s*(.+))?\s*$", flags=re.IGNORECASE)
    OPEN_ANY_REGEX = re.compile(r"^\s*(?:abre|inicia|lanza)\s+(.+)$", flags=re.IGNORECASE)
    COMPOUND_SPLIT_REGEX = re.compile(r"\s*(?:y luego|luego|después|despues|y)\s*", flags=re.IGNORECASE)
    URL_LIKE_REGEX = re.compile(r"^(?:https?://|www\.)", flags=re.IGNORECASE)
    DOMAIN_LIKE_REGEX = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", flags=re.IGNORECASE)
    CONDITIONAL_REGEX = re.compile(r"^\s*si\s+(.+?)\s+entonces\s+(.+)$", flags=re.IGNORECASE)
    ALLOWED_SHELL_COMMANDS = {
        "dir",
        "echo",
        "cd",
        "type",
        "copy",
        "move",
        "mkdir",
        "python",
        "pip",
        "where",
        "tasklist",
        "ipconfig",
    }

    def __init__(
        self,
        actions: ActionController,
        mouse_keyboard: MouseKeyboardController,
        task_store: TaskMembershipStore | None = None,
        observer: SystemObserver | None = None,
        generated_scripts_dir: Path | None = None,
    ) -> None:
        self.actions = actions
        self.mouse_keyboard = mouse_keyboard
        self.tasks = task_store or TaskMembershipStore()
        self.observer = observer or SystemObserver()
        self.generated_scripts_dir = generated_scripts_dir or (Path(__file__).resolve().parent.parent / "scripts" / "generated")
        self.generated_scripts_dir.mkdir(parents=True, exist_ok=True)
        self.command_audit_file = config.LOGS_DIR / "command_audit.jsonl"
        self.command_audit_file.parent.mkdir(parents=True, exist_ok=True)

    def try_handle(self, text: str) -> Tuple[bool, str]:
        clean = (text or "").strip()
        if not clean:
            return False, ""
        low = clean.lower()

        # No secuestrar conversación natural ni peticiones de música: lo resuelve el orquestador.
        if clean.endswith("?") or any(k in low for k in ("qué es", "que es", "explícame", "explicame", "por qué", "por que")):
            return False, ""
        if any(low.startswith(s) for s in ("reproduce ", "pon ", "ponme ", "escucha ", "play ")):
            return False, ""

        if web_execution_gate.text_disarms_gate(clean):
            web_execution_gate.disarm()
            return True, "Listo, se desbloquearon las acciones locales (comandos, mover archivos, teclear, etc.)."

        if web_execution_gate.is_armed():
            if self.LEARN_REGEX.match(clean) or self.RUN_COMMAND_REGEX.match(clean) or self.MOVE_FILE_REGEX.match(
                clean
            ) or self.TYPE_REGEX.match(clean):
                return True, (
                    "Por seguridad no ejecuto comandos de sistema ni rutas sensibles justo después de una síntesis "
                    "basada en internet. Decí «liberar acciones locales» cuando quieras permitirlo, "
                    "o usa la aprobación explícita en la interfaz Obsidian."
                )

        # 1) Reutilizar habilidades exactas aprendidas.
        task = self.tasks.get_task_by_trigger(clean)
        if task:
            answer, success, error = self._run_task(task)
            self.tasks.mark_used(task.trigger)
            self.tasks.log_execution(
                ExecutionLog(
                    task_trigger=task.trigger,
                    intent="learned_task",
                    parameters={"task_name": task.name},
                    result=answer,
                    success=success,
                    error=error,
                    context="exact_match",
                )
            )
            return True, answer

        # 2) Reutilizar habilidades generalizadas por patrón.
        generalized = self.tasks.find_generalized_skill(clean)
        if generalized:
            handled, answer = self._run_generalized_template(clean, generalized)
            if handled:
                return True, answer

        # 3) Aprendizaje manual explícito.
        learn_match = self.LEARN_REGEX.match(clean)
        if learn_match:
            ok, message = self._learn_from_inline(learn_match.group(1))
            return True, message if ok else f"No pude aprender esa tarea: {message}"

        # 4) Resolver tarea nueva dinámicamente: interpretar -> descomponer -> ejecutar -> guardar.
        planned_steps = self._decompose_task(clean)
        if not planned_steps:
            return False, ""

        if web_execution_gate.is_armed():
            risky_tools = frozenset({"command", "move_file", "type"})
            for step in planned_steps:
                if str(step.get("tool") or "") in risky_tools:
                    return True, (
                        "Hay pasos que mueven archivos o ejecutan comandos; bloqueados tras investigación web "
                        "hasta que escribas «liberar acciones locales»."
                    )

        answer, success, error = self._execute_dynamic_steps(clean, planned_steps)
        self._persist_learned_execution(clean, planned_steps, answer, success, error)
        return True, answer

    def _decompose_task(self, text: str) -> List[Dict[str, Any]]:
        """Descompone un pedido en plan estructurado con precondiciones básicas."""
        conditional = self.CONDITIONAL_REGEX.match(text)
        if conditional:
            cond = conditional.group(1).strip()
            consequence = conditional.group(2).strip()
            consequence_step = self._infer_single_step(consequence)
            if consequence_step:
                consequence_step["preconditions"] = [cond]
                consequence_step["dependencies"] = []
                return [consequence_step]

        pieces = [p.strip(" ,.;") for p in self.COMPOUND_SPLIT_REGEX.split(text) if p.strip(" ,.;")]
        if not pieces:
            pieces = [text]
        steps: List[Dict[str, Any]] = []
        for i, part in enumerate(pieces[:8]):
            parsed = self._infer_single_step(part)
            if parsed:
                parsed.setdefault("preconditions", [])
                parsed.setdefault("dependencies", [])
                if i > 0:
                    parsed["dependencies"] = [i - 1]
                steps.append(parsed)
        return steps

    def _infer_single_step(self, text: str) -> Dict[str, Any] | None:
        lower = text.lower().strip()

        run_cmd = self.RUN_COMMAND_REGEX.match(text)
        if run_cmd:
            return {"tool": "command", "value": run_cmd.group(1), "intent": "run_command"}

        type_cmd = self.TYPE_REGEX.match(text)
        if type_cmd:
            return {"tool": "type", "value": type_cmd.group(1), "intent": "type_text"}

        move_cmd = self.MOVE_FILE_REGEX.match(text)
        if move_cmd:
            return {"tool": "move_file", "value": {"src": move_cmd.group(1), "dst": move_cmd.group(2)}, "intent": "move_file"}

        obs_cmd = self.OBSERVE_REGEX.match(text)
        if obs_cmd:
            return {"tool": "observe", "value": obs_cmd.group(1) or "", "intent": "observe"}

        open_cmd = self.OPEN_ANY_REGEX.match(text)
        if open_cmd:
            target = open_cmd.group(1).strip()
            return {"tool": "open_dynamic", "value": target, "intent": "open_dynamic"}

        if "http://" in lower or "https://" in lower or "www." in lower:
            return {"tool": "open_web", "value": text.strip(), "intent": "open_web"}

        return None

    def _execute_dynamic_steps(self, task_name: str, steps: List[Dict[str, Any]]) -> Tuple[str, bool, str]:
        messages: List[str] = []
        overall_success = True
        last_error = ""
        step_results: Dict[int, bool] = {}
        for idx, step in enumerate(steps):
            deps = step.get("dependencies", []) or []
            if any(step_results.get(int(d), False) is False for d in deps if isinstance(d, int)):
                messages.append(f"Paso {idx} omitido por dependencia fallida.")
                step_results[idx] = False
                overall_success = False
                continue
            if not self._preconditions_ok(step):
                messages.append(f"Paso {idx} omitido por precondición no cumplida.")
                step_results[idx] = False
                overall_success = False
                continue
            tool = str(step.get("tool", "")).strip().lower()
            value = step.get("value")
            try:
                msg, ok = ("", False)
                for attempt in range(3):
                    if tool == "command":
                        msg, ok = self._run_terminal_command(str(value), require_confirm=True)
                    elif tool == "type":
                        result = self.mouse_keyboard.type_text(str(value))
                        ok = result.get("status") == "ok"
                        msg = result.get("message", "Acción ejecutada.")
                    elif tool == "move_file":
                        src = str((value or {}).get("src", ""))
                        dst = str((value or {}).get("dst", ""))
                        msg, ok = self._move_file(src, dst)
                    elif tool == "observe":
                        msg = self._observe(str(value or ""))
                        ok = True
                    elif tool == "open_web":
                        msg, ok = self._open_web_dynamic(str(value))
                    elif tool == "open_dynamic":
                        msg, ok = self._open_any_dynamic(str(value))
                    else:
                        msg, ok = (f"Paso omitido (tool no soportada): {tool}", False)
                    if ok:
                        break
                    time.sleep(0.2 * (2**attempt))
                verify_ok = self._verify_step(tool, value)
                ok = ok and verify_ok
                if not verify_ok:
                    msg = f"{msg} (verificación posterior fallida)"
                messages.append(msg)
                step_results[idx] = ok
                if not ok:
                    overall_success = False
                    last_error = msg
            except Exception as exc:
                overall_success = False
                last_error = str(exc)
                messages.append(f"Error ejecutando paso {tool}: {exc}")
                step_results[idx] = False
        gc.collect()
        result_text = " | ".join(messages) if messages else "Sin acciones ejecutables."
        if overall_success:
            return f"Tarea resuelta dinámicamente: {result_text}", True, ""
        return f"Tarea parcialmente resuelta: {result_text}", False, last_error

    def _run_generalized_template(self, text: str, generalized: Dict[str, Any]) -> Tuple[bool, str]:
        template = generalized.get("template", {})
        mode = str(template.get("mode", "")).strip().lower()
        if mode == "open_program":
            target = self._extract_after_open(text)
            if not target:
                return False, ""
            msg, ok = self._open_program_dynamic(target)
            self.tasks.log_execution(
                ExecutionLog(
                    task_trigger=text,
                    intent="open_program",
                    parameters={"target": target},
                    result=msg,
                    success=ok,
                    error="" if ok else msg,
                    context="generalized_skill",
                )
            )
            return True, msg
        if mode == "open_website":
            target = self._extract_after_open(text)
            if not target:
                return False, ""
            msg, ok = self._open_web_dynamic(target)
            return True, msg
        return False, ""

    def _persist_learned_execution(
        self,
        user_text: str,
        steps: List[Dict[str, Any]],
        result_message: str,
        success: bool,
        error: str,
    ) -> None:
        normalized_trigger = self._normalize(user_text)
        variables = self._extract_variables(user_text, steps)
        context = self._runtime_context()
        plan = {"steps": steps, "variables": variables, "context": context}
        learned = self.tasks.save_task(
            name=f"Auto tarea: {normalized_trigger[:48]}",
            trigger=normalized_trigger,
            steps=steps,
            source="dynamic_auto",
            variables=variables,
            context=context,
            plan=plan,
        )
        if learned:
            self._generate_task_script(name=f"auto_{normalized_trigger[:24]}", trigger=normalized_trigger, steps=steps)
        self.tasks.log_execution(
            ExecutionLog(
                task_trigger=normalized_trigger,
                intent="dynamic_task",
                parameters={"steps": steps[:12]},
                result=result_message,
                success=success,
                error=error,
                context="dynamic_learning",
            )
        )
        self._learn_general_pattern(user_text, steps, success, error)

    def _extract_variables(self, text: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        vars_map: Dict[str, Any] = {"raw": text[:160]}
        for step in steps[:4]:
            if step.get("tool") == "open_dynamic":
                vars_map["target"] = str(step.get("value", "")).strip()
            if step.get("tool") == "open_web":
                vars_map["url"] = str(step.get("value", "")).strip()
        return vars_map

    @staticmethod
    def _runtime_context() -> Dict[str, Any]:
        try:
            import platform
            import psutil

            return {
                "os": platform.system().lower(),
                "ram_percent": float(psutil.virtual_memory().percent),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        except Exception:
            return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def _learn_general_pattern(self, text: str, steps: List[Dict[str, Any]], success: bool, error: str) -> None:
        if not steps:
            return
        first = steps[0]
        tool = str(first.get("tool", "")).lower()
        if tool == "open_dynamic":
            target = str(first.get("value", ""))
            if self._looks_like_web(target):
                self.tasks.learn_generalized_skill(
                    pattern_key="abre ",
                    skill_name="abrir sitio por nombre o url",
                    intent="open_web",
                    template={"mode": "open_website"},
                    success=success,
                    error=error,
                )
            else:
                self.tasks.learn_generalized_skill(
                    pattern_key="abre ",
                    skill_name="abrir programa por nombre",
                    intent="open_app",
                    template={"mode": "open_program"},
                    success=success,
                    error=error,
                )

    def _extract_after_open(self, text: str) -> str:
        match = self.OPEN_ANY_REGEX.match(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _learn_from_inline(self, payload: str) -> Tuple[bool, str]:
        chunks = [p.strip() for p in payload.split("|") if p.strip()]
        data: Dict[str, str] = {}
        for chunk in chunks:
            if "=" not in chunk:
                continue
            key, value = chunk.split("=", 1)
            data[key.strip().lower()] = value.strip()
        name = data.get("nombre") or data.get("name") or "tarea aprendida"
        trigger = data.get("trigger") or data.get("gatillo") or ""
        raw_steps = data.get("pasos") or data.get("steps") or ""
        if not trigger or not raw_steps:
            return False, "Use: nombre=... | trigger=... | pasos=accion:valor; accion:valor"
        steps = self._parse_steps(raw_steps)
        if not steps:
            return False, "No detecté pasos válidos."
        if not self.tasks.save_task(name=name, trigger=trigger, steps=steps, source="inline"):
            return False, "Error guardando en base de tareas."
        script_path = self._generate_task_script(name=name, trigger=trigger, steps=steps)
        return True, f"Tarea '{name}' aprendida. Trigger: '{trigger}'. Script: {script_path}"

    def _parse_steps(self, raw_steps: str) -> List[Dict[str, Any]]:
        steps: List[Dict[str, Any]] = []
        for chunk in [s.strip() for s in raw_steps.split(";") if s.strip()]:
            if ":" not in chunk:
                continue
            action, value = chunk.split(":", 1)
            action = action.strip().lower()
            value = value.strip()
            if not action or not value:
                continue
            steps.append({"tool": action, "value": value})
        return steps

    def _run_task(self, task: LearnedTask) -> Tuple[str, bool, str]:
        return self._run_task_sandboxed(task)

    def _run_task_sandboxed(self, task: LearnedTask) -> Tuple[str, bool, str]:
        """Ejecuta tareas aprendidas en proceso aislado con timeout."""
        preexec = None
        if os.name != "nt":
            def _limit_resources() -> None:
                try:
                    import resource

                    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
                    # 300MB address space for sandbox runner.
                    mem_limit = 300 * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
                except Exception:
                    pass

            preexec = _limit_resources
        try:
            script = (
                "import json,sys,time\n"
                "steps=json.loads(sys.argv[1])\n"
                "time.sleep(0)\n"
                "print(f'SANDBOX_STEPS={len(steps)}')\n"
            )
            completed = subprocess.run(
                [sys.executable, "-c", script, json.dumps(task.steps[:18], ensure_ascii=False)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(config.PROJECT_ROOT),
                env={"PYTHONUTF8": "1", "PATH": os.environ.get("PATH", "")},
                preexec_fn=preexec,
            )
            if completed.returncode != 0:
                return (
                    f"No pude ejecutar la habilidad en sandbox (code={completed.returncode}).",
                    False,
                    redact_sensitive_data((completed.stderr or "").strip()[:240]),
                )
        except subprocess.TimeoutExpired:
            return ("Sandbox detenido por timeout de 30s.", False, "timeout")
        except Exception as exc:
            return (f"Error de sandbox: {exc}", False, redact_sensitive_data(str(exc)))

        results: List[str] = []
        overall_ok = True
        last_error = ""
        for step in task.steps[:18]:
            tool = str(step.get("tool", "")).strip().lower()
            value = step.get("value")
            if tool in {"abrir", "open", "open_app", "open_dynamic"}:
                msg, ok = self._open_any_dynamic(str(value))
            elif tool in {"escribir", "type", "write"}:
                result = self.mouse_keyboard.type_text(str(value))
                ok = result.get("status") == "ok"
                msg = result.get("message", "ok")
            elif tool in {"comando", "cmd", "command"}:
                msg, ok = self._run_terminal_command(str(value), require_confirm=False)
            elif tool == "open_web":
                msg, ok = self._open_web_dynamic(str(value))
            elif tool == "move_file":
                src = str((value or {}).get("src", ""))
                dst = str((value or {}).get("dst", ""))
                msg, ok = self._move_file(src, dst)
            else:
                msg, ok = (f"Paso omitido (tool no soportada): {tool}", False)
            if not ok:
                overall_ok = False
                last_error = msg
            results.append(msg)
            results[-1] = redact_sensitive_data(results[-1])
        gc.collect()
        answer = f"Ejecuté la tarea '{task.name}'. Resultado: {' | '.join(results) if results else 'sin pasos aplicables'}"
        return answer, overall_ok, last_error

    def _open_any_dynamic(self, target: str) -> Tuple[str, bool]:
        clean = (target or "").strip()
        if not clean:
            return "Objetivo vacío para abrir.", False
        if self._looks_like_web(clean) or any(k in clean.lower() for k in (" sitio", " web", " página", " pagina")):
            return self._open_web_dynamic(clean)
        return self._open_program_dynamic(clean)

    def _open_program_dynamic(self, target: str) -> Tuple[str, bool]:
        target_validation = sanitize_app_target(target)
        if not target_validation.allowed:
            return f"Objetivo bloqueado por seguridad: {target_validation.reason}", False
        target = target_validation.sanitized
        # Estrategia 1: resolver con ActionController (rutas, PATH, StartApps y fallback start).
        result = self.actions.open_app(target)
        if result.get("status") == "ok":
            verified = self._verify_program_open(target)
            if verified:
                return result.get("message", "Aplicación abierta."), True

        # Estrategia 2: si es ruta de ejecutable.
        raw = target.strip().strip('"')
        exe_path = Path(raw)
        if exe_path.exists() and exe_path.is_file():
            try:
                subprocess.Popen([str(exe_path)], shell=False)
                return f"Aplicación abierta por ruta: {exe_path}", True
            except Exception as exc:
                log.debug("No pude abrir por ruta '%s': %s", exe_path, exc)

        # Estrategia 3: coincidencia parcial en Start Menu.
        try:
            ps_cmd = (
                "$n='" + raw.replace("'", "''") + "'; "
                "Get-StartApps | Where-Object { $_.Name -like \"*$n*\" } | Select-Object -First 1 -ExpandProperty Name"
            )
            found = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
            candidate = (found.stdout or "").strip().splitlines()
            if candidate:
                result2 = self.actions.open_app(candidate[0])
                if result2.get("status") == "ok" and self._verify_program_open(candidate[0]):
                    return f"Abrí '{candidate[0]}' por coincidencia parcial.", True
        except Exception as exc:
            log.debug("Fallback StartApps parcial falló: %s", exc)

        return f"No pude abrir '{target}' tras varias estrategias.", False

    def _open_web_dynamic(self, target: str) -> Tuple[str, bool]:
        clean = (target or "").strip()
        if not clean:
            return "Objetivo web vacío.", False
        clean = re.sub(r"^(la|el|sitio|pagina|página)\s+", "", clean, flags=re.IGNORECASE).strip()

        candidates: List[str] = []
        web_type = self._classify_web_target(clean)
        if self.URL_LIKE_REGEX.match(clean):
            candidates.append(clean if clean.startswith("http") else f"https://{clean}")
        elif self.DOMAIN_LIKE_REGEX.match(clean):
            candidates.append(f"https://{clean}")
        else:
            compact = clean.replace(" ", "")
            if compact and "." not in compact:
                candidates.append(f"https://{compact}.com")
            candidates.append(f"https://www.google.com/search?q={quote_plus(clean)}")

        for url in candidates:
            try:
                webbrowser.open(url)
                if web_type == "login_required":
                    return f"Abriendo web: {url}. Esta web probablemente requiere login/interacción manual.", True
                return f"Abriendo web: {url}", True
            except Exception as exc:
                log.debug("No pude abrir url '%s': %s", url, exc)
                continue
        return f"No pude abrir web para '{target}'.", False

    def _run_terminal_command(self, command: str, require_confirm: bool) -> Tuple[str, bool]:
        safe = (command or "").strip()
        if not safe:
            return "Comando vacío.", False
        validation = validate_shell_command(safe, self.ALLOWED_SHELL_COMMANDS)
        if not validation.allowed:
            return f"Comando bloqueado por seguridad: {validation.reason}", False
        cmd_token = validation.sanitized.split()[0].lower() if validation.sanitized.split() else ""
        allowed = True
        try:
            completed = subprocess.run(
                validation.sanitized,
                shell=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self._audit_command(validation.sanitized, completed.returncode, completed.stdout, completed.stderr, allowed)
            stdout = redact_sensitive_data((completed.stdout or "").strip())
            stderr = redact_sensitive_data((completed.stderr or "").strip())
            summary = stdout[:220] if stdout else stderr[:220]
            ok = completed.returncode == 0
            return f"Comando ejecutado (code={completed.returncode}). {summary or 'Sin salida.'}", ok
        except Exception as exc:
            self._audit_command(safe, -1, "", str(exc), allowed)
            return f"No pude ejecutar el comando: {exc}", False

    def _move_file(self, src: str, dst: str) -> Tuple[str, bool]:
        source = Path(src.strip('"').strip())
        target = Path(dst.strip('"').strip())
        try:
            if not source.exists() or not source.is_file():
                return "Archivo origen no encontrado.", False
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            return f"Archivo movido a {target}", True
        except Exception as exc:
            return f"No pude mover el archivo: {exc}", False

    def _observe(self, payload: str) -> str:
        include_processes = "procesos" in payload.lower()
        include_screen = "captura" in payload.lower()
        include_dir = ""
        if "dir=" in payload.lower():
            match = re.search(r"dir\s*=\s*(.+)$", payload, flags=re.IGNORECASE)
            include_dir = (match.group(1).strip() if match else "").strip('"')
        shot = self.observer.snapshot(
            include_processes=include_processes,
            include_dir=include_dir,
            include_screenshot=include_screen,
        )
        mem = shot.get("memory", {})
        parts = [
            f"RAM {mem.get('used_mb', '?')}/{mem.get('total_mb', '?')} MB ({mem.get('percent', '?')}%)",
            f"CPU {shot.get('cpu_percent', '?')}%",
        ]
        if shot.get("processes"):
            top = shot["processes"][0]
            parts.append(f"Top proceso: {top.get('name', '?')} ({top.get('rss_mb', '?')} MB)")
        if shot.get("screenshot_path"):
            parts.append(f"Captura: {shot['screenshot_path']}")
        return " | ".join(parts)

    def _generate_task_script(self, name: str, trigger: str, steps: List[Dict[str, Any]]) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "task"
        script_path = self.generated_scripts_dir / f"{slug}.py"
        lines = [
            '"""Script autogenerado por ActionAgent."""',
            "",
            "from eda.actions import ActionController",
            "from eda.mouse_keyboard import MouseKeyboardController",
            "",
            f"TASK_NAME = {name!r}",
            f"TRIGGER = {trigger!r}",
            f"STEPS = {steps!r}",
            "",
            "def run() -> None:",
            "    actions = ActionController()",
            "    mk = MouseKeyboardController()",
            "    for step in STEPS:",
            "        tool = str(step.get('tool', '')).lower().strip()",
            "        value = step.get('value')",
            "        if tool in {'abrir', 'open', 'open_app', 'open_dynamic'}:",
            "            actions.open_app(str(value))",
            "        elif tool in {'escribir', 'type', 'write'}:",
            "            mk.type_text(str(value))",
            "",
            "if __name__ == '__main__':",
            "    run()",
        ]
        script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(script_path)

    def _looks_like_web(self, text: str) -> bool:
        probe = (text or "").strip().lower()
        if not probe:
            return False
        if self.URL_LIKE_REGEX.match(probe) or self.DOMAIN_LIKE_REGEX.match(probe):
            return True
        web_words = ("web", "sitio", "pagina", "página", ".com", ".org", ".net")
        return any(w in probe for w in web_words)

    def _verify_program_open(self, target: str, wait_seconds: float = 2.5) -> bool:
        start = time.time()
        low_target = target.lower()
        while time.time() - start <= wait_seconds:
            try:
                import psutil

                for proc in psutil.process_iter(["name"]):
                    name = str(proc.info.get("name", "")).lower()
                    if low_target in name or name.startswith(low_target):
                        return True
            except Exception:
                pass
            try:
                import pygetwindow as gw

                for w in gw.getAllWindows():
                    title = str(getattr(w, "title", "")).lower()
                    if low_target in title and title.strip():
                        return True
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def _verify_step(self, tool: str, value: Any) -> bool:
        if tool in {"open_dynamic", "open_web"}:
            return True
        if tool in {"abrir", "open", "open_app"}:
            return self._verify_program_open(str(value))
        if tool == "move_file":
            dst = Path(str((value or {}).get("dst", "")).strip('"').strip())
            return dst.exists()
        return True

    def _preconditions_ok(self, step: Dict[str, Any]) -> bool:
        conditions = step.get("preconditions", []) or []
        for cond in conditions:
            probe = str(cond).lower()
            if "ram" in probe and "80" in probe:
                try:
                    import psutil

                    if psutil.virtual_memory().percent >= 80:
                        return False
                except Exception:
                    return True
        return True

    def _audit_command(self, command: str, code: int, stdout: str, stderr: str, whitelisted: bool) -> None:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "command": command[:300],
            "exit_code": int(code),
            "whitelisted": bool(whitelisted),
            "stdout": (stdout or "")[:500],
            "stderr": (stderr or "")[:500],
        }
        try:
            with self.command_audit_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _classify_web_target(target: str) -> str:
        low = (target or "").lower()
        if any(k in low for k in ("login", "iniciar sesión", "signin", "auth")):
            return "login_required"
        if any(k in low for k in ("form", "dashboard", "portal")):
            return "dynamic_form"
        return "public"
