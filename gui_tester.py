"""
Advanced Print Tester for Pantum BP5100DW.
Refactored using SOLID principles, type hinting, and separated concerns.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import asyncio
import os
import time
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Callable, Tuple, Optional

try:
    import win32print
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

from core.printer import FastPrinter
from core.converters import docx_to_pdf
from core.fallback import FallbackChain

CONFIG_FILE = "tester_config.json"


@dataclass
class AppConfig:
    """Model for application configuration."""
    ip: str = "192.168.1.100"
    win_printer: str = ""


class ConfigManager:
    """Handles loading and saving the application configuration."""
    
    @staticmethod
    def load() -> AppConfig:
        if not os.path.exists(CONFIG_FILE):
            return AppConfig()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return AppConfig(**data)
        except Exception as e:
            logging.error(f"Failed to load config: {e}")
            return AppConfig()

    @staticmethod
    def save(config: AppConfig) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(asdict(config), f, indent=4)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")


class FileConverter:
    """Handles conversion of various file types to PDF."""
    
    SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
    
    @staticmethod
    async def convert_to_pdf(file_path: str) -> str:
        """Converts a given file to PDF based on its extension."""
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return file_path
            
        if ext == ".docx":
            return await docx_to_pdf(file_path)
            
        if ext in FileConverter.SUPPORTED_IMAGE_EXTENSIONS:
            return await asyncio.to_thread(FileConverter._convert_image, file_path)
            
        if ext == ".txt":
            return await asyncio.to_thread(FileConverter._convert_text, file_path)
            
        raise ValueError(f"Неизвестный или неподдерживаемый формат: {ext}")

    @staticmethod
    def _convert_image(file_path: str) -> str:
        from PIL import Image
        out_path = str(Path(file_path).with_suffix('.pdf'))
        with Image.open(file_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(out_path, "PDF", resolution=300.0)
        return out_path

    @staticmethod
    def _convert_text(file_path: str) -> str:
        from PIL import Image, ImageDraw, ImageFont
        out_path = str(Path(file_path).with_suffix('.pdf'))
        # A4 size at 300dpi
        img = Image.new('RGB', (2480, 3508), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
            
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except IOError:
            font = ImageFont.load_default()
            
        d.text((100, 100), text, fill=(0, 0, 0), font=font)
        img.save(out_path, "PDF", resolution=300.0)
        return out_path


class PrintTestingService:
    """Service to handle the execution of different print methods."""
    
    def __init__(self, logger_callback: Callable[[str, str], None]):
        self.log = logger_callback

    async def execute_all_tests(self, file_path: str, ip: str, win_printer: str) -> None:
        """Executes all print strategies sequentially."""
        try:
            # 1. Preparation
            pdf_path = await self._prepare_pdf(file_path)
            if not pdf_path:
                return

            # 2. Printer Initialization
            printer = FastPrinter(printer_ip=ip, printer_name=win_printer, printer_port=9100)

            # 3. Define Strategies
            strategies = [
                ("Прямая TCP печать RAW PDF (Сетевой)", self._test_direct_tcp),
                ("Windows RAW Spooler (Локальный)", self._test_win32_raw),
                ("SumatraPDF (Продакшен метод)", self._test_sumatra),
                ("PCL6 по TCP (Резервный конвертер)", self._test_pcl6_tcp)
            ]

            # 4. Execute Strategies
            for index, (name, strategy_func) in enumerate(strategies):
                self.log(f"▶ ЗАПУСК: {name}", "header")
                await self._run_single_strategy(strategy_func, printer, pdf_path)

                if index < len(strategies) - 1:
                    self.log("  ⏳ Ожидание 8 секунд для очистки памяти принтера...\n", "warning")
                    await asyncio.sleep(8)

        except Exception as e:
            self.log(f"\nКРИТИЧЕСКАЯ ОШИБКА ТЕСТИРОВАНИЯ: {e}", "error")

    async def _prepare_pdf(self, file_path: str) -> Optional[str]:
        ext = Path(file_path).suffix.lower()
        if ext != ".pdf":
            self.log(f"[Подготовка] Конвертация {ext} в PDF через PyMuPDF (flash speed)...", "warning")
            try:
                from core.converters import image_to_pdf, text_to_pdf
                if ext in FileConverter.SUPPORTED_IMAGE_EXTENSIONS:
                    pdf_path = await image_to_pdf(file_path)
                elif ext == ".txt":
                    pdf_path = await text_to_pdf(file_path)
                else:
                    pdf_path = await FileConverter.convert_to_pdf(file_path)
                
                self.log(f"[Подготовка] Успешно: {os.path.basename(pdf_path)}\n", "success")
                return pdf_path
            except Exception as e:
                self.log(f"[Подготовка] ОШИБКА: {e}", "error")
                return None
        return file_path

    async def _run_single_strategy(self, strategy: Callable, printer: FastPrinter, pdf_path: str) -> None:
        t0 = time.time()
        try:
            success, msg = await strategy(printer, pdf_path)
            t_elapsed = time.time() - t0
            if success:
                self.log(f"  └─ [V] УСПЕХ: {msg} (Заняло {t_elapsed:.3f} сек.)\n", "success")
            else:
                self.log(f"  └─ [X] ОШИБКА: {msg} (Заняло {t_elapsed:.3f} сек.)\n", "error")
        except Exception as e:
            t_elapsed = time.time() - t0
            self.log(f"  └─ [!] СБОЙ: {str(e)} (Заняло {t_elapsed:.3f} сек.)\n", "error")

    # --- Print Strategies ---

    async def _test_direct_tcp(self, printer: FastPrinter, pdf_path: str) -> Tuple[bool, str]:
        if not printer.printer_ip or printer.printer_ip == "0.0.0.0":
            return False, "Не указан корректный IP принтера."
        job = await printer.print_pdf_direct_tcp(pdf_path, copies=1, duplex=False)
        if job.status.value == "completed":
            return True, "Отправлено на TCP порт 9100 напрямую."
        return False, job.error or "Неизвестная ошибка отправки"

    async def _test_win32_raw(self, printer: FastPrinter, pdf_path: str) -> Tuple[bool, str]:
        if not WIN32_AVAILABLE:
            return False, "Библиотека pywin32 не установлена."
        if not printer.printer_name:
            return False, "Не выбран Windows-принтер."
        job = await printer.print_pdf_win32_raw(pdf_path, copies=1, duplex=False)
        if job.status.value == "completed":
            return True, "Отправлено в очередь Windows Spooler как RAW."
        return False, job.error or "Неизвестная ошибка отправки"

    async def _test_sumatra(self, printer: FastPrinter, pdf_path: str) -> Tuple[bool, str]:
        chain = FallbackChain(printer=printer)
        result = await chain._try_sumatra(pdf_path, copies=1)
        if result.success:
            return True, "Успешно отправлено через процесс SumatraPDF."
        return False, result.error or "SumatraPDF не установлена или вернула ошибку."

    async def _test_pcl6_tcp(self, printer: FastPrinter, pdf_path: str) -> Tuple[bool, str]:
        if not printer.printer_ip or printer.printer_ip == "0.0.0.0":
            return False, "Не указан корректный IP принтера."
        job = await printer.print_pdf_fast(pdf_path, copies=1, duplex=False)
        if job.status.value == "completed":
            return True, "Отправлено на TCP порт 9100 после конвертации в PCL6."
        return False, job.error or "Неизвестная ошибка отправки"


class PrintTesterApp(tk.Tk):
    """Main GUI Application View and Controller."""
    
    def __init__(self):
        super().__init__()
        self.title("Pantum BP5100DW - Advanced Print Tester")
        self.geometry("850x700")
        self.minsize(750, 600)
        
        self.config = ConfigManager.load()
        self.print_service = PrintTestingService(logger_callback=self.safe_log)
        
        self._setup_variables()
        self._setup_styles()
        self._create_widgets()
        self._load_printers()

    def _setup_variables(self) -> None:
        self.selected_file = tk.StringVar()
        self.printer_ip = tk.StringVar(value=self.config.ip)
        self.selected_win_printer = tk.StringVar(value=self.config.win_printer)

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
            
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=10)

    def _create_widgets(self) -> None:
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill="both", expand=True)

        self._create_file_section(main_frame)
        self._create_printer_section(main_frame)
        self._create_action_section(main_frame)
        self._create_log_section(main_frame)

    def _create_file_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text=" 1. Выбор файла (PDF, DOCX, TXT, IMG) ", padding="10")
        frame.pack(fill="x", pady=(0, 15))
        ttk.Entry(frame, textvariable=self.selected_file, state="readonly").pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Button(frame, text="Обзор...", command=self.browse_file, width=15).pack(side="right")

    def _create_printer_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text=" 2. Настройки принтера ", padding="10")
        frame.pack(fill="x", pady=(0, 15))
        frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text="IP-адрес (TCP 9100):").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.printer_ip).grid(row=0, column=1, sticky="we", pady=5, padx=(10, 0))
        
        ttk.Label(frame, text="Windows Принтер:").grid(row=1, column=0, sticky="w", pady=5)
        self.cb_printers = ttk.Combobox(frame, textvariable=self.selected_win_printer, state="readonly")
        self.cb_printers.grid(row=1, column=1, sticky="we", pady=5, padx=(10, 0))

    def _create_action_section(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(5, 15))
        
        self.btn_test = ttk.Button(frame, text="🚀 ЗАПУСТИТЬ ТЕСТИРОВАНИЕ МЕТОДОВ", style="Action.TButton", command=self.start_testing)
        self.btn_test.pack(fill="x", pady=(0, 10))
        self.progress = ttk.Progressbar(frame, mode="indeterminate")

    def _create_log_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text=" Журнал тестирования ", padding="10")
        frame.pack(fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        
        self.txt_logs = tk.Text(
            frame, state="disabled", wrap="word", yscrollcommand=scrollbar.set, 
            font=("Consolas", 10), bg="#1E1E1E", fg="#D4D4D4", relief="flat"
        )
        self.txt_logs.pack(fill="both", expand=True)
        scrollbar.config(command=self.txt_logs.yview)

        # Log tags
        self.txt_logs.tag_config("info", foreground="#9CDCFE")
        self.txt_logs.tag_config("success", foreground="#4CAF50", font=("Consolas", 10, "bold"))
        self.txt_logs.tag_config("error", foreground="#F44336", font=("Consolas", 10, "bold"))
        self.txt_logs.tag_config("warning", foreground="#CE9178")
        self.txt_logs.tag_config("header", foreground="#DCDCAA", font=("Consolas", 10, "bold"))

    def _load_printers(self) -> None:
        if not WIN32_AVAILABLE:
            self.cb_printers['values'] = ["win32print недоступен"]
            self.cb_printers.current(0)
            return

        try:
            printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
            printer_names = sorted([p[2] for p in printers])
            self.cb_printers['values'] = printer_names
            
            saved_printer = self.config.win_printer
            if saved_printer in printer_names:
                self.cb_printers.set(saved_printer)
            elif printer_names:
                self.cb_printers.current(0)
        except Exception as e:
            self.cb_printers['values'] = [f"Ошибка загрузки: {e}"]
            self.cb_printers.current(0)

    def browse_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Выберите файл для печати",
            filetypes=[
                ("Поддерживаемые форматы", "*.pdf *.docx *.txt *.png *.jpg *.jpeg"),
                ("PDF документы", "*.pdf"),
                ("Word документы", "*.docx"),
                ("Изображения", "*.png *.jpg *.jpeg"),
                ("Текстовые файлы", "*.txt")
            ]
        )
        if filename:
            self.selected_file.set(filename)

    def safe_log(self, message: str, level: str = "info") -> None:
        """Thread-safe logging to the GUI Text widget."""
        self.after(0, self._log_insert, message, level)

    def _log_insert(self, message: str, level: str) -> None:
        self.txt_logs.config(state="normal")
        self.txt_logs.insert(tk.END, message + "\n", level)
        self.txt_logs.see(tk.END)
        self.txt_logs.config(state="disabled")

    def start_testing(self) -> None:
        file_path = self.selected_file.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("Внимание", "Пожалуйста, сначала выберите существующий файл!")
            return
            
        # Update config
        self.config.ip = self.printer_ip.get().strip()
        self.config.win_printer = self.selected_win_printer.get().strip()
        ConfigManager.save(self.config)
        
        # UI updates
        self.btn_test.config(state="disabled", text="⏳ ИДЕТ ТЕСТИРОВАНИЕ...")
        self.progress.pack(fill="x", pady=(0, 10))
        self.progress.start(15)
        
        self.txt_logs.config(state="normal")
        self.txt_logs.delete(1.0, tk.END)
        self.txt_logs.config(state="disabled")
        
        self.safe_log(f"{'='*60}", "header")
        self.safe_log(f"🕒 НАЧАЛО ТЕСТИРОВАНИЯ: {time.strftime('%H:%M:%S')}", "header")
        self.safe_log(f"📄 Файл: {os.path.basename(file_path)}", "info")
        self.safe_log(f"🌐 TCP IP: {self.config.ip}", "info")
        self.safe_log(f"🖨️ Win Принтер: {self.config.win_printer}", "info")
        self.safe_log(f"{'='*60}\n", "header")
        
        threading.Thread(target=self._test_runner, daemon=True).start()

    def _test_runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self.print_service.execute_all_tests(
                    file_path=self.selected_file.get(),
                    ip=self.config.ip,
                    win_printer=self.config.win_printer
                )
            )
        finally:
            loop.close()
            self.after(0, self._finish_testing)

    def _finish_testing(self) -> None:
        self.progress.stop()
        self.progress.pack_forget()
        self.btn_test.config(state="normal", text="🚀 ЗАПУСТИТЬ ТЕСТИРОВАНИЕ МЕТОДОВ")
        self.safe_log(f"\n{'='*60}", "header")
        self.safe_log("✅ ТЕСТИРОВАНИЕ ПОЛНОСТЬЮ ЗАВЕРШЕНО", "success")
        self.safe_log(f"{'='*60}", "header")


if __name__ == "__main__":
    # Настраиваем базовое логирование, чтобы системные ошибки не терялись
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    app = PrintTesterApp()
    app.mainloop()
