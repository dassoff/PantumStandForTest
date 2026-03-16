"""Сравнительный анализ методов печати."""

import asyncio
import csv
import json
import os
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.printer import FastPrinter, PrintStatus
from utils.helpers import format_bytes, format_duration, generate_test_pdf


@dataclass
class MethodBenchmark:
    """Результаты бенчмарка метода."""

    method: str
    conversion_avg_ms: float = 0
    conversion_min_ms: float = 0
    conversion_max_ms: float = 0
    send_avg_ms: float = 0
    send_min_ms: float = 0
    send_max_ms: float = 0
    total_avg_ms: float = 0
    total_min_ms: float = 0
    total_max_ms: float = 0
    success_rate: float = 0
    throughput_pages_per_min: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "conversion": {
                "avg_ms": round(self.conversion_avg_ms, 2),
                "min_ms": round(self.conversion_min_ms, 2),
                "max_ms": round(self.conversion_max_ms, 2),
            },
            "send": {
                "avg_ms": round(self.send_avg_ms, 2),
                "min_ms": round(self.send_min_ms, 2),
                "max_ms": round(self.send_max_ms, 2),
            },
            "total": {
                "avg_ms": round(self.total_avg_ms, 2),
                "min_ms": round(self.total_min_ms, 2),
                "max_ms": round(self.total_max_ms, 2),
            },
            "success_rate_percent": round(self.success_rate, 2),
            "throughput_pages_per_min": round(self.throughput_pages_per_min, 2),
        }


