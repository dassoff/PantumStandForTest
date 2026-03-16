"""Цепочка fallback методов для отказоустойчивой печати."""

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .printer import FastPrinter


class FallbackMethod(Enum):
    """Методы fallback цепочки."""

    RAW_TCP = "raw_tcp"
    SUMATRA_PDF = "sumatra_pdf"
    WINDOWS_API = "windows_api"
    ADOBE_READER = "adobe_reader"
    BROWSER_PRINT = "browser_print"


@dataclass
class FallbackResult:
    """Результат выполнения fallback метода."""

    method: FallbackMethod
    success: bool
    duration_ms: int
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class FallbackChain:
    """Цепочка fallback методов для печати."""

    def __init__(
        self,
        printer: FastPrinter,
        max_fallback_time: float = 5.0,
        sumatra_path: Optional[str] = None,
        adobe_path: Optional[str] = None,
    ):
        """Инициализация цепочки fallback."""
        self.printer = printer
        self.max_fallback_time = max_fallback_time
        self.sumatra_path = sumatra_path
        self.adobe_path = adobe_path
        self._results: List[FallbackResult] = []

    async def execute(
        self,
        file_path: str,
        copies: int = 1,
        duplex: bool = True,
    ) -> FallbackResult:
        """Выполнение цепочки fallback."""
        self._results = []

        # Цепочка методов в порядке приоритета
        methods: List[Tuple[FallbackMethod, Callable]] = [
            (FallbackMethod.RAW_TCP, lambda: self._try_raw_tcp(file_path, copies, duplex)),
            (FallbackMethod.SUMATRA_PDF, lambda: self._try_sumatra(file_path, copies)),
            (FallbackMethod.WINDOWS_API, lambda: self._try_windows_api(file_path, copies)),
            (FallbackMethod.ADOBE_READER, lambda: self._try_adobe(file_path, copies)),
        ]

        start_time = time.time()

        for method, func in methods:
            elapsed = time.time() - start_time
            if elapsed > self.max_fallback_time * len(self._results):
                # Превышено время на предыдущие попытки
                break

            try:
                result = await asyncio.wait_for(
                    func(),
                    timeout=self.max_fallback_time,
                )
                self._results.append(result)

                if result.success:
                    return result

            except asyncio.TimeoutError:
                self._results.append(FallbackResult(
                    method=method,
                    success=False,
                    duration_ms=int(self.max_fallback_time * 1000),
                    error="Timeout",
                ))
            except Exception as e:
                self._results.append(FallbackResult(
                    method=method,
                    success=False,
                    duration_ms=0,
                    error=str(e),
                ))

        # Все методы не удались
        return FallbackResult(
            method=FallbackMethod.RAW_TCP,
            success=False,
            duration_ms=int((time.time() - start_time) * 1000),
            error="All fallback methods failed",
            details={"attempts": [r.__dict__ for r in self._results]},
        )

    async def _try_raw_tcp(
        self,
        file_path: str,
        copies: int,
        duplex: bool,
    ) -> FallbackResult:
        """Попытка печати через RAW TCP."""
        start = time.time()

        try:
            if not self.printer.printer_ip:
                return FallbackResult(
                    method=FallbackMethod.RAW_TCP,
                    success=False,
                    duration_ms=0,
                    error="Printer IP not specified",
                )

            job = await self.printer.print_pdf_fast(
                file_path,
                copies=copies,
                duplex=duplex,
            )

            duration = int((time.time() - start) * 1000)

            if job.status.value == "completed":
                return FallbackResult(
                    method=FallbackMethod.RAW_TCP,
                    success=True,
                    duration_ms=duration,
                )
            else:
                return FallbackResult(
                    method=FallbackMethod.RAW_TCP,
                    success=False,
                    duration_ms=duration,
                    error=job.error,
                )

        except Exception as e:
            return FallbackResult(
                method=FallbackMethod.RAW_TCP,
                success=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    async def _try_sumatra(
        self,
        file_path: str,
        copies: int,
    ) -> FallbackResult:
        """Попытка печати через SumatraPDF."""
        start = time.time()

        sumatra_exe = self.sumatra_path or self._find_sumatra()
        if not sumatra_exe or not os.path.exists(sumatra_exe):
            return FallbackResult(
                method=FallbackMethod.SUMATRA_PDF,
                success=False,
                duration_ms=0,
                error="SumatraPDF not found",
            )

        try:
            # Команда для печати
            cmd = [
                sumatra_exe,
                "-print-to",
                self.printer.printer_name or "Pantum BM5100ADN",
                file_path,
            ]

            if copies > 1:
                # Sumatra не поддерживает копии напрямую, нужно повторить
                for _ in range(copies):
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await process.communicate()
            else:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()

            duration = int((time.time() - start) * 1000)

            return FallbackResult(
                method=FallbackMethod.SUMATRA_PDF,
                success=True,
                duration_ms=duration,
            )

        except Exception as e:
            return FallbackResult(
                method=FallbackMethod.SUMATRA_PDF,
                success=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    async def _try_windows_api(
        self,
        file_path: str,
        copies: int,
    ) -> FallbackResult:
        """Попытка печати через Windows API (ShellExecute)."""
        start = time.time()

        try:
            # Используем ShellExecute для печати
            import subprocess

            cmd = ["cmd", "/c", "start", "/wait", "/min", file_path]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

            duration = int((time.time() - start) * 1000)

            return FallbackResult(
                method=FallbackMethod.WINDOWS_API,
                success=True,
                duration_ms=duration,
            )

        except Exception as e:
            return FallbackResult(
                method=FallbackMethod.WINDOWS_API,
                success=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    async def _try_adobe(
        self,
        file_path: str,
        copies: int,
    ) -> FallbackResult:
        """Попытка печати через Adobe Reader."""
        start = time.time()

        adobe_exe = self.adobe_path or self._find_adobe()
        if not adobe_exe or not os.path.exists(adobe_exe):
            return FallbackResult(
                method=FallbackMethod.ADOBE_READER,
                success=False,
                duration_ms=0,
                error="Adobe Reader not found",
            )

        try:
            cmd = [
                adobe_exe,
                "/t",  # Печать
                file_path,
                self.printer.printer_name or "Pantum BM5100ADN",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate()

            duration = int((time.time() - start) * 1000)

            return FallbackResult(
                method=FallbackMethod.ADOBE_READER,
                success=True,
                duration_ms=duration,
            )

        except Exception as e:
            return FallbackResult(
                method=FallbackMethod.ADOBE_READER,
                success=False,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def _find_sumatra(self) -> Optional[str]:
        """Поиск SumatraPDF."""
        possible_paths = [
            r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        return None

    def _find_adobe(self) -> Optional[str]:
        """Поиск Adobe Reader."""
        possible_paths = [
            r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            r"C:\Program Files (x86)\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            r"C:\Program Files\Adobe\Reader DC\Reader\AcroRd32.exe",
            r"C:\Program Files (x86)\Adobe\Reader DC\Reader\AcroRd32.exe",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        return None

    def get_results(self) -> List[FallbackResult]:
        """Получение результатов всех попыток."""
        return self._results.copy()

    def get_summary(self) -> Dict[str, Any]:
        """Получение сводки о выполнении."""
        return {
            "total_attempts": len(self._results),
            "success": any(r.success for r in self._results),
            "methods_tried": [r.method.value for r in self._results],
            "total_duration_ms": sum(r.duration_ms for r in self._results),
            "results": [r.__dict__ for r in self._results],
        }
