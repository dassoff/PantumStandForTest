#!/usr/bin/env python3
"""
CLI интерфейс для тестового стенда печати Pantum BM5100ADN.

Использование:
    python run_tests.py quick --printer-ip 192.168.1.100
    python run_tests.py full --config ./config/settings.yaml
    python run_tests.py benchmark --iterations 10
    python run_tests.py print ./document.pdf --method raw
    python run_tests.py status
    python run_tests.py clean
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.printer import FastPrinter, PrintStatus
from core.network import NetworkPrinter
from benchmarks.runner import BenchmarkRunner
from config.validator import ConfigValidator, validate_config
from utils.helpers import format_bytes, format_duration, generate_test_pdf, generate_test_docx
from utils.logger import setup_logger, get_logger


console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="Print Test Stand")
def cli():
    """Тестовый стенд для валидации сценариев печати Pantum BM5100ADN."""
    pass


@cli.command()
@click.option("--printer-ip", "-ip", default=None, help="IP адрес принтера")
@click.option("--config", "-c", default="./config/settings.yaml", help="Путь к конфигурации")
@click.option("--report", "-r", default="./reports", help="Директория для отчётов")
def quick(printer_ip: Optional[str], config: str, report: str):
    """Быстрый тест печати."""
    console.print("[bold blue]🚀 Запуск быстрого теста печати[/bold blue]\n")

    # Загружаем конфигурацию если есть
    if os.path.exists(config):
        try:
            validator = ConfigValidator(config)
            config_data = validator.load()
            if validator.validate(config_data):
                if not printer_ip:
                    printer_ip = validator.get_config().printer.ip
                console.print(f"[green]✓[/green] Конфигурация загружена: {config}")
        except Exception as e:
            console.print(f"[yellow]⚠ Конфигурация не загружена: {e}[/yellow]")

    if not printer_ip:
        console.print("[yellow]⚠ Printer IP не указан. Используем из конфигурации или default.[/yellow]\n")

    async def run_test():
        printer = FastPrinter(printer_ip=printer_ip)

        # Создаем тестовый PDF
        fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(temp_path, pages=1, text="Quick Test Print")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                # Проверка статуса
                progress.add_task("Проверка принтера...", total=None)
                status = await printer.get_status()

                if status.online:
                    console.print("[green]✓[/green] Принтер онлайн")
                else:
                    console.print("[red]✗[/red] Принтер оффлайн")
                    if status.error_message:
                        console.print(f"  {status.error_message}")

                # Печать
                progress.add_task("Печать тестовой страницы...", total=None)
                start_time = datetime.now()

                job = await printer.print_pdf_fast(temp_path, copies=1, duplex=False)

                duration = (datetime.now() - start_time).total_seconds() * 1000

                if job.status == PrintStatus.COMPLETED:
                    console.print(f"[green]✓[/green] Печать завершена за {format_duration(int(duration))}")
                    console.print(f"  Job ID: {job.job_id}")
                else:
                    console.print(f"[red]✗[/red] Ошибка печати: {job.error}")

        finally:
            os.unlink(temp_path)

        # Сохраняем отчёт
        os.makedirs(report, exist_ok=True)
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "printer_ip": printer_ip,
            "test": "quick",
            "status": "passed" if job.status == PrintStatus.COMPLETED else "failed",
            "duration_ms": int(duration),
        }

        report_path = os.path.join(report, "quick_test_report.json")
        with open(report_path, "w") as f:
            json.dump(report_data, f, indent=2)

        console.print(f"\n[green]✓[/green] Отчёт сохранён: {report_path}")

        return job.status == PrintStatus.COMPLETED

    result = asyncio.run(run_test())
    sys.exit(0 if result else 1)


@cli.command()
@click.option("--config", "-c", default="./config/settings.yaml", help="Путь к конфигурации")
@click.option("--report", "-r", default="./reports", help="Директория для отчётов")
@click.option("--printer-ip", "-ip", default=None, help="IP адрес принтера")
def full(config: str, report: str, printer_ip: Optional[str]):
    """Полное тестирование всех сценариев."""
    console.print("[bold blue]📋 Запуск полного тестирования[/bold blue]\n")

    # Загружаем конфигурацию
    if not os.path.exists(config):
        console.print(f"[red]✗[/red] Конфигурация не найдена: {config}")
        sys.exit(1)

    try:
        validator = ConfigValidator(config)
        config_data = validator.load()
        if not validator.validate(config_data):
            console.print("[red]✗[/red] Ошибки валидации конфигурации:")
            for error in validator.errors:
                console.print(f"  - {error}")
            sys.exit(1)

        cfg = validator.get_config()
        if not printer_ip:
            printer_ip = cfg.printer.ip
    except Exception as e:
        console.print(f"[red]✗[/red] Ошибка загрузки конфигурации: {e}")
        sys.exit(1)

    async def run_full_tests():
        printer = FastPrinter(printer_ip=printer_ip)
        results = {
            "timestamp": datetime.now().isoformat(),
            "printer_ip": printer_ip,
            "tests": [],
            "passed": 0,
            "failed": 0,
        }

        os.makedirs(report, exist_ok=True)

        test_cases = [
            ("PDF 1 страница", lambda: printer.print_pdf_fast(_create_test_pdf(1), copies=1, duplex=False)),
            ("PDF 5 страниц", lambda: printer.print_pdf_fast(_create_test_pdf(5), copies=1, duplex=False)),
            ("PDF 10 страниц", lambda: printer.print_pdf_fast(_create_test_pdf(10), copies=1, duplex=False)),
            ("PDF дуплекс", lambda: printer.print_pdf_fast(_create_test_pdf(3), copies=1, duplex=True)),
            ("PDF 2 копии", lambda: printer.print_pdf_fast(_create_test_pdf(1), copies=2, duplex=False)),
            ("DOCX простой", lambda: printer.print_docx_fast(_create_test_docx(1), copies=1, duplex=False)),
        ]

        for test_name, test_func in test_cases:
            console.print(f"\n[bold]Тест: {test_name}[/bold]")

            try:
                start = datetime.now()
                job = await test_func()
                duration = (datetime.now() - start).total_seconds() * 1000

                if job.status == PrintStatus.COMPLETED:
                    console.print(f"  [green]✓[/green] Пройден за {format_duration(int(duration))}")
                    results["tests"].append({"name": test_name, "status": "passed", "duration_ms": int(duration)})
                    results["passed"] += 1
                else:
                    console.print(f"  [red]✗[/red] Не пройден: {job.error}")
                    results["tests"].append({"name": test_name, "status": "failed", "error": job.error})
                    results["failed"] += 1

            except Exception as e:
                console.print(f"  [red]✗[/red] Ошибка: {e}")
                results["tests"].append({"name": test_name, "status": "failed", "error": str(e)})
                results["failed"] += 1

        # Статус принтера
        console.print("\n[bold]Статус принтера[/bold]")
        status = await printer.get_status()
        console.print(f"  Онлайн: {'[green]Да[/green]' if status.online else '[red]Нет[/red]'}")
        console.print(f"  Готов: {'[green]Да[/green]' if status.ready else '[yellow]Нет[/yellow]'}")

        # Сохраняем отчёт
        report_path = os.path.join(report, "full_test_report.json")
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)

        # Выводим сводку
        console.print(f"\n[bold]Сводка[/bold]")
        console.print(f"  Пройдено: [green]{results['passed']}[/green]")
        console.print(f"  Не пройдено: [red]{results['failed']}[/red]")
        console.print(f"  Отчёт: {report_path}")

        return results["failed"] == 0

    def _create_test_pdf(pages: int) -> str:
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        generate_test_pdf(path, pages=pages, text="Full Test")
        return path

    def _create_test_docx(pages: int) -> str:
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        generate_test_docx(path, pages=pages, text="Full Test")
        return path

    result = asyncio.run(run_full_tests())
    sys.exit(0 if result else 1)


@cli.command()
@click.option("--printer-ip", "-ip", required=True, help="IP адрес принтера")
@click.option("--iterations", "-n", default=5, help="Количество итераций")
@click.option("--output", "-o", default="json", type=click.Choice(["json", "csv", "table"]), help="Формат вывода")
@click.option("--report-dir", "-r", default="./reports", help="Директория для отчётов")
def benchmark(printer_ip: str, iterations: int, output: str, report_dir: str):
    """Бенчмарк производительности."""
    console.print(f"[bold blue]📊 Запуск бенчмарка ({iterations} итераций)[/bold blue]\n")

    async def run_benchmark():
        runner = BenchmarkRunner(printer_ip=printer_ip, iterations=iterations, output_dir=report_dir)
        report = await runner.run_all(pages=5)

        # Выводим результаты
        if output == "table":
            console.print(report.generate_table())
        elif output == "json":
            console.print(report.to_json())
        else:
            console.print(report.to_csv())

        # Сохраняем
        saved = runner.save_report(report, formats=["json", "csv", "table"])
        console.print(f"\n[green]✓[/green] Отчёты сохранены:")
        for fmt, path in saved.items():
            console.print(f"  {fmt}: {path}")

        return report

    asyncio.run(run_benchmark())


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--method", "-m", default="raw", type=click.Choice(["raw", "fallback"]), help="Метод печати")
@click.option("--copies", "-c", default=1, help="Количество копий")
@click.option("--duplex", "-d", is_flag=True, help="Двусторонняя печать")
@click.option("--printer-ip", "-ip", default=None, help="IP адрес принтера")
def print_file(file_path: str, method: str, copies: int, duplex: bool, printer_ip: Optional[str]):
    """Печать конкретного файла."""
    console.print(f"[bold blue]🖨️ Печать файла: {file_path}[/bold blue]\n")

    async def do_print():
        printer = FastPrinter(printer_ip=printer_ip)

        start = datetime.now()

        if method == "raw":
            if file_path.lower().endswith(".pdf"):
                job = await printer.print_pdf_fast(file_path, copies=copies, duplex=duplex)
            elif file_path.lower().endswith(".docx"):
                job = await printer.print_docx_fast(file_path, copies=copies, duplex=duplex)
            else:
                console.print("[red]✗[/red] Неподдерживаемый формат файла")
                return False
        else:
            job = await printer.print_with_fallback(file_path, copies=copies, duplex=duplex)

        duration = (datetime.now() - start).total_seconds() * 1000

        if job.status == PrintStatus.COMPLETED:
            console.print(f"[green]✓[/green] Печать завершена за {format_duration(int(duration))}")
            console.print(f"  Job ID: {job.job_id}")
            return True
        else:
            console.print(f"[red]✗[/red] Ошибка: {job.error}")
            return False

    result = asyncio.run(do_print())
    sys.exit(0 if result else 1)


@cli.command()
@click.option("--printer-ip", "-ip", default=None, help="IP адрес принтера")
@click.option("--verbose", "-v", is_flag=True, help="Подробный вывод")
def status(printer_ip: Optional[str], verbose: bool):
    """Проверка статуса принтера."""
    console.print("[bold blue]📡 Проверка статуса принтера[/bold blue]\n")

    async def check_status():
        printer = FastPrinter(printer_ip=printer_ip)
        status = await printer.get_status()

        table = Table(title="Статус принтера")
        table.add_column("Параметр", style="cyan")
        table.add_column("Значение", style="green")

        table.add_row("Принтер", printer.printer_name)
        table.add_row("IP", printer.printer_ip or "Не указан")
        table.add_row("Порт", str(printer.printer_port))
        table.add_row("Онлайн", "[green]Да[/green]" if status.online else "[red]Нет[/red]")
        table.add_row("Готов", "[green]Да[/green]" if status.ready else "[yellow]Нет[/yellow]")

        if verbose and status.snmp_data:
            for key, value in status.snmp_data.items():
                table.add_row(key.capitalize(), str(value))

        if status.error_message:
            table.add_row("Ошибка", f"[red]{status.error_message}[/red]")

        console.print(table)

        return status.online

    result = asyncio.run(check_status())
    sys.exit(0 if result else 1)


@cli.command()
@click.option("--temp-dir", "-t", default=None, help="Директория для очистки")
@click.option("--older-than", "-o", default=1, help="Возраст файлов в часах")
def clean(temp_dir: Optional[str], older_than: int):
    """Очистка временных файлов."""
    console.print("[bold blue]🧹 Очистка временных файлов[/bold blue]\n")

    from utils.helpers import cleanup_temp

    removed = cleanup_temp(temp_dir, older_than_hours=older_than)

    console.print(f"[green]✓[/green] Удалено файлов: {removed}")


@cli.command()
@click.option("--config", "-c", default="./config/settings.yaml", help="Путь к конфигурации")
def validate(config: str):
    """Валидация конфигурации."""
    console.print("[bold blue]✅ Валидация конфигурации[/bold blue]\n")

    if not os.path.exists(config):
        console.print(f"[red]✗[/red] Файл не найден: {config}")
        sys.exit(1)

    result = validate_config(config)

    if result["valid"]:
        console.print("[green]✓[/green] Конфигурация валидна")
    else:
        console.print("[red]✗[/red] Ошибки валидации:")
        for error in result["errors"]:
            console.print(f"  - {error}")

    if result["warnings"]:
        console.print("\n[yellow]⚠ Предупреждения:[/yellow]")
        for warning in result["warnings"]:
            console.print(f"  - {warning}")

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    cli()