@dataclass
class BenchmarkReport:
    """Отчёт о бенчмарке."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    printer_ip: Optional[str] = None
    printer_name: str = "Pantum BM5100ADN"
    iterations: int = 1
    file_size: int = 0
    pages: int = 1
    methods: List[MethodBenchmark] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "printer": f"{self.printer_name} @ {self.printer_ip}",
            "iterations": self.iterations,
            "file": {
                "size": self.file_size,
                "size_formatted": format_bytes(self.file_size),
                "pages": self.pages,
            },
            "benchmarks": {m.method: m.to_dict() for m in self.methods},
            "recommendation": self.recommendation,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_csv(self) -> str:
        """Экспорт в CSV формат."""
        lines = []
        lines.append("Method,Conversion Avg (ms),Send Avg (ms),Total Avg (ms),Success Rate (%),Throughput (pages/min)")

        for m in self.methods:
            lines.append(
                f"{m.method},{m.conversion_avg_ms:.2f},{m.send_avg_ms:.2f},"
                f"{m.total_avg_ms:.2f},{m.success_rate:.2f},{m.throughput_pages_per_min:.2f}"
            )

        return "\n".join(lines)

    def generate_table(self) -> str:
        """Генерация сравнительной таблицы."""
        lines = []
        lines.append("")
        lines.append("┌" + "─" * 80 + "┐")
        lines.append("│" + " BENCHMARK RESULTS ".center(80) + "│")
        lines.append("├" + "─" * 80 + "┤")
        lines.append(f"│ Printer: {self.printer_name} @ {self.printer_ip}".ljust(80) + "│")
        lines.append(f"│ File: {format_bytes(self.file_size)}, {self.pages} pages".ljust(80) + "│")
        lines.append(f"│ Iterations: {self.iterations}".ljust(80) + "│")
        lines.append("├" + "─" * 80 + "┤")
        lines.append(
            "│ Method          │ Conv (ms)    │ Send (ms)    │ Total (ms)   │ Success │"
        )
        lines.append("├" + "─" * 80 + "┤")

        for m in self.methods:
            conv = f"{m.conversion_avg_ms:.0f} ({m.conversion_min_ms:.0f}-{m.conversion_max_ms:.0f})"
            send = f"{m.send_avg_ms:.0f} ({m.send_min_ms:.0f}-{m.send_max_ms:.0f})"
            total = f"{m.total_avg_ms:.0f} ({m.total_min_ms:.0f}-{m.total_max_ms:.0f})"
            success = f"{m.success_rate:.1f}%"

            lines.append(
                f"│ {m.method:<15} │ {conv:<13} │ {send:<13} │ {total:<13} │ {success:<7} │"
            )

        lines.append("├" + "─" * 80 + "┤")
        lines.append(f"│ Recommendation: {self.recommendation}".ljust(80) + "│")
        lines.append("└" + "─" * 80 + "┘")
        lines.append("")

        return "\n".join(lines)


class BenchmarkRunner:
    """Запуск бенчмарков."""

    def __init__(
        self,
        printer_ip: Optional[str] = None,
        iterations: int = 5,
        output_dir: Optional[str] = None,
    ):
        """Инициализация бенчмарк раннера."""
        self.printer_ip = printer_ip
        self.iterations = iterations
        self.output_dir = output_dir or "./reports"
        self.printer = FastPrinter(printer_ip=printer_ip)

    async def run_all(self, pages: int = 5) -> BenchmarkReport:
        """Запуск всех бенчмарков."""
        # Создаем тестовый файл
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(temp_path, pages=pages, text="Benchmark Test")

        file_size = os.path.getsize(temp_path)

        try:
            report = BenchmarkReport(
                printer_ip=self.printer_ip,
                iterations=self.iterations,
                file_size=file_size,
                pages=pages,
            )

            # Бенчмарк RAW TCP
            raw_result = await self._benchmark_raw_tcp(temp_path, pages)
            report.methods.append(raw_result)

            # Генерируем рекомендацию
            report.recommendation = self._generate_recommendation(report.methods)

            return report

        finally:
            os.unlink(temp_path)

    async def _benchmark_raw_tcp(
        self,
        file_path: str,
        pages: int,
    ) -> MethodBenchmark:
        """Бенчмарк RAW TCP метода."""
        conversion_times: List[float] = []
        send_times: List[float] = []
        total_times: List[float] = []
        successes = 0

        for i in range(self.iterations):
            try:
                start = time.time()

                # Конвертация
                from core.converters import Converter

                converter = Converter()
                conv_start = time.time()
                pcl_data = await converter.pdf_to_pcl6(file_path)
                conversion_time = (time.time() - conv_start) * 1000
                conversion_times.append(conversion_time)

                # Отправка
                send_start = time.time()
                job = await self.printer.print_pdf_fast(file_path, copies=1, duplex=False)
                send_time = (time.time() - send_start) * 1000
                send_times.append(send_time)

                total_time = (time.time() - start) * 1000
                total_times.append(total_time)

                if job.status == PrintStatus.COMPLETED:
                    successes += 1

            except Exception as e:
                # Записываем таймауты
                conversion_times.append(30000)
                send_times.append(30000)
                total_times.append(30000)

        return MethodBenchmark(
            method="RAW_TCP_PCL6",
            conversion_avg_ms=statistics.mean(conversion_times) if conversion_times else 0,
            conversion_min_ms=min(conversion_times) if conversion_times else 0,
            conversion_max_ms=max(conversion_times) if conversion_times else 0,
            send_avg_ms=statistics.mean(send_times) if send_times else 0,
            send_min_ms=min(send_times) if send_times else 0,
            send_max_ms=max(send_times) if send_times else 0,
            total_avg_ms=statistics.mean(total_times) if total_times else 0,
            total_min_ms=min(total_times) if total_times else 0,
            total_max_ms=max(total_times) if total_times else 0,
            success_rate=(successes / self.iterations) * 100 if self.iterations > 0 else 0,
            throughput_pages_per_min=(pages / (statistics.mean(total_times) / 60000)) if total_times else 0,
        )

    def _generate_recommendation(self, methods: List[MethodBenchmark]) -> str:
        """Генерация рекомендации на основе результатов."""
        if not methods:
            return "No benchmark data available"

        # Находим лучший метод по времени и надёжности
        best_method = None
        best_score = float("inf")

        for m in methods:
            # Score = время + штраф за неудачи
            penalty = (100 - m.success_rate) * 100
            score = m.total_avg_ms + penalty

            if score < best_score:
                best_score = score
                best_method = m

        if best_method:
            if best_method.success_rate >= 90:
                return f"Use {best_method.method} for production"
            else:
                return f"{best_method.method} is fastest but consider fallback (success rate: {best_method.success_rate:.1f}%)"

        return "Review benchmark results manually"

    def save_report(
        self,
        report: BenchmarkReport,
        filename: Optional[str] = None,
        formats: List[str] = ("json", "csv", "table"),
    ) -> Dict[str, str]:
        """Сохранение отчёта."""
        os.makedirs(self.output_dir, exist_ok=True)
        saved_files = {}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if "json" in formats:
            json_path = os.path.join(
                self.output_dir,
                filename or f"benchmark_{timestamp}.json",
            )
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.to_json())
            saved_files["json"] = json_path

        if "csv" in formats:
            csv_path = os.path.join(
                self.output_dir,
                filename or f"benchmark_{timestamp}.csv",
            )
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(report.to_csv())
            saved_files["csv"] = csv_path

        if "table" in formats:
            table_path = os.path.join(
                self.output_dir,
                filename or f"benchmark_{timestamp}.txt",
            )
            with open(table_path, "w", encoding="utf-8") as f:
                f.write(report.generate_table())
            saved_files["table"] = table_path

        return saved_files


async def run_benchmark(
    printer_ip: str,
    iterations: int = 5,
    output_dir: Optional[str] = None,
    pages: int = 5,
) -> BenchmarkReport:
    """Утилита для быстрого запуска бенчмарка."""
    runner = BenchmarkRunner(printer_ip=printer_ip, iterations=iterations, output_dir=output_dir)
    report = await runner.run_all(pages=pages)

    if output_dir:
        runner.save_report(report)

    return report
