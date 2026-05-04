"""Основной класс FastPrinter для печати."""

import asyncio
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiofiles

from .converters import Converter, docx_to_pdf, pdf_to_pcl6
from .network import NetworkPrinter, TCPConnection


class PrintStatus(Enum):
    """Статус задания печати."""

    PENDING = "pending"
    PROCESSING = "processing"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PrintJob:
    """Задание печати."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    file_path: Optional[str] = None
    file_data: Optional[bytes] = None
    file_type: str = "pdf"
    copies: int = 1
    duplex: bool = True
    paper_size: str = "A4"
    status: PrintStatus = PrintStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    method: str = "raw_tcp"
    duration_ms: Optional[int] = None

    def __post_init__(self):
        if self.file_path and not self.file_type:
            ext = Path(self.file_path).suffix.lower()
            self.file_type = ext.lstrip(".")

    @property
    def is_finished(self) -> bool:
        return self.status in (PrintStatus.COMPLETED, PrintStatus.FAILED, PrintStatus.CANCELLED)

    @property
    def elapsed_ms(self) -> Optional[int]:
        if self.started_at is None:
            return None
        end_time = self.completed_at or time.time()
        return int((end_time - self.started_at) * 1000)


class FastPrinter:
    """Основной класс для быстрой печати на Pantum BM5100ADN."""

    # PCL6 команды для Pantum BM5100ADN
    PCL6_COMMANDS = {
        "reset": b"\x1bE",
        "duplex_long": b"\x1b&l1S",
        "duplex_short": b"\x1b&l2S",
        "simplex": b"\x1b&l0S",
        "copies_2": b"\x1b&l2X",
        "a4": b"\x1b&l26A",
        "600dpi": b"\x1b*t600R",
    }

    def __init__(
        self,
        printer_ip: Optional[str] = None,
        printer_port: int = 9100,
        printer_name: Optional[str] = None,
        tcp_timeout: int = 10,
        conversion_timeout: int = 30,
        enable_cache: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Инициализация принтера."""
        self.printer_ip = printer_ip or (config.get("printer", {}).get("ip") if config else None)
        self.printer_port = printer_port or (config.get("printer", {}).get("port", 9100) if config else 9100)
        self.printer_name = printer_name or (config.get("printer", {}).get("name") if config else None) or "Pantum BM5100ADN"
        self.tcp_timeout = tcp_timeout or (config.get("performance", {}).get("tcp_timeout", 10) if config else 10)
        self.conversion_timeout = conversion_timeout or (config.get("performance", {}).get("conversion_timeout", 30) if config else 30)
        self.enable_cache = enable_cache or (config.get("performance", {}).get("enable_cache", True) if config else True)

        self.network_printer = NetworkPrinter(self.printer_ip, self.printer_port, self.tcp_timeout)
        self.converter = Converter(enable_cache=self.enable_cache)
        self._current_job: Optional[PrintJob] = None
        self._job_history: List[PrintJob] = []

    async def flatten_pdf(self, file_path: str, dpi: int = 600) -> str:
        """
        'Сплющивает' PDF, превращая страницы в высококачественные растровые изображения.
        Это значительно ускоряет обработку PDF процессором принтера.
        """
        import fitz
        out_path = str(Path(file_path).with_suffix('.flat.pdf'))
        
        def _flatten():
            src_doc = fitz.open(file_path)
            out_doc = fitz.open()
            
            for page in src_doc:
                # Рендерим страницу в картинку (pixmap)
                pix = page.get_pixmap(dpi=dpi)
                
                # Создаем новую страницу в выходном документе того же размера
                new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                # Вставляем картинку напрямую через pixmap
                new_page.insert_image(new_page.rect, pixmap=pix)
            
            out_doc.save(out_path)
            out_doc.close()
            src_doc.close()
            return out_path

        return await asyncio.to_thread(_flatten)


    @classmethod
    def from_config(cls, config_path: Optional[str] = None) -> "FastPrinter":
        """Создание принтера из конфигурации."""
        if config_path and os.path.exists(config_path):
            import yaml

            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return cls(config=config)
        return cls()

    @classmethod
    def from_env(cls) -> "FastPrinter":
        """Создание принтера из переменных окружения."""
        return cls(
            printer_ip=os.getenv("PRINT_PRINTER_IP"),
            printer_port=int(os.getenv("PRINT_PRINTER_PORT", "9100")),
            tcp_timeout=int(os.getenv("PRINT_TCP_TIMEOUT", "10")),
        )

    async def print_pdf_fast(
        self,
        path: str,
        copies: int = 1,
        duplex: bool = True,
        paper_size: str = "A4",
    ) -> PrintJob:
        """Основной метод: PDF → PCL6 → RAW TCP."""
        job = PrintJob(
            file_path=path,
            file_type="pdf",
            copies=copies,
            duplex=duplex,
            paper_size=paper_size,
            method="raw_tcp",
        )
        return await self._execute_job(job)

    async def print_pdf_stream(
        self,
        data: bytes,
        copies: int = 1,
        duplex: bool = True,
        paper_size: str = "A4",
    ) -> PrintJob:
        """Печать PDF из памяти (без записи на диск)."""
        job = PrintJob(
            file_data=data,
            file_type="pdf",
            copies=copies,
            duplex=duplex,
            paper_size=paper_size,
            method="raw_tcp",
        )
        return await self._execute_job(job)

    async def print_docx_fast(
        self,
        path: str,
        copies: int = 1,
        duplex: bool = True,
        paper_size: str = "A4",
    ) -> PrintJob:
        """DOCX → LibreOffice → PDF → PCL6 → RAW TCP."""
        job = PrintJob(
            file_path=path,
            file_type="docx",
            copies=copies,
            duplex=duplex,
            paper_size=paper_size,
            method="raw_tcp",
        )
        return await self._execute_job(job)

    async def print_pdf_direct_tcp(
        self,
        pdf_path: str,
        copies: int = 1,
        duplex: bool = False,
        job_name: str = "PantumTestJob"
    ) -> PrintJob:
        """Печать PDF напрямую через TCP порт 9100 с PJL именованием."""
        job = PrintJob(
            file_path=pdf_path,
            copies=copies,
            duplex=duplex,
            method="direct_tcp",
        )

        try:
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()

            # PJL заголовок с именем задания
            pjl_header = (
                b"\x1b%-12345X@PJL JOB NAME = \"" + job_name.encode('utf-8') + b"\"\r\n"
                b"@PJL SET COPIES = " + str(copies).encode() + b"\r\n"
                b"@PJL ENTER LANGUAGE = PDF\r\n"
            )
            pjl_footer = b"\x1b%-12345X@PJL EOJ\r\n\x1b%-12345X"

            payload = pjl_header + pdf_data + pjl_footer
            await self.network_printer.send_raw(payload)
            job.status = PrintStatus.COMPLETED
        except Exception as e:
            job.status = PrintStatus.FAILED
            job.error = str(e)

        self._job_history.append(job)
        return job

    async def print_pdf_win32_raw(
        self,
        path: str,
        copies: int = 1,
        duplex: bool = True,
    ) -> PrintJob:
        """Самый быстрый метод 2: Отправка RAW PDF в Windows Spooler.
        Быстрее чем SumatraPDF, так как обходит рендеринг и драйвер.
        """
        job = PrintJob(
            file_path=path,
            file_type="win32_raw",
            copies=copies,
            duplex=duplex,
            method="win32_raw",
        )
        return await self._execute_job(job)

    async def print_raw_pcl(
        self,
        data: Union[bytes, str],
        copies: int = 1,
    ) -> PrintJob:
        """Прямая отправка PCL6 данных на принтер."""
        job = PrintJob(
            file_data=data.encode() if isinstance(data, str) else data,
            file_type="pcl",
            copies=copies,
            method="raw_pcl",
        )
        return await self._execute_job(job)

    async def print_with_fallback(
        self,
        path: str,
        copies: int = 1,
        duplex: bool = True,
    ) -> PrintJob:
        """Печать с цепочкой fallback методов."""
        from .fallback import FallbackChain

        job = PrintJob(
            file_path=path,
            copies=copies,
            duplex=duplex,
            method="fallback",
        )

        job.started_at = time.time()
        self._current_job = job
        job.status = PrintStatus.PROCESSING

        fallback_chain = FallbackChain(printer=self)
        result = await fallback_chain.execute(path, copies, duplex)

        job.completed_at = time.time()
        job.duration_ms = job.elapsed_ms

        if result.success:
            job.status = PrintStatus.COMPLETED
        else:
            job.status = PrintStatus.FAILED
            job.error = result.error

        self._current_job = None
        self._job_history.append(job)

        return job

    async def wake_up(self) -> tuple[bool, str]:
        """
        'Умный' прогрев: отправляет пустую команду, чтобы принтер начал греть печку.
        Лист при этом не печатается.
        """
        if not self.printer_ip:
            return False, "IP не указан"
            
        try:
            # Отправляем только PJL заголовок и команду INFO
            pjl_wake = (
                b"\x1b%-12345X@PJL INFO ID\r\n"
                b"\x1b%-12345X"
            )
            await self.network_printer.send_raw(pjl_wake)
            return True, "Успешно"
        except Exception as e:
            return False, str(e)


    async def _execute_job(self, job: PrintJob) -> PrintJob:
        """Выполнение задания печати."""
        job.started_at = time.time()
        self._current_job = job
        job.status = PrintStatus.PROCESSING

        try:
            if job.file_type == "pdf":
                await self._print_pdf_internal(job)
            elif job.file_type == "pdf_direct":
                await self._print_pdf_direct_internal(job)
            elif job.file_type == "win32_raw":
                await self._print_win32_raw_internal(job)
            elif job.file_type == "docx":
                await self._print_docx_internal(job)
            elif job.file_type == "pcl":
                await self._print_pcl_internal(job)
            else:
                raise ValueError(f"Unsupported file type: {job.file_type}")

            job.status = PrintStatus.COMPLETED

        except asyncio.CancelledError:
            job.status = PrintStatus.CANCELLED
            job.error = "Job cancelled by user"
            raise

        except Exception as e:
            job.status = PrintStatus.FAILED
            job.error = str(e)

        finally:
            job.completed_at = time.time()
            job.duration_ms = job.elapsed_ms
            self._current_job = None
            self._job_history.append(job)

        return job

    async def _print_pdf_internal(self, job: PrintJob) -> None:
        """Внутренний метод печати PDF."""
        if job.file_data:
            # Печать из потока
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(job.file_data)
                temp_path = f.name
            try:
                await self._convert_and_print(temp_path, job)
            finally:
                os.unlink(temp_path)
        else:
            await self._convert_and_print(job.file_path, job)

    async def _convert_and_print(self, pdf_path: str, job: PrintJob) -> None:
        """Конвертация PDF в PCL6 и отправка."""
        job.status = PrintStatus.PRINTING

        # Конвертация PDF → PCL6
        pcl_data = await asyncio.wait_for(
            self.converter.pdf_to_pcl6(
                pdf_path,
                duplex=job.duplex,
                paper_size=job.paper_size,
                copies=job.copies,
            ),
            timeout=self.conversion_timeout,
        )

        # Добавляем PCL команды
        pcl_data = self._build_pcl_command(pcl_data, job)

        # Отправка на принтер
        await self.network_printer.send_raw(pcl_data)

    async def _print_docx_internal(self, job: PrintJob) -> None:
        """Внутренний метод печати DOCX."""
        job.status = PrintStatus.PRINTING

        if job.file_data:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
                f.write(job.file_data)
                docx_path = f.name
            try:
                pdf_path = await asyncio.wait_for(
                    docx_to_pdf(docx_path),
                    timeout=self.conversion_timeout,
                )
                await self._convert_and_print(pdf_path, job)
            finally:
                os.unlink(docx_path)
        else:
            pdf_path = await asyncio.wait_for(
                docx_to_pdf(job.file_path),
                timeout=self.conversion_timeout,
            )
            await self._convert_and_print(pdf_path, job)

    async def _print_pdf_direct_internal(self, job: PrintJob) -> None:
        """Прямая отправка PDF файла на принтер (без конвертации)."""
        job.status = PrintStatus.PRINTING
        
        pdf_data = job.file_data
        if not pdf_data:
            with open(job.file_path, "rb") as f:
                pdf_data = f.read()

        # Оборачиваем в PJL для настройки дуплекса и копий
        pjl = b"\x1b%-12345X@PJL JOB\r\n"
        if job.copies > 1:
            pjl += f"@PJL SET COPIES={job.copies}\r\n".encode()
        if job.duplex:
            pjl += b"@PJL SET DUPLEX=ON\r\n@PJL SET BINDING=LONGEDGE\r\n"
        else:
            pjl += b"@PJL SET DUPLEX=OFF\r\n"
        pjl += b"@PJL ENTER LANGUAGE=PDF\r\n"
        
        footer = b"\x1b%-12345X@PJL EOJ\r\n\x1b%-12345X"
        final_data = pjl + pdf_data + footer
        
        await self.network_printer.send_raw(final_data)

    async def _print_win32_raw_internal(self, job: PrintJob) -> None:
        """Печать RAW PDF через Windows Spooler (pywin32)."""
        import win32print
        
        job.status = PrintStatus.PRINTING
        
        data = job.file_data
        if not data:
            with open(job.file_path, "rb") as f:
                data = f.read()
                
        # Настройка PJL
        pjl = b"\x1b%-12345X@PJL JOB\r\n"
        if job.copies > 1:
            pjl += f"@PJL SET COPIES={job.copies}\r\n".encode()
        if job.duplex:
            pjl += b"@PJL SET DUPLEX=ON\r\n@PJL SET BINDING=LONGEDGE\r\n"
        pjl += b"@PJL ENTER LANGUAGE=PDF\r\n"
        footer = b"\x1b%-12345X@PJL EOJ\r\n\x1b%-12345X"
        
        final_data = pjl + data + footer

        def _print_task():
            hprinter = win32print.OpenPrinter(self.printer_name)
            try:
                win32print.StartDocPrinter(hprinter, 1, ("Pantum Fast PDF Print", None, "RAW"))
                win32print.StartPagePrinter(hprinter)
                win32print.WritePrinter(hprinter, final_data)
                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)

        await asyncio.to_thread(_print_task)

    async def _print_pcl_internal(self, job: PrintJob) -> None:
        """Внутренний метод печати PCL."""
        job.status = PrintStatus.PRINTING

        data = job.file_data
        if data is None:
            raise ValueError("No PCL data provided")

        await self.network_printer.send_raw(data)

    def _build_pcl_command(self, pcl_data: bytes, job: PrintJob) -> bytes:
        """Построение PCL команды с настройками."""
        commands = []

        # Сброс
        commands.append(self.PCL6_COMMANDS["reset"])

        # Дуплекс
        if job.duplex:
            commands.append(self.PCL6_COMMANDS["duplex_long"])
        else:
            commands.append(self.PCL6_COMMANDS["simplex"])

        # Формат бумаги
        if job.paper_size == "A4":
            commands.append(self.PCL6_COMMANDS["a4"])

        # Разрешение
        commands.append(self.PCL6_COMMANDS["600dpi"])

        # Копии
        if job.copies > 1:
            copies_cmd = f"\x1b&l{min(job.copies, 999)}X".encode()
            commands.append(copies_cmd)

        # Данные
        commands.append(pcl_data)

        return b"".join(commands)

    async def get_status(self) -> Dict[str, Any]:
        """Получение статуса принтера."""
        return await self.network_printer.get_status()

    async def cancel_job(self) -> bool:
        """Отмена текущего задания печати."""
        if self._current_job:
            self._current_job.status = PrintStatus.CANCELLED
            self._current_job.error = "Cancelled by user"
            self._current_job = None
            return True
        return False

    def get_job_history(self, limit: int = 10) -> List[PrintJob]:
        """Получение истории заданий."""
        return self._job_history[-limit:]

    def get_current_job(self) -> Optional[PrintJob]:
        """Получение текущего задания."""
        return self._current_job

    async def __aenter__(self) -> "FastPrinter":
        """Контекстный менеджер: вход."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Контекстный менеджер: выход."""
        if self._current_job:
            await self.cancel_job()
