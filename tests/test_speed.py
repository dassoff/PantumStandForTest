"""Тесты скорости и бенчмарки."""

import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from core.printer import FastPrinter, PrintStatus
from utils.helpers import format_bytes, format_duration, generate_test_pdf


@dataclass
class BenchmarkResult:
    """Результат бенчмарка."""

    method: str
    file_size: int
    pages: int
    duration_ms: int
    success: bool
    error: Optional[str] = None

    @property
    def throughput_pages_per_min(self) -> float:
        if self.duration_ms == 0:
            return 0.0
        return (self.pages / self.duration_ms) * 60000

    @property
    def throughput_mb_per_min(self) -> float:
        if self.duration_ms == 0:
            return 0.0
        return (self.file_size / (1024 * 1024)) / (self.duration_ms / 60000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "file_size": self.file_size,
            "file_size_formatted": format_bytes(self.file_size),
            "pages": self.pages,
            "duration_ms": self.duration_ms,
            "duration_formatted": format_duration(self.duration_ms),
            "success": self.success,
            "error": self.error,
            "throughput_pages_per_min": round(self.throughput_pages_per_min, 2),
            "throughput_mb_per_min": round(self.throughput_mb_per_min, 4),
        }


class TestSpeedBenchmark:
    """Бенчмарки скорости печати."""

    @pytest.fixture
    def printer(self, printer_ip: Optional[str] = None) -> FastPrinter:
        """Создание экземпляра принтера."""
        return FastPrinter(printer_ip=printer_ip)

    @pytest.fixture
    def test_files(self) -> Dict[str, str]:
        """Создание тестовых файлов разного размера."""
        files = {}

        # 1 страница
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=1, text="Benchmark - 1 page")
        files["1_page"] = path

        # 5 страниц
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=5, text="Benchmark - 5 pages")
        files["5_pages"] = path

        # 10 страниц
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=10, text="Benchmark - 10 pages")
        files["10_pages"] = path

        yield files

        # Очистка
        for path in files.values():
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_raw_tcp_speed_1_page(
        self,
        printer: FastPrinter,
        test_files: Dict[str, str],
        printer_ip: Optional[str],
    ) -> BenchmarkResult:
        """Бенчмарк RAW TCP для 1 страницы."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        file_path = test_files["1_page"]
        file_size = os.path.getsize(file_path)

        start = time.time()
        job = await printer.print_pdf_fast(file_path, copies=1, duplex=False)
        duration_ms = int((time.time() - start) * 1000)

        result = BenchmarkResult(
            method="raw_tcp",
            file_size=file_size,
            pages=1,
            duration_ms=duration_ms,
            success=job.status == PrintStatus.COMPLETED,
            error=job.error,
        )

        return result

    @pytest.mark.asyncio
    async def test_raw_tcp_speed_5_pages(
        self,
        printer: FastPrinter,
        test_files: Dict[str, str],
        printer_ip: Optional[str],
    ) -> BenchmarkResult:
        """Бенчмарк RAW TCP для 5 страниц."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        file_path = test_files["5_pages"]
        file_size = os.path.getsize(file_path)

        start = time.time()
        job = await printer.print_pdf_fast(file_path, copies=1, duplex=False)
        duration_ms = int((time.time() - start) * 1000)

        result = BenchmarkResult(
            method="raw_tcp",
            file_size=file_size,
            pages=5,
            duration_ms=duration_ms,
            success=job.status == PrintStatus.COMPLETED,
            error=job.error,
        )

        return result

    @pytest.mark.asyncio
    async def test_raw_tcp_speed_10_pages(
        self,
        printer: FastPrinter,
        test_files: Dict[str, str],
        printer_ip: Optional[str],
    ) -> BenchmarkResult:
        """Бенчмарк RAW TCP для 10 страниц."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        file_path = test_files["10_pages"]
        file_size = os.path.getsize(file_path)

        start = time.time()
        job = await printer.print_pdf_fast(file_path, copies=1, duplex=False)
        duration_ms = int((time.time() - start) * 1000)

        result = BenchmarkResult(
            method="raw_tcp",
            file_size=file_size,
            pages=10,
            duration_ms=duration_ms,
            success=job.status == PrintStatus.COMPLETED,
            error=job.error,
        )

        return result

    @pytest.mark.asyncio
    async def test_duplex_vs_simplex_speed(
        self,
        printer: FastPrinter,
        test_files: Dict[str, str],
        printer_ip: Optional[str],
    ) -> Dict[str, BenchmarkResult]:
        """Сравнение скорости дуплекса и симплекса."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        file_path = test_files["5_pages"]

        # Симплекс
        start = time.time()
        job_simplex = await printer.print_pdf_fast(file_path, copies=1, duplex=False)
        simplex_ms = int((time.time() - start) * 1000)

        # Дуплекс
        start = time.time()
        job_duplex = await printer.print_pdf_fast(file_path, copies=1, duplex=True)
        duplex_ms = int((time.time() - start) * 1000)

        return {
            "simplex": BenchmarkResult(
                method="simplex",
                file_size=os.path.getsize(file_path),
                pages=5,
                duration_ms=simplex_ms,
                success=job_simplex.status == PrintStatus.COMPLETED,
            ),
            "duplex": BenchmarkResult(
                method="duplex",
                file_size=os.path.getsize(file_path),
                pages=5,
                duration_ms=duplex_ms,
                success=job_duplex.status == PrintStatus.COMPLETED,
            ),
        }

    @pytest.mark.asyncio
    async def test_concurrent_printing(
        self,
        printer: FastPrinter,
        test_files: Dict[str, str],
        printer_ip: Optional[str],
    ) -> Dict[str, Any]:
        """Тест параллельной печати."""
        if not printer_ip:
            pytest.skip("Printer IP not specified")

        import asyncio

        file_path = test_files["1_page"]

        # Запускаем 5 заданий параллельно
        start = time.time()
        tasks = [
            printer.print_pdf_fast(file_path, copies=1, duplex=False)
            for _ in range(5)
        ]
        jobs = await asyncio.gather(*tasks, return_exceptions=True)
        total_ms = int((time.time() - start) * 1000)

        successes = sum(
            1 for j in jobs if isinstance(j, type(printer.get_current_job())) and j.status == PrintStatus.COMPLETED
        )

        return {
            "concurrent_jobs": 5,
            "total_duration_ms": total_ms,
            "successful": successes,
            "failed": 5 - successes,
            "avg_duration_ms": total_ms / 5 if successes > 0 else total_ms,
        }

    @pytest.mark.asyncio
    async def test_conversion_time(
        self,
        test_files: Dict[str, str],
    ) -> Dict[str, int]:
        """Измерение времени конвертации PDF → PCL6."""
        from core.converters import Converter

        converter = Converter()
        file_path = test_files["5_pages"]

        # Замеряем время конвертации
        start = time.time()
        pcl_data = await converter.pdf_to_pcl6(file_path)
        conversion_ms = int((time.time() - start) * 1000)

        return {
            "file_size": os.path.getsize(file_path),
            "pcl_size": len(pcl_data),
            "conversion_ms": conversion_ms,
        }


