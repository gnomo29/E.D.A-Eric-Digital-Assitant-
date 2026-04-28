"""Módulo de logging centralizado."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from . import config
from .utils.security import redact_sensitive_data


class RedactingFilter(logging.Filter):
    """Filtro global de secretos/PII en logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_sensitive_data(str(record.msg))
            if record.args:
                record.args = tuple(redact_sensitive_data(str(arg)) for arg in record.args)
        except Exception:
            pass
        return True


def setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    """Configura y retorna el logger principal del sistema."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    target_file = log_file or (config.LOGS_DIR / "eda.log")

    logger = logging.getLogger("EDA")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(target_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RedactingFilter())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RedactingFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    logger.info("Logger inicializado")
    return logger


def get_logger(name: str = "EDA") -> logging.Logger:
    """Obtiene un logger hijo del logger central."""
    root = setup_logging()
    if name == "EDA":
        return root
    return root.getChild(name)
