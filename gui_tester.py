import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import asyncio
import os
import time
from pathlib import Path

# Попытаемся импортировать win32print для списка принтеров Windows
try:
    import win32print
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

from core.printer import FastPrinter
from core.converters import docx_to_pdf
from core.fallback import FallbackChain

class PrintTesterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pantum BP5100DW - Print Method Tester")
        self.geometry("750x650")
        
        self.selected_file = tk.StringVar()
        self.printer_ip = tk.StringVar(value="192.168.1.100")
        self.selected_win_printer = tk.StringVar()
        
        self.create_widgets()
        self.load_printers()

    def create_widgets(self):
        # 1. Выбор файла
        frame_file = tk.LabelFrame(self, text="1. Выбор файла (PDF, DOCX, TXT, IMG)", padx=10, pady=10)
        frame_file.pack(fill="x", padx=10, pady=5)
        
        tk.Entry(frame_file, textvariable=self.selected_file, state="readonly", width=70).pack(side="left", padx=5)
        tk.Button(frame_file, text="Обзор...", command=self.browse_file).pack(side="left")

        # 2. Выбор принтера
        frame_printer = tk.LabelFrame(self, text="2. Выбор принтера", padx=10, pady=10)
        frame_printer.pack(fill="x", padx=10, pady=5)
        
        tk.Label(frame_printer, text="IP-адрес (для прямых TCP методов):").grid(row=0, column=0, sticky="w", pady=2)
        tk.Entry(frame_printer, textvariable=self.printer_ip, width=40).grid(row=0, column=1, sticky="w", pady=2, padx=5)
        
        tk.Label(frame_printer, text="Windows Принтер (для Win32 методов):").grid(row=1, column=0, sticky="w", pady=2)
        self.cb_printers = ttk.Combobox(frame_printer, textvariable=self.selected_win_printer, width=37)
        self.cb_printers.grid(row=1, column=1, sticky="w", pady=2, padx=5)
        
        # 3. Кнопка тестирования
        frame_action = tk.Frame(self)
        frame_action.pack(fill="x", padx=10, pady=10)
        
        self.btn_test = tk.Button(frame_action, text="ТЕСТИРОВАТЬ ВСЕ МЕТОДЫ ПО ОЧЕРЕДИ", bg="#4CAF50", fg="black", font=("Arial", 11, "bold"), command=self.start_testing)
        self.btn_test.pack(fill="x", ipady=8)
        
        # 4. Логи
        frame_logs = tk.LabelFrame(self, text="Журнал тестирования", padx=10, pady=10)
        frame_logs.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Добавим скроллбар к логам
        scrollbar = tk.Scrollbar(frame_logs)
        scrollbar.pack(side="right", fill="y")
        self.txt_logs = tk.Text(frame_logs, state="disabled", wrap="word", yscrollcommand=scrollbar.set, font=("Consolas", 9))
        self.txt_logs.pack(fill="both", expand=True)
        scrollbar.config(command=self.txt_logs.yview)

    def load_printers(self):
        if WIN32_AVAILABLE:
            try:
                printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
                printer_names = [p[2] for p in printers]
                self.cb_printers['values'] = printer_names
                if printer_names:
                    self.cb_printers.current(0)
            except Exception as e:
                self.cb_printers['values'] = [f"Ошибка загрузки: {e}"]
                self.cb_printers.current(0)
        else:
            self.cb_printers['values'] = ["win32print не доступен (только TCP)"]
            self.cb_printers.current(0)

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите файл для печати",
            filetypes=[
                ("All Supported", "*.pdf;*.docx;*.txt;*.png;*.jpg;*.jpeg"),
                ("PDF Files", "*.pdf"),
                ("Word Documents", "*.docx"),
                ("Images", "*.png;*.jpg;*.jpeg"),
                ("Text Files", "*.txt"),
                ("All Files", "*.*")
            ]
        )
        if filename:
            self.selected_file.set(filename)

    def log(self, message):
        self.txt_logs.config(state="normal")
        self.txt_logs.insert(tk.END, message + "\n")
        self.txt_logs.see(tk.END)
        self.txt_logs.config(state="disabled")
        self.update_idletasks()

    def start_testing(self):
        file_path = self.selected_file.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Ошибка", "Сначала выберите существующий файл!")
            return
            
        ip = self.printer_ip.get().strip()
        win_printer = self.selected_win_printer.get().strip()
        
        self.btn_test.config(state="disabled")
        self.log(f"\n{'='*50}")
        self.log(f"[{time.strftime('%H:%M:%S')}] НАЧАЛО ТЕСТИРОВАНИЯ")
        self.log(f"Файл: {os.path.basename(file_path)}")
        self.log(f"TCP IP: {ip}")
        self.log(f"Win Принтер: {win_printer}")
        self.log(f"{'='*50}")
        
        # Запускаем асинхронный цикл в отдельном потоке
        threading.Thread(target=self.run_async_tests, args=(file_path, ip, win_printer), daemon=True).start()

    def run_async_tests(self, file_path, ip, win_printer):
        # Создаем новый event loop для потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_test_routine(file_path, ip, win_printer))
        finally:
            loop.close()
            
        # Восстанавливаем UI
        self.after(0, lambda: self.btn_test.config(state="normal"))
        self.after(0, lambda: self.log(f"\n{'='*50}\nТЕСТИРОВАНИЕ ПОЛНОСТЬЮ ЗАВЕРШЕНО\n{'='*50}"))

    async def async_test_routine(self, file_path, ip, win_printer):
        # Унификация: приводим файл к PDF, так как наши сверхбыстрые методы
        # работают именно с Native PDF. SumatraPDF и Ghostscript тоже умеют кушать PDF.
        pdf_path = file_path
        ext = Path(file_path).suffix.lower()
        
        if ext != ".pdf":
            self.after(0, lambda: self.log(f"\n[Подготовка] Конвертация {ext} в единый PDF-формат..."))
            try:
                pdf_path = await self.convert_to_pdf(file_path, ext)
                self.after(0, lambda: self.log(f"[Подготовка] Успешно сконвертировано: {os.path.basename(pdf_path)}"))
            except Exception as e:
                self.after(0, lambda: self.log(f"[Подготовка] ОШИБКА КОНВЕРТАЦИИ: {e}"))
                return
        
        # Создаем экземпляр принтера
        printer = FastPrinter(printer_ip=ip, printer_name=win_printer, printer_port=9100)
        
        methods_to_test = [
            ("Метод 1: Прямая TCP печать RAW PDF (Самый быстрый сетевой)", self.test_direct_tcp, [printer, pdf_path]),
            ("Метод 2: Windows RAW Spooler (Самый быстрый локальный)", self.test_win32_raw, [printer, pdf_path]),
            ("Метод 3: SumatraPDF (Стандартный из прода)", self.test_sumatra, [printer, pdf_path]),
            ("Метод 4: PDF -> PCL6 -> TCP (Резервный)", self.test_pcl6_tcp, [printer, pdf_path])
        ]
        
        for index, (name, func, args) in enumerate(methods_to_test):
            self.after(0, lambda n=name: self.log(f"\n>>> ЗАПУСК: {n}"))
            try:
                t0 = time.time()
                success, msg = await func(*args)
                t_elapsed = time.time() - t0
                
                if success:
                    self.after(0, lambda m=msg, t=t_elapsed: self.log(f"   [V] УСПЕХ: {m} (Заняло {t:.3f} сек.)"))
                else:
                    self.after(0, lambda m=msg, t=t_elapsed: self.log(f"   [X] ОШИБКА: {m} (Заняло {t:.3f} сек.)"))
            except Exception as e:
                self.after(0, lambda e=e: self.log(f"   [!] КРИТИЧЕСКИЙ СБОЙ: {str(e)}"))
            
            # Пауза между тестами, чтобы принтер успел напечатать лист и переварить кэш
            if index < len(methods_to_test) - 1:
                self.after(0, lambda: self.log("   -> Ожидание 8 секунд для очистки памяти принтера..."))
                await asyncio.sleep(8)

    async def convert_to_pdf(self, file_path, ext):
        if ext == ".docx":
            return await docx_to_pdf(file_path)
        elif ext in [".png", ".jpg", ".jpeg"]:
            from PIL import Image
            out_path = str(Path(file_path).with_suffix('.pdf'))
            img = Image.open(file_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(out_path, "PDF", resolution=300.0)
            return out_path
        elif ext == ".txt":
            # Простейшая конвертация текста в PDF (через PIL)
            from PIL import Image, ImageDraw, ImageFont
            out_path = str(Path(file_path).with_suffix('.pdf'))
            img = Image.new('RGB', (2480, 3508), color=(255, 255, 255)) # A4 at 300dpi
            d = ImageDraw.Draw(img)
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            # Пытаемся подгрузить базовый шрифт, если нет - используем дефолтный
            try:
                font = ImageFont.truetype("arial.ttf", 40)
            except IOError:
                font = ImageFont.load_default()
            d.text((100, 100), text, fill=(0, 0, 0), font=font)
            img.save(out_path, "PDF", resolution=300.0)
            return out_path
        else:
            raise ValueError(f"Неизвестный формат для конвертации: {ext}")

    async def test_direct_tcp(self, printer, pdf_path):
        if not printer.printer_ip or printer.printer_ip == "0.0.0.0":
            return False, "Не указан корректный IP принтера."
        job = await printer.print_pdf_direct_tcp(pdf_path, copies=1, duplex=False)
        if job.status.value == "completed":
            return True, "Отправлено на TCP порт 9100 напрямую."
        return False, job.error or "Неизвестная ошибка отправки"

    async def test_win32_raw(self, printer, pdf_path):
        if not WIN32_AVAILABLE:
            return False, "Библиотека pywin32 не установлена (Метод недоступен)."
        if not printer.printer_name:
            return False, "Не выбран Windows-принтер."
            
        job = await printer.print_pdf_win32_raw(pdf_path, copies=1, duplex=False)
        if job.status.value == "completed":
            return True, "Отправлено в очередь Windows как RAW."
        return False, job.error or "Неизвестная ошибка отправки"

    async def test_sumatra(self, printer, pdf_path):
        chain = FallbackChain(printer=printer)
        result = await chain._try_sumatra(pdf_path, copies=1)
        if result.success:
            return True, "Успешно отправлено через процесс SumatraPDF."
        return False, result.error or "SumatraPDF не установлена или вернула ошибку."

    async def test_pcl6_tcp(self, printer, pdf_path):
        if not printer.printer_ip or printer.printer_ip == "0.0.0.0":
            return False, "Не указан корректный IP принтера."
        job = await printer.print_pdf_fast(pdf_path, copies=1, duplex=False)
        if job.status.value == "completed":
            return True, "Отправлено на TCP порт 9100 после конвертации в PCL6."
        return False, job.error or "Неизвестная ошибка отправки"

if __name__ == "__main__":
    app = PrintTesterApp()
    app.mainloop()
