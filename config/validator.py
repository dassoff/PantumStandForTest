"""Валидация конфигурации тестового стенда."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class PrinterCapabilities(BaseModel):
    """Возможности принтера."""

    duplex: bool = True
    color: bool = False
    max_resolution: int = 600


class PrinterDefaults(BaseModel):
    """Настройки печати по умолчанию."""

    copies: int = Field(default=1, ge=1, le=999)
    duplex: bool = True
    paper: str = "A4"


class PrinterConfig(BaseModel):
    """Конфигурация принтера."""

    name: str = "Pantum BM5100ADN"
    ip: Optional[str] = None
    port: int = 9100
    mac: Optional[str] = None
    protocol: str = "raw_tcp"
    capabilities: PrinterCapabilities = Field(default_factory=PrinterCapabilities)
    defaults: PrinterDefaults = Field(default_factory=PrinterDefaults)

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        allowed = ["raw_tcp", "lpd", "ipp", "smb"]
        if v not in allowed:
            raise ValueError(f"Protocol must be one of: {allowed}")
        return v


class PathsConfig(BaseModel):
    """Конфигурация путей."""

    ghostscript: Optional[str] = None
    libreoffice: Optional[str] = None
    sumatra: Optional[str] = None
    temp_dir: str = "./temp"

    @field_validator("temp_dir")
    @classmethod
    def validate_temp_dir(cls, v: str) -> str:
        path = Path(v)
        path.mkdir(parents=True, exist_ok=True)
        return str(path)


class PerformanceConfig(BaseModel):
    """Конфигурация производительности."""

    tcp_timeout: int = Field(default=10, ge=1, le=300)
    conversion_timeout: int = Field(default=30, ge=1, le=600)
    max_concurrent_jobs: int = Field(default=5, ge=1, le=100)
    enable_cache: bool = True
    cache_size: int = Field(default=50, ge=1, le=1000)


class LoggingConfig(BaseModel):
    """Конфигурация логирования."""

    level: str = "INFO"
    file: str = "./reports/print.log"
    format: str = "json"

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"Log level must be one of: {allowed}")
        return v.upper()

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        allowed = ["json", "text"]
        if v not in allowed:
            raise ValueError(f"Log format must be one of: {allowed}")
        return v


class FullConfig(BaseModel):
    """Полная конфигурация приложения."""

    printer: PrinterConfig = Field(default_factory=PrinterConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class ConfigValidator:
    """Валидатор конфигурации."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self.config: Optional[FullConfig] = None
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def load(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Загрузка конфигурации из YAML файла."""
        path = config_path or self.config_path
        if not path:
            raise FileNotFoundError("Config path not specified")

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def validate(self, config_data: Dict[str, Any]) -> bool:
        """Валидация конфигурации."""
        self.errors = []
        self.warnings = []

        try:
            self.config = FullConfig(**config_data)
        except Exception as e:
            self.errors.append(f"Schema validation error: {str(e)}")
            return False

        # Дополнительные проверки
        self._check_executables()
        self._check_network_settings()

        return len(self.errors) == 0

    def _check_executables(self) -> None:
        """Проверка существования исполняемых файлов."""
        if not self.config:
            return

        executables = [
            ("Ghostscript", self.config.paths.ghostscript),
            ("LibreOffice", self.config.paths.libreoffice),
            ("SumatraPDF", self.config.paths.sumatra),
        ]

        for name, path in executables:
            if path and not os.path.exists(path):
                self.warnings.append(f"{name} not found at: {path}")

    def _check_network_settings(self) -> None:
        """Проверка сетевых настроек."""
        if not self.config:
            return

        if not self.config.printer.ip:
            self.warnings.append("Printer IP not specified, auto-detection will be used")

        if self.config.printer.mac:
            mac = self.config.printer.mac
            if not self._validate_mac(mac):
                self.errors.append(f"Invalid MAC address format: {mac}")

    @staticmethod
    def _validate_mac(mac: str) -> bool:
        """Валидация MAC-адреса."""
        import re

        pattern = r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$"
        return bool(re.match(pattern, mac))

    def get_config(self) -> FullConfig:
        """Получение валидированной конфигурации."""
        if not self.config:
            raise ValueError("Config not validated yet")
        return self.config

    def get_report(self) -> Dict[str, Any]:
        """Получение отчёта о валидации."""
        return {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
            "config": self.config.model_dump() if self.config else None,
        }


def validate_config(config_path: str) -> Dict[str, Any]:
    """Утилита для быстрой валидации конфигурации."""
    validator = ConfigValidator(config_path)
    config_data = validator.load()
    validator.validate(config_data)
    return validator.get_report()
