"""Структурированное логирование для тестового стенда."""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import structlog


class PrintLogger:
    """Логгер для печати с поддержкой JSON формата."""

    def __init__(
        self,
        log_file: Optional[str] = None,
        level: str = "INFO",
        log_format: str = "json",
    ):
        """Инициализация логгера."""
        self.log_file = log_file
        self.level = getattr(logging, level.upper(), logging.INFO)
        self.log_format = log_format

        self._setup_logging()

    def _setup_logging(self) -> None:
        """Настройка логгера."""
        # Создаем директорию для логов
        if self.log_file:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

        # Настройка structlog
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        if self.log_format == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Настройка handlers
        handlers = []

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.level)
        handlers.append(console_handler)

        # File handler
        if self.log_file:
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setLevel(self.level)
            handlers.append(file_handler)

        # Настройка корневого логгера
        logging.basicConfig(
            format="%(message)s",
            level=self.level,
            handlers=handlers,
        )

    def log_print_job(
        self,
        job_id: str,
        file_path: str,
        method: str,
        status: str,
        duration_ms: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        """Логирование задания печати."""
        logger = structlog.get_logger("print")

        event_data = {
            "event": "print_job",
            "job_id": job_id,
            "file_path": file_path,
            "method": method,
            "status": status,
        }

        if duration_ms is not None:
            event_data["duration_ms"] = duration_ms

        if error:
            event_data["error"] = error

        if status == "completed":
            logger.info(**event_data)
        elif status == "failed":
            logger.error(**event_data)
        else:
            logger.info(**event_data)

    def log_benchmark(
        self,
        method: str,
        file_size: int,
        pages: int,
        duration_ms: int,
        throughput: float,
    ) -> None:
        """Логирование результатов бенчмарка."""
        logger = structlog.get_logger("benchmark")

        logger.info(
            event="benchmark_result",
            method=method,
            file_size=file_size,
            pages=pages,
            duration_ms=duration_ms,
            throughput_pages_per_min=throughput,
        )

    def log_error(
        self,
        error_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Логирование ошибки."""
        logger = structlog.get_logger("error")

        event_data = {
            "event": "error",
            "error_type": error_type,
            "message": message,
        }

        if context:
            event_data.update(context)

        logger.error(**event_data)

    def log_status(
        self,
        printer_ip: str,
        online: bool,
        ready: bool,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Логирование статуса принтера."""
        logger = structlog.get_logger("status")

        event_data = {
            "event": "printer_status",
            "printer_ip": printer_ip,
            "online": online,
            "ready": ready,
        }

        if details:
            event_data.update(details)

        logger.info(**event_data)


# Глобальный экземпляр логгера
_global_logger: Optional[PrintLogger] = None


def setup_logger(
    log_file: Optional[str] = None,
    level: str = "INFO",
    log_format: str = "json",
) -> PrintLogger:
    """Настройка глобального логгера."""
    global _global_logger
    _global_logger = PrintLogger(log_file, level, log_format)
    return _global_logger


def get_logger() -> PrintLogger:
    """Получение глобального логгера."""
    if _global_logger is None:
        _global_logger = PrintLogger()
    return _global_logger
