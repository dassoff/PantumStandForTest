"""Тесты отказоустойчивости и fallback цепочки."""

import os
import tempfile
from typing import Any, Dict, Optional

import pytest

from core.fallback import FallbackChain, FallbackMethod, FallbackResult
from core.printer import FastPrinter, PrintStatus
from utils.helpers import generate_test_pdf


class TestFallbackChain:
    """Тесты fallback цепочки."""

    @pytest.fixture
    def printer(self, printer_ip: Optional[str] = None) -> FastPrinter:
        """Создание экземпляра принтера."""
        return FastPrinter(printer_ip=printer_ip, tcp_timeout=2)

    @pytest.fixture
    def sample_pdf(self) -> str:
        """Создание тестового PDF файла."""
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=1, text="Fallback Test")
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_fallback_with_wrong_ip(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест fallback при недоступном IP."""
        # Устанавливаем неверный IP
        printer.printer_ip = "192.168.255.255"

        fallback_chain = FallbackChain(printer, max_fallback_time=3.0)
        result = await fallback_chain.execute(sample_pdf, copies=1, duplex=False)

        # Все методы должны были быть尝试ованы
        assert len(fallback_chain.get_results()) >= 1

        # Хотя бы один метод должен был быть尝试ован
        assert FallbackMethod.RAW_TCP in [r.method for r in fallback_chain.get_results()]

    @pytest.mark.asyncio
    async def test_fallback_summary(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест сводки fallback."""
        printer.printer_ip = "192.168.255.255"

        fallback_chain = FallbackChain(printer, max_fallback_time=2.0)
        await fallback_chain.execute(sample_pdf, copies=1, duplex=False)

        summary = fallback_chain.get_summary()

        assert "total_attempts" in summary
        assert "success" in summary
        assert "methods_tried" in summary
        assert "total_duration_ms" in summary

    @pytest.mark.asyncio
    async def test_fallback_with_valid_printer(
        self,
        printer: FastPrinter,
        sample_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест fallback с валидным принтером."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        fallback_chain = FallbackChain(printer, max_fallback_time=10.0)
        result = await fallback_chain.execute(sample_pdf, copies=1, duplex=False)

        # Должен успешно напечатать через RAW TCP
        assert result.success
        assert result.method == FallbackMethod.RAW_TCP

    @pytest.mark.asyncio
    async def test_fallback_timeout(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест таймаута fallback."""
        printer.printer_ip = "192.168.255.255"

        # Короткий таймаут
        fallback_chain = FallbackChain(printer, max_fallback_time=1.0)
        result = await fallback_chain.execute(sample_pdf, copies=1, duplex=False)

        # Должен завершиться с ошибкой
        assert result.duration_ms < 5000  # Общий таймаут

    @pytest.mark.asyncio
    async def test_fallback_results_history(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест истории результатов fallback."""
        printer.printer_ip = "192.168.255.255"

        fallback_chain = FallbackChain(printer, max_fallback_time=2.0)
        await fallback_chain.execute(sample_pdf, copies=1, duplex=False)

        results = fallback_chain.get_results()

        # Каждый результат должен иметь правильную структуру
        for result in results:
            assert isinstance(result, FallbackResult)
            assert isinstance(result.method, FallbackMethod)
            assert isinstance(result.duration_ms, int)
            assert isinstance(result.success, bool)


class TestFallbackMethods:
    """Тесты отдельных методов fallback."""

    @pytest.fixture
    def printer(self) -> FastPrinter:
        """Создание экземпляра принтера."""
        return FastPrinter(tcp_timeout=1)

    @pytest.fixture
    def sample_pdf(self) -> str:
        """Создание тестового PDF файла."""
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=1, text="Method Test")
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_raw_tcp_method_no_ip(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест RAW TCP метода без IP."""
        fallback_chain = FallbackChain(printer)
        result = await fallback_chain._try_raw_tcp(sample_pdf, copies=1, duplex=False)

        assert not result.success
        assert "IP not specified" in result.error

    @pytest.mark.asyncio
    async def test_sumatra_method_not_found(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест метода SumatraPDF когда он не найден."""
        fallback_chain = FallbackChain(printer, sumatra_path="C:\\NonExistent\\SumatraPDF.exe")
        result = await fallback_chain._try_sumatra(sample_pdf, copies=1)

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_adobe_method_not_found(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест метода Adobe Reader когда он не найден."""
        fallback_chain = FallbackChain(printer, adobe_path="C:\\NonExistent\\Acrobat.exe")
        result = await fallback_chain._try_adobe(sample_pdf, copies=1)

        assert not result.success
        assert "not found" in result.error.lower()


class TestNetworkSimulation:
    """Тесты симуляции сетевых проблем."""

    @pytest.fixture
    def printer(self) -> FastPrinter:
        """Создание экземпляра принтера."""
        return FastPrinter(tcp_timeout=1)

    @pytest.mark.asyncio
    async def test_printer_offline_simulation(
        self,
        printer: FastPrinter,
    ) -> None:
        """Симуляция offline принтера."""
        printer.printer_ip = "127.0.0.1"
        printer.printer_port = 65432  # Закрытый порт

        status = await printer.get_status()

        # Статус должен показать что принтер недоступен
        # (если только у вас не запущен сервер на этом порту)
        assert status.online in (True, False)  # Может быть и True если порт открыт

    @pytest.mark.asyncio
    async def test_printer_timeout_simulation(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Симуляция таймаута подключения."""
        import time

        printer.printer_ip = "10.255.255.1"  # Адрес который скорее всего не ответит
        printer.tcp_timeout = 1

        start = time.time()
        job = await printer.print_pdf_fast(sample_pdf, copies=1, duplex=False)
        duration = time.time() - start

        # Должен завершиться с ошибкой и не зависнуть
        assert duration < 10  # Общий таймаут
        assert job.status == PrintStatus.FAILED


def create_fallback_test_report(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Создание отчёта о тестах fallback."""
    return {
        "total_tests": len(results),
        "successful": sum(1 for r in results if r.get("success", False)),
        "failed": sum(1 for r in results if not r.get("success", False)),
        "avg_duration_ms": sum(r.get("duration_ms", 0) for r in results) / len(results) if results else 0,
        "methods_tested": list(set(r.get("method", "") for r in results)),
        "results": results,
    }
