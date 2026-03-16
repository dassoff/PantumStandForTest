"""Конвертация форматов для печати."""

import asyncio
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional


class Converter:
    """Конвертер форматов для печати."""

    def __init__(
        self,
        ghostscript_path: Optional[str] = None,
        libreoffice_path: Optional[str] = None,
        enable_cache: bool = True,
    ):
        """Инициализация конвертера."""
        self.ghostscript_path = ghostscript_path
        self.libreoffice_path = libreoffice_path
        self.enable_cache = enable_cache
        self._cache: dict = {}

    async def pdf_to_pcl6(
        self,
        pdf_path: str,
        duplex: bool = True,
        paper_size: str = "A4",
        copies: int = 1,
        resolution: int = 600,
    ) -> bytes:
        """Конвертация PDF в PCL6 формат."""
        cache_key = None
        if self.enable_cache:
            cache_key = f"{pdf_path}:{duplex}:{paper_size}:{copies}:{resolution}"
            if cache_key in self._cache:
                return self._cache[cache_key]

        # Определяем путь к Ghostscript
        gs_cmd = self._find_ghostscript()

        # Параметры для PCL6
        pcl_params = [
            "-sDEVICE=pcl6",
            f"-r{resolution}",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sOutputFile=-",  # Вывод в stdout
        ]

        # Добавляем параметры бумаги
        if paper_size == "A4":
            pcl_params.append("-sPAPERSIZE=a4")

        cmd = [gs_cmd] + pcl_params + [pdf_path]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=30,
            )

            if process.returncode != 0:
                raise RuntimeError(f"Ghostscript error: {stderr.decode()}")

            pcl_data = stdout

            if self.enable_cache and cache_key:
                self._cache[cache_key] = pcl_data

            return pcl_data

        except FileNotFoundError:
            # Fallback: используем pdftoppm + конвертация
            return await self._pdf_to_pcl6_fallback(pdf_path)

    async def _pdf_to_pcl6_fallback(self, pdf_path: str) -> bytes:
        """Fallback метод конвертации через pdftoppm."""
        try:
            # Пробуем pdftoppm
            with tempfile.TemporaryDirectory() as tmpdir:
                output_prefix = os.path.join(tmpdir, "page")
                cmd = ["pdftoppm", "-pcl", pdf_path, output_prefix]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30,
                )

                if process.returncode == 0:
                    # Собираем все PCL файлы
                    pcl_data = b""
                    for f in sorted(os.listdir(tmpdir)):
                        if f.endswith(".pcl"):
                            with open(os.path.join(tmpdir, f), "rb") as pf:
                                pcl_data += pf.read()
                    return pcl_data

        except Exception:
            pass

        # Если ничего не помогло, возвращаем сырой PDF
        # (принтер может обработать сам)
        async with asyncio.Lock():
            with open(pdf_path, "rb") as f:
                return f.read()

    def _find_ghostscript(self) -> str:
        """Поиск исполняемого файла Ghostscript."""
        if self.ghostscript_path and os.path.exists(self.ghostscript_path):
            return self.ghostscript_path

        # Стандартные пути Windows
        possible_paths = [
            r"C:\Program Files\gs\gs10.02.0\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.01.0\bin\gswin64c.exe",
            r"C:\Program Files\gs\gs10.00.0\bin\gswin64c.exe",
            r"C:\Program Files (x86)\gs\gs10.02.0\bin\gswin32c.exe",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # Пробуем найти в PATH
        gs_names = ["gswin64c", "gswin32c", "gs"]
        for name in gs_names:
            try:
                result = subprocess.run(
                    ["where", name],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return result.stdout.strip().split("\n")[0]
            except subprocess.CalledProcessError:
                continue

        return "gswin64c"  # По умолчанию


async def pdf_to_pcl6(
    pdf_path: str,
    duplex: bool = True,
    paper_size: str = "A4",
    copies: int = 1,
    resolution: int = 600,
    ghostscript_path: Optional[str] = None,
) -> bytes:
    """Утилита для конвертации PDF в PCL6."""
    converter = Converter(ghostscript_path=ghostscript_path)
    return await converter.pdf_to_pcl6(
        pdf_path,
        duplex=duplex,
        paper_size=paper_size,
        copies=copies,
        resolution=resolution,
    )


async def docx_to_pdf(
    docx_path: str,
    output_dir: Optional[str] = None,
    libreoffice_path: Optional[str] = None,
) -> str:
    """Конвертация DOCX в PDF через LibreOffice."""
    # Определяем путь к LibreOffice
    lo_cmd = _find_libreoffice(libreoffice_path)

    # Выходная директория
    if output_dir is None:
        output_dir = os.path.dirname(docx_path) or tempfile.gettempdir()

    cmd = [
        lo_cmd,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", output_dir,
        docx_path,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=60,
        )

        if process.returncode != 0:
            raise RuntimeError(f"LibreOffice error: {stderr.decode()}")

        # Находим созданный PDF файл
        pdf_name = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        pdf_path = os.path.join(output_dir, pdf_name)

        if not os.path.exists(pdf_path):
            raise RuntimeError(f"PDF file not created: {pdf_path}")

        return pdf_path

    except FileNotFoundError:
        raise RuntimeError(
            "LibreOffice not found. Please install LibreOffice or specify the path."
        )


async def html_to_pdf(
    html_path: str,
    output_path: Optional[str] = None,
) -> str:
    """Конвертация HTML в PDF через weasyprint или playwright."""
    if output_path is None:
        output_path = os.path.splitext(html_path)[0] + ".pdf"

    # Пробуем weasyprint
    try:
        cmd = ["weasyprint", html_path, output_path]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode == 0:
            return output_path
    except FileNotFoundError:
        pass

    # Fallback: playwright
    try:
        cmd = [
            "python", "-m", "playwright",
            "pdf", html_path, output_path,
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode == 0:
            return output_path
    except FileNotFoundError:
        pass

    raise RuntimeError(
        "No HTML to PDF converter found. Install weasyprint or playwright."
    )


async def image_to_pcl(
    image_path: str,
    paper_size: str = "A4",
) -> bytes:
    """Конвертация изображения в PCL6 (для чеков)."""
    from PIL import Image

    img = Image.open(image_path)

    # Создаем PCL команду
    pcl_header = b"\x1bE"  # Reset
    pcl_header += b"\x1b&l26A"  # A4
    pcl_header += b"\x1b*t600R"  # 600 DPI

    # Конвертируем изображение в бинарные данные
    # Для простоты используем grayscale
    img_gray = img.convert("1")
    width, height = img_gray.size

    # PCL растровые данные
    raster_data = b""
    for y in range(0, height, 8):
        pcl_data = b"\x1b*t0R"  # Start raster graphics
        for x in range(width):
            byte = 0
            for bit in range(8):
                py = y + bit
                if py < height and img_gray.getpixel((x, py)) == 0:
                    byte |= (1 << (7 - bit))
            raster_data += bytes([byte])

    return pcl_header + raster_data


def _find_libreoffice(custom_path: Optional[str] = None) -> str:
    """Поиск исполняемого файла LibreOffice."""
    if custom_path and os.path.exists(custom_path):
        return custom_path

    # Стандартные пути Windows
    possible_paths = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # Linux
    if os.path.exists("/usr/bin/soffice"):
        return "/usr/bin/soffice"

    return "soffice"