def run_benchmark_suite(
    printer_ip: str,
    iterations: int = 3,
) -> Dict[str, Any]:
    """Запуск полного набора бенчмарков."""
    import asyncio
    import statistics

    async def run():
        results = {
            "raw_tcp": [],
            "duplex_vs_simplex": None,
            "concurrent": None,
        }

        printer = FastPrinter(printer_ip=printer_ip)

        # Создаем тестовые файлы
        test_files = {}
        for pages in [1, 5, 10]:
            fd, path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            generate_test_pdf(path, pages=pages, text=f"Benchmark {pages} pages")
            test_files[f"{pages}_pages"] = path

        try:
            # RAW TCP бенчмарки
            for pages in [1, 5, 10]:
                file_path = test_files[f"{pages}_pages"]
                file_size = os.path.getsize(file_path)

                durations = []
                for _ in range(iterations):
                    start = time.time()
                    job = await printer.print_pdf_fast(file_path, copies=1, duplex=False)
                    duration_ms = int((time.time() - start) * 1000)

                    if job.status == PrintStatus.COMPLETED:
                        durations.append(duration_ms)

                if durations:
                    results["raw_tcp"].append({
                        "pages": pages,
                        "file_size": file_size,
                        "avg_ms": statistics.mean(durations),
                        "min_ms": min(durations),
                        "max_ms": max(durations),
                        "success_rate": len(durations) / iterations * 100,
                    })

            # Дуплекс vs Симплекс
            file_path = test_files["5_pages"]

            simplex_times = []
            duplex_times = []

            for _ in range(iterations):
                start = time.time()
                job = await printer.print_pdf_fast(file_path, copies=1, duplex=False)
                if job.status == PrintStatus.COMPLETED:
                    simplex_times.append(int((time.time() - start) * 1000))

                start = time.time()
                job = await printer.print_pdf_fast(file_path, copies=1, duplex=True)
                if job.status == PrintStatus.COMPLETED:
                    duplex_times.append(int((time.time() - start) * 1000))

            results["duplex_vs_simplex"] = {
                "simplex_avg_ms": statistics.mean(simplex_times) if simplex_times else 0,
                "duplex_avg_ms": statistics.mean(duplex_times) if duplex_times else 0,
            }

        finally:
            # Очистка
            for path in test_files.values():
                os.unlink(path)

        return results

    return asyncio.run(run())
