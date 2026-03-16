"""Тесты для тестового стенда печати."""

from .test_pdf import TestPDFPrinting
from .test_docx import TestDOCXPrinting
from .test_speed import TestSpeedBenchmark
from .test_fallback import TestFallbackChain

__all__ = [
    "TestPDFPrinting",
    "TestDOCXPrinting",
    "TestSpeedBenchmark",
    "TestFallbackChain",
]
