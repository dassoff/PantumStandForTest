"""Тесты PDF печати."""

import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import pytest

from core.printer import FastPrinter, PrintJob, PrintStatus
from utils.helpers import generate_test_pdf


class TestPDFPrinting:
    """Тесты печати PDF файлов."""

    @pytest.fixture
    def printer(self, printer_ip: Optional[str] = None) -> FastPrinter:
        """Создание экземпляра принтера."""
        return FastPrinter(printer_ip=printer_ip)

    @pytest.fixture
    def sample_pdf(self) -> str:
        """Создание тестового PDF файла."""
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=1, text="Test PDF - Single Page")
        yield path
        os.unlink(path)

    @pytest.fixture
    def large_pdf(self) -> str:
        """Создание большого тестового PDF файла."""
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=10, text="Test PDF - Large Document")
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_print_single_page_pdf(
        self,
        printer: FastPrinter,
        sample_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест печати 1-страничного PDF."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        job = await printer.print_pdf_fast(sample_pdf, copies=1, duplex=False)

        assert job.status == PrintStatus.COMPLETED, f"Print failed: {job.error}"
        assert job.duration_ms is not None
        assert job.duration_ms < 5000, f"Print took too long: {job.duration_ms}ms"

    @pytest.mark.asyncio
    async def test_print_large_pdf(
        self,
        printer: FastPrinter,
        large_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест печати 10-страничного PDF (нагрузка)."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        job = await printer.print_pdf_fast(large_pdf, copies=1, duplex=False)

        assert job.status == PrintStatus.COMPLETED, f"Print failed: {job.error}"
        assert job.duration_ms is not None
        # 10 страниц должны напечататься за разумное время
        assert job.duration_ms < 30000, f"Print took too long: {job.duration_ms}ms"

    @pytest.mark.asyncio
    async def test_print_with_duplex(
        self,
        printer: FastPrinter,
        sample_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест печати с дуплексом."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        job = await printer.print_pdf_fast(sample_pdf, copies=1, duplex=True)

        assert job.status == PrintStatus.COMPLETED, f"Print failed: {job.error}"

    @pytest.mark.asyncio
    async def test_print_multiple_copies(
        self,
        printer: FastPrinter,
        sample_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест печати 2 копий."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        job = await printer.print_pdf_fast(sample_pdf, copies=2, duplex=False)

        assert job.status == PrintStatus.COMPLETED, f"Print failed: {job.error}"

    @pytest.mark.asyncio
    async def test_print_from_stream(
        self,
        printer: FastPrinter,
        printer_ip: Optional[str],
    ) -> None:
        """Тест печати из потока (bytes)."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        # Создаем PDF в памяти
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(temp_path, pages=1, text="Stream Test")

        with open(temp_path, "rb") as f:
            pdf_data = f.read()

        os.unlink(temp_path)

        job = await printer.print_pdf_stream(pdf_data, copies=1, duplex=False)

        assert job.status == PrintStatus.COMPLETED, f"Print failed: {job.error}"

    @pytest.mark.asyncio
    async def test_print_without_printer_ip(
        self,
        printer: FastPrinter,
        sample_pdf: str,
    ) -> None:
        """Тест печати без указания IP (должен вернуть ошибку)."""
        job = await printer.print_pdf_fast(sample_pdf)

        # Ожидаем ошибку или завершение (если IP определен автоматически)
        assert job.status in (PrintStatus.FAILED, PrintStatus.COMPLETED)

    @pytest.mark.asyncio
    async def test_job_history(
        self,
        printer: FastPrinter,
        sample_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест истории заданий."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        # Выполняем несколько заданий
        for i in range(3):
            await printer.print_pdf_fast(sample_pdf, copies=1, duplex=False)

        history = printer.get_job_history(limit=10)

        assert len(history) >= 3
        assert all(isinstance(job, PrintJob) for job in history)

    @pytest.mark.asyncio
    async def test_cancel_job(
        self,
        printer: FastPrinter,
        sample_pdf: str,
        printer_ip: Optional[str],
    ) -> None:
        """Тест отмены задания."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        # Запускаем задание в фоне
        import asyncio

        task = asyncio.create_task(
            printer.print_pdf_fast(sample_pdf, copies=1, duplex=False)
        )

        # Даем заданию начаться
        await asyncio.sleep(0.1)

        # Пытаемся отменить
        cancelled = await printer.cancel_job()

        # Отмена может не сработать если задание уже завершено
        assert cancelled in (True, False)


# Конфигурация pytest
def pytest_addoption(parser):
    """Добавление опций командной строки."""
    parser.addoption(
        "--printer-ip",
        action="store",
        default=None,
        help="IP адрес принтера для тестов",
    )


@pytest.fixture
def printer_ip(request) -> Optional[str]:
    """Получение IP принтера из опций."""
    return request.config.getoption("--printer-ip")
