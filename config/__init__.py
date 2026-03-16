"""Конфигурация тестового стенда печати."""

from .validator import ConfigValidator, validate_config
from pydantic_settings import BaseSettings

__all__ = ["ConfigValidator", "validate_config", "Settings"]


class Settings(BaseSettings):
    """Настройки приложения."""

    class Config:
        env_prefix = "PRINT_"
        env_file = ".env"
