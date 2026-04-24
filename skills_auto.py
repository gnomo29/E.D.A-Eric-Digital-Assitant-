"""Módulo de habilidades auto-aprendidas de E.D.A."""


def learned_busac_xokas(command_text: str = "") -> dict:
    """Función aprendida automáticamente por E.D.A."""
    texto = command_text.strip() or "busac xokas"
    return {
        "status": "ok",
        "message": f"Acción aprendida ejecutada para: {texto}",
    }


def learned_aprender_a_controlar_la(command_text: str = "") -> dict:
    """Abre la cámara del sistema (Windows)."""
    try:
        import os
        import subprocess
        if os.name == 'nt':
            subprocess.Popen('start microsoft.windows.camera:', shell=True)
            return {'status': 'ok', 'message': 'Abriendo la cámara del sistema.'}
        return {'status': 'error', 'message': 'Apertura de cámara no implementada para este sistema.'}
    except Exception as exc:
        return {'status': 'error', 'message': f'No pude abrir la cámara: {exc}'}
