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
import csv
import socket
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
    flatten: bool = True
    resolution: int = 600


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
            return await FileConverter.repair_pdf(file_path)
            
        if ext == ".docx":
            return await docx_to_pdf(file_path)
            
        if ext in FileConverter.SUPPORTED_IMAGE_EXTENSIONS:
            return await asyncio.to_thread(FileConverter._convert_image, file_path)
            
        if ext == ".txt":
            return await asyncio.to_thread(FileConverter._convert_text, file_path)
            
        raise ValueError(f"Неизвестный или неподдерживаемый формат: {ext}")

    @staticmethod
    async def repair_pdf(file_path: str) -> str:
        """Очистка и восстановление PDF через PyMuPDF."""
        import fitz
        out_path = str(Path(file_path).with_suffix('.repaired.pdf'))
        try:
            def _repair():
                doc = fitz.open(file_path)
                doc.save(out_path, clean=True, deflate=True)
                doc.close()
                return out_path
            return await asyncio.to_thread(_repair)
        except Exception:
            return file_path # Возвращаем оригинал если не вышло

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

    async def execute_all_tests(self, file_path: str, ip: str, win_printer: str, flatten: bool = False, resolution: int = 600) -> None:
        """Executes all print strategies sequentially."""
        try:
            # 1. Preparation
            pdf_path = await self._prepare_pdf(file_path)
            if not pdf_path:
                return

            # 2. Flattening if requested
            if flatten:
                self.log(f"[Оптимизация] Сплющивание PDF (DPI: {resolution}) для ускорения процессора принтера...", "warning")
                printer_temp = FastPrinter(printer_ip=ip)
                pdf_path = await printer_temp.flatten_pdf(pdf_path, dpi=resolution)
                self.log(f"[Оптимизация] PDF сплющен: {os.path.basename(pdf_path)}\n", "success")

            # 3. Printer Initialization
            printer = FastPrinter(printer_ip=ip, printer_name=win_printer, printer_port=9100)

            # 3. Define Strategies
            strategies = [
                ("Прямая TCP печать RAW PDF (Сетевой)", lambda p, path: self._test_direct_tcp(p, path, resolution)),
                ("Windows RAW Spooler (Локальный)", self._test_win32_raw),
                ("SumatraPDF (Продакшен метод)", self._test_sumatra),
                ("PCL6 по TCP (Резервный конвертер)", self._test_pcl6_tcp)
            ]


            # 3. Smart Method Selection (Optional info)
            best_method = self._suggest_best_method(pdf_path)
            self.log(f"🤖 Рекомендация: {best_method}\n", "info")

            # 4. Execute Strategies
            for index, (name, strategy_func) in enumerate(strategies):
                self.log(f"▶ ЗАПУСК: {name}", "header")
                t_elapsed, success, msg = await self._run_single_strategy(strategy_func, printer, pdf_path)
                
                # Сохранение статистики
                self._save_stat(name, os.path.basename(file_path), t_elapsed, success, flatten)

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
                self._update_preview(pdf_path)
                return pdf_path
            except Exception as e:
                self.log(f"[Подготовка] ОШИБКА: {e}", "error")
                return None
        return file_path

    def _suggest_best_method(self, pdf_path: str) -> str:
        """Анализ файла и выбор оптимальной стратегии."""
        size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if size_mb > 15:
            return "Сплющивание + Win32 RAW (Тяжелый файл)"
        return "Direct TCP (Быстрый старт)"

    async def _run_single_strategy(self, strategy: Callable, printer: FastPrinter, pdf_path: str) -> Tuple[float, bool, str]:
        t0 = time.time()
        try:
            success, msg = await strategy(printer, pdf_path)
            t_elapsed = time.time() - t0
            if success:
                self.log(f"  └─ [V] УСПЕХ: {msg} (Заняло {t_elapsed:.3f} сек.)\n", "success")
            else:
                self.log(f"  └─ [X] ОШИБКА: {msg} (Заняло {t_elapsed:.3f} сек.)\n", "error")
            return t_elapsed, success, msg
        except Exception as e:
            t_elapsed = time.time() - t0
            self.log(f"  └─ [!] СБОЙ: {str(e)} (Заняло {t_elapsed:.3f} сек.)\n", "error")
            return t_elapsed, False, str(e)

    def _save_stat(self, method: str, filename: str, duration: float, success: bool, flattened: bool) -> None:
        file_exists = os.path.isfile("print_stats.csv")
        with open("print_stats.csv", "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Timestamp", "Method", "File", "Duration", "Success", "Flattened"])
            writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                method, filename, f"{duration:.4f}", success, flattened
            ])

    # --- Print Strategies ---

    async def _test_direct_tcp(self, printer: FastPrinter, pdf_path: str, resolution: int = 600) -> Tuple[bool, str]:
        if not printer.printer_ip or printer.printer_ip == "0.0.0.0":
            return False, "Не указан корректный IP принтера."
        job = await printer.print_pdf_direct_tcp(pdf_path, copies=1, duplex=False, resolution=resolution)
        if job.status.value == "completed":
            return True, f"Отправлено на TCP (DPI: {resolution})"
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
        self._start_status_loop()

    def _setup_variables(self) -> None:
        self.selected_file = tk.StringVar()
        self.printer_ip = tk.StringVar(value=self.config.ip)
        self.selected_win_printer = tk.StringVar(value=self.config.win_printer)
        self.use_flattening = tk.BooleanVar(value=self.config.flatten)
        self.selected_resolution = tk.IntVar(value=self.config.resolution)

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

        # Layout: Left column (controls) and Right column (preview)
        content_grid = ttk.Frame(main_frame)
        content_grid.pack(fill="both", expand=True)
        content_grid.columnconfigure(0, weight=3)
        content_grid.columnconfigure(1, weight=1)

        left_pane = ttk.Frame(content_grid)
        left_pane.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        
        self._create_file_section(left_pane)
        self._create_printer_section(left_pane)
        self._create_action_section(left_pane)
        self._create_log_section(left_pane)
        
        # Preview Pane
        preview_frame = ttk.LabelFrame(content_grid, text=" Предпросмотр ", padding="10")
        preview_frame.grid(row=0, column=1, sticky="nsew")
        self.preview_label = ttk.Label(preview_frame, text="Нет файла для\nпредпросмотра", justify="center")
        self.preview_label.pack(fill="both", expand=True)

        # Status Bar at the very bottom
        self.status_bar = ttk.Frame(self, relief="sunken", padding=(5, 2))
        self.status_bar.pack(side="bottom", fill="x")
        
        self.lbl_toner = ttk.Label(self.status_bar, text="Тонер: --%")
        self.lbl_toner.pack(side="left", padx=10)
        
        self.lbl_drum = ttk.Label(self.status_bar, text="Барабан: --%")
        self.lbl_drum.pack(side="left", padx=10)
        
        self.lbl_pages = ttk.Label(self.status_bar, text="Счетчик: --")
        self.lbl_pages.pack(side="left", padx=10)
        
        self.lbl_ping = ttk.Label(self.status_bar, text="Пинг: -- мс")
        self.lbl_ping.pack(side="left", padx=10)
        
        self.lbl_status = ttk.Label(self.status_bar, text="Статус: Ожидание...")
        self.lbl_status.pack(side="right", padx=10)

    def _start_status_loop(self) -> None:
        """Фоновый поток для опроса статуса принтера."""
        def _loop():
            while True:
                ip = self.printer_ip.get().strip()
                if ip and ip != "192.168.1.100": # Не опрашиваем дефолт
                    try:
                        from core.network import NetworkPrinter
                        printer = NetworkPrinter(ip)
                        status = asyncio.run(printer.get_status())
                        self.after(0, self._update_status_ui, status)
                    except Exception:
                        pass
                time.sleep(10)
        
        threading.Thread(target=_loop, daemon=True).start()

    def _update_status_ui(self, status) -> None:
        if status.online:
            toner = status.snmp_data.get("toner_level", 0) if status.snmp_data else 0
            drum = status.snmp_data.get("drum_level", 0) if status.snmp_data else 0
            pages = status.snmp_data.get("pages_printed", 0) if status.snmp_data else 0
            latency = status.snmp_data.get("latency_ms", 0) if status.snmp_data else 0
            err = status.snmp_data.get("error") if status.snmp_data else None
            
            self.lbl_toner.config(text=f"Тонер: {toner}%", foreground="orange" if toner < 15 else "black")
            self.lbl_drum.config(text=f"Барабан: {drum}%", foreground="orange" if drum < 15 else "black")
            self.lbl_pages.config(text=f"Счетчик: {pages}")
            
            if latency >= 0:
                self.lbl_ping.config(text=f"Пинг: {latency} мс", foreground="red" if latency > 100 else "green")
            else:
                self.lbl_ping.config(text="Пинг: ОШИБКА", foreground="red")
            
            if err:
                self.lbl_status.config(text=f"⚠️ {err}", foreground="red")
            else:
                self.lbl_status.config(text="✅ Готов", foreground="green")
        else:
            self.lbl_status.config(text="❌ Офлайн", foreground="gray")

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
        ttk.Button(frame, text="🔍 Найти принтеры", command=self.discover_printers).grid(row=0, column=2, padx=(10, 0))
        
        ttk.Label(frame, text="Windows Принтер:").grid(row=1, column=0, sticky="w", pady=5)
        self.cb_printers = ttk.Combobox(frame, textvariable=self.selected_win_printer, state="readonly")
        self.cb_printers.grid(row=1, column=1, sticky="we", pady=5, padx=(10, 0))
        
        ttk.Checkbutton(frame, text="Сплющивать PDF (Flattening)", 
                        variable=self.use_flattening).grid(row=2, column=0, sticky="w", pady=5)
        
        ttk.Label(frame, text="DPI:").grid(row=2, column=1, sticky="e", pady=5)
        self.cb_dpi = ttk.Combobox(frame, textvariable=self.selected_resolution, values=[300, 600, 1200], width=5, state="readonly")
        self.cb_dpi.grid(row=2, column=2, sticky="w", pady=5, padx=(5, 0))

    def _create_action_section(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(5, 15))
        
        # Кнопки в ряд
        btn_grid = ttk.Frame(frame)
        btn_grid.pack(fill="x")
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=3)
        
        ttk.Button(btn_grid, text="🔥 Прогрев печки", command=self.wake_printer).grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        self.btn_test = ttk.Button(btn_grid, text="🚀 ЗАПУСТИТЬ ТЕСТИРОВАНИЕ МЕТОДОВ", style="Action.TButton", command=self.start_testing)
        self.btn_test.grid(row=0, column=1, padx=(0, 10), sticky="nsew")
        ttk.Button(btn_grid, text="📊 Отчет", command=self.show_report).grid(row=0, column=2, padx=(0, 10), sticky="nsew")
        ttk.Button(btn_grid, text="📟 Текст на LCD", command=self.set_lcd_message).grid(row=0, column=3, padx=(0, 10), sticky="nsew")
        ttk.Button(btn_grid, text="🛑 ОТМЕНА", style="Error.TButton", command=self.cancel_printing).grid(row=0, column=4, padx=(0, 10), sticky="nsew")
        
        # Вторая строка кнопок (Админские)
        admin_grid = ttk.Frame(frame)
        admin_grid.pack(fill="x", pady=(5, 0))
        admin_grid.columnconfigure(0, weight=1)
        admin_grid.columnconfigure(1, weight=1)
        
        ttk.Button(admin_grid, text="🩺 ГЛУБОКАЯ ДИАГНОСТИКА", command=self.run_deep_check).grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        ttk.Button(admin_grid, text="🔄 ПЕРЕЗАГРУЗИТЬ ПРИНТЕР", command=self.reboot_printer_ui).grid(row=0, column=1, sticky="nsew")
        
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

    def discover_printers(self) -> None:
        self.safe_log("🔍 Поиск принтеров в локальной сети...", "warning")
        
        def _scan():
            try:
                # Определяем подсеть
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                
                subnet = ".".join(local_ip.split(".")[:-1])
                self.safe_log(f"📡 Сканирование подсети {subnet}.0/24...")
                
                from core.network import discover_printers
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                found = loop.run_until_complete(discover_printers(subnet=subnet, timeout=0.5))
                
                # Bonjour / mDNS Discovery
                try:
                    from zeroconf import Zeroconf, ServiceBrowser
                    class MyListener:
                        def add_service(self, zc, type_, name):
                            info = zc.get_service_info(type_, name)
                            if info and info.addresses:
                                ip = socket.inet_ntoa(info.addresses[0])
                                found[ip] = name
                    
                    zc = Zeroconf()
                    ServiceBrowser(zc, "_printer._tcp.local.", MyListener())
                    time.sleep(1.0)
                    zc.close()
                except Exception:
                    pass
                
                loop.close()
                
                if found:
                    self.safe_log(f"✅ Найдено принтеров: {len(found)}", "success")
                    for ip in found:
                        self.safe_log(f"  - {ip} (готов к печати)")
                    # Ставим первый найденный IP в поле
                    self.printer_ip.set(list(found.keys())[0])
                else:
                    self.safe_log("❌ Принтеры не найдены. Проверьте сеть или введите IP вручную.", "error")
            except Exception as e:
                self.safe_log(f"❌ Ошибка при поиске: {e}", "error")
                
        threading.Thread(target=_scan, daemon=True).start()

    def show_report(self) -> None:
        if not os.path.exists("print_stats.csv"):
            messagebox.showinfo("Инфо", "Статистика пока пуста. Проведите тесты!")
            return
            
        # Простое открытие файла в системе
        os.startfile("print_stats.csv") if hasattr(os, 'startfile') else os.system(f'open "print_stats.csv"')

    def _update_preview(self, pdf_path: str) -> None:
        """Обновление картинки предпросмотра."""
        def _render():
            try:
                import fitz
                from PIL import Image, ImageTk
                doc = fitz.open(pdf_path)
                page = doc[0]
                # Масштабируем для превью
                pix = page.get_pixmap(matrix=fitz.Matrix(0.15, 0.15))
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                photo = ImageTk.PhotoImage(img)
                
                self.after(0, self._set_preview_image, photo)
                doc.close()
            except Exception as e:
                print(f"Preview error: {e}")

        threading.Thread(target=_render, daemon=True).start()

    def _set_preview_image(self, photo) -> None:
        self.preview_label.config(image=photo, text="")
        self.preview_label.image = photo

    def wake_printer(self) -> None:
        ip = self.printer_ip.get().strip()
        if not ip:
            messagebox.showwarning("Внимание", "Введите IP принтера для прогрева!")
            return
            
        self.safe_log(f"♨️ Отправка команды прогрева на {ip}...", "warning")
        
        def _wake():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            printer = FastPrinter(printer_ip=ip)
            success, msg = loop.run_until_complete(printer.wake_up())
            if success:
                self.safe_log("✅ Принтер получил команду и начал прогрев (без печати листа).", "success")
            else:
                self.safe_log(f"❌ Не удалось отправить команду прогрева: {msg}", "error")
            loop.close()
            
        threading.Thread(target=_wake, daemon=True).start()

    def _test_runner(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self.print_service.execute_all_tests(
                    file_path=self.selected_file.get(),
                    ip=self.config.ip,
                    win_printer=self.config.win_printer,
                    flatten=self.use_flattening.get(),
                    resolution=self.selected_resolution.get()
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

    def cancel_printing(self) -> None:
        ip = self.printer_ip.get().strip()
        if not ip: return
        
        if messagebox.askyesno("Отмена", "Вы действительно хотите прервать печать?"):
            def _cancel():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                printer = FastPrinter(printer_ip=ip)
                loop.run_until_complete(printer.cancel_all_jobs())
                self.after(0, lambda: self.safe_log("🛑 Команда экстренной отмены отправлена!", "error"))
                loop.close()
            threading.Thread(target=_cancel, daemon=True).start()

    def set_lcd_message(self) -> None:
        from tkinter import simpledialog
        ip = self.printer_ip.get().strip()
        if not ip: return
        
        msg = simpledialog.askstring("LCD", "Введите текст для экрана принтера (макс 16 симв):", initialvalue="PTPRINT READY")
        if msg:
            def _set():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                printer = FastPrinter(printer_ip=ip)
                loop.run_until_complete(printer.set_ready_message(msg))
                self.after(0, lambda: self.safe_log(f"📟 На экран принтера отправлено: {msg}", "success"))
                loop.close()
            threading.Thread(target=_set, daemon=True).start()

    def run_deep_check(self) -> None:
        ip = self.printer_ip.get().strip()
        if not ip: return
        
        self.safe_log("🩺 Запуск глубокой диагностики портов...", "warning")
        
        def _check():
            from core.network import NetworkPrinter
            net = NetworkPrinter(ip)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            report = loop.run_until_complete(net.deep_health_check())
            
            self.safe_log("\n--- ОТЧЕТ ПО ПОРТАМ ---", "header")
            for name, status in report.items():
                tag = "success" if "ONLINE" in status or "OPEN" in status else "error"
                self.safe_log(f"  {name}: {status}", tag)
            self.safe_log("-----------------------\n", "header")
            loop.close()
            
        threading.Thread(target=_check, daemon=True).start()

    def reboot_printer_ui(self) -> None:
        ip = self.printer_ip.get().strip()
        if not ip: return
        
        if messagebox.askyesno("Рестарт", "Вы действительно хотите ПЕРЕЗАГРУЗИТЬ принтер?"):
            def _reboot():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                printer = FastPrinter(printer_ip=ip)
                loop.run_until_complete(printer.reboot_printer())
                self.after(0, lambda: self.safe_log("🔄 Команда на перезагрузку отправлена!", "warning"))
                loop.close()
            threading.Thread(target=_reboot, daemon=True).start()

if __name__ == "__main__":
    # Настраиваем базовое логирование, чтобы системные ошибки не терялись
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    app = PrintTesterApp()
    app.mainloop()
