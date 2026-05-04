import asyncio
import os
import time
from core.printer import FastPrinter

async def test_fastest_print_methods():
    print("=== Тестирование самых быстрых методов печати для Pantum BP5100DW ===")
    
    # Задаем IP или Имя принтера (изменить при необходимости)
    printer_ip = os.getenv("PRINT_PRINTER_IP", "192.168.1.100") 
    printer_name = "Pantum BP5100DW"
    
    # Создаем тестовый PDF файл (или укажите путь к реальному)
    test_pdf_path = "test_document.pdf"
    if not os.path.exists(test_pdf_path):
        print(f"Файл {test_pdf_path} не найден. Пожалуйста, положите тестовый PDF в директорию.")
        return

    printer = FastPrinter(
        printer_ip=printer_ip,
        printer_name=printer_name,
        printer_port=9100
    )

    print("\n[Метод 1] Прямая TCP печать RAW PDF (Native PDF over Port 9100)")
    try:
        t0 = time.time()
        job = await printer.print_pdf_direct_tcp(test_pdf_path, copies=1, duplex=False)
        print(f"Статус: {job.status.value}, Затрачено времени: {time.time() - t0:.3f} сек")
        if job.error:
            print(f"Ошибка: {job.error}")
    except Exception as e:
        print(f"Сбой TCP метода: {e}")

    print("\n[Метод 2] Печать RAW PDF через Windows Spooler (pywin32)")
    try:
        t0 = time.time()
        job2 = await printer.print_pdf_win32_raw(test_pdf_path, copies=1, duplex=False)
        print(f"Статус: {job2.status.value}, Затрачено времени: {time.time() - t0:.3f} сек")
        if job2.error:
            print(f"Ошибка: {job2.error}")
    except Exception as e:
        print(f"Сбой Win32 метода: {e}")

if __name__ == "__main__":
    asyncio.run(test_fastest_print_methods())
