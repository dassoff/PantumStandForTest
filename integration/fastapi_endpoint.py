"""Пример интеграции с FastAPI."""

import os
import tempfile
import time
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.printer import FastPrinter, PrintJob, PrintStatus


# Создаем приложение FastAPI
app = FastAPI(
    title="Print Service API",
    description="API для печати документов на Pantum BM5100ADN",
    version="0.1.0",
)

# Инициализируем принтер
printer: Optional[FastPrinter] = None


def get_printer() -> FastPrinter:
    """Получение экземпляра принтера."""
    global printer
    if printer is None:
        printer_ip = os.getenv("PRINT_PRINTER_IP")
        printer_port = int(os.getenv("PRINT_PRINTER_PORT", "9100"))
        printer = FastPrinter(printer_ip=printer_ip, printer_port=printer_port)
    return printer


# Модели данных
class PrintRequest(BaseModel):
    """Запрос на печать."""

    copies: int = Field(default=1, ge=1, le=999, description="Количество копий")
    duplex: bool = Field(default=True, description="Двусторонняя печать")
    paper_size: str = Field(default="A4", description="Формат бумаги")


class PrintResponse(BaseModel):
    """Ответ на запрос печати."""

    status: str
    job_id: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class StatusResponse(BaseModel):
    """Ответ со статусом принтера."""

    online: bool
    ready: bool
    printer_ip: Optional[str] = None
    printer_name: str = "Pantum BM5100ADN"
    error_message: Optional[str] = None


class CancelResponse(BaseModel):
    """Ответ на запрос отмены."""

    success: bool
    message: str


# Endpoints
@app.post("/print/pdf", response_model=PrintResponse, tags=["Print"])
async def print_pdf(
    file: UploadFile = File(..., description="PDF файл для печати"),
    copies: int = Field(default=1, ge=1, le=999),
    duplex: bool = Field(default=True),
    background_tasks: BackgroundTasks = None,
):
    """
    Асинхронная печать PDF файла.

    - **file**: PDF файл для печати
    - **copies**: Количество копий (1-999)
    - **duplex**: Двусторонняя печать
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    try:
        # Читаем файл
        content = await file.read()

        # Печатаем
        printer_instance = get_printer()
        job = await printer_instance.print_pdf_stream(
            content,
            copies=copies,
            duplex=duplex,
        )

        return PrintResponse(
            status=job.status.value,
            job_id=job.job_id,
            duration_ms=job.duration_ms,
            error=job.error,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/print/docx", response_model=PrintResponse, tags=["Print"])
async def print_docx(
    file: UploadFile = File(..., description="DOCX файл для печати"),
    copies: int = Field(default=1, ge=1, le=999),
    duplex: bool = Field(default=True),
    background_tasks: BackgroundTasks = None,
):
    """
    Печать DOCX файла с конвертацией в PDF.

    - **file**: DOCX файл для печати
    - **copies**: Количество копий (1-999)
    - **duplex**: Двусторонняя печать
    """
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Only DOCX files are allowed")

    try:
        # Сохраняем во временный файл
        fd, temp_path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)

        with open(temp_path, "wb") as f:
            f.write(await file.read())

        # Печатаем
        printer_instance = get_printer()
        job = await printer_instance.print_docx_fast(
            temp_path,
            copies=copies,
            duplex=duplex,
        )

        # Очищаем временный файл
        os.unlink(temp_path)

        return PrintResponse(
            status=job.status.value,
            job_id=job.job_id,
            duration_ms=job.duration_ms,
            error=job.error,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/print/file", response_model=PrintResponse, tags=["Print"])
async def print_file(
    file_path: str,
    copies: int = Field(default=1, ge=1, le=999),
    duplex: bool = Field(default=True),
):
    """
    Печать файла по указанному пути.

    - **file_path**: Полный путь к файлу
    - **copies**: Количество копий
    - **duplex**: Двусторонняя печать
    """
    if not os.path.exists(file_path):
        raise HTTPException(status_code=400, detail="File not found")

    try:
        printer_instance = get_printer()

        if file_path.lower().endswith(".pdf"):
            job = await printer_instance.print_pdf_fast(
                file_path,
                copies=copies,
                duplex=duplex,
            )
        elif file_path.lower().endswith(".docx"):
            job = await printer_instance.print_docx_fast(
                file_path,
                copies=copies,
                duplex=duplex,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Use PDF or DOCX.",
            )

        return PrintResponse(
            status=job.status.value,
            job_id=job.job_id,
            duration_ms=job.duration_ms,
            error=job.error,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/printer/status", response_model=StatusResponse, tags=["Printer"])
async def printer_status():
    """
    Получение статуса принтера.
    """
    printer_instance = get_printer()
    status = await printer_instance.get_status()

    return StatusResponse(
        online=status.online,
        ready=status.ready,
        printer_ip=printer_instance.printer_ip,
        printer_name=printer_instance.printer_name,
        error_message=status.error_message,
    )


@app.post("/printer/cancel", response_model=CancelResponse, tags=["Printer"])
async def cancel_print():
    """
    Отмена текущего задания печати.
    """
    printer_instance = get_printer()
    success = await printer_instance.cancel_job()

    return CancelResponse(
        success=success,
        message="Job cancelled" if success else "No active job to cancel",
    )


@app.get("/printer/jobs", tags=["Printer"])
async def get_job_history(limit: int = 10):
    """
    Получение истории заданий печати.
    """
    printer_instance = get_printer()
    jobs = printer_instance.get_job_history(limit=limit)

    return {
        "jobs": [
            {
                "job_id": job.job_id,
                "status": job.status.value,
                "file_type": job.file_type,
                "copies": job.copies,
                "duplex": job.duplex,
                "duration_ms": job.duration_ms,
                "error": job.error,
                "created_at": job.created_at,
            }
            for job in jobs
        ]
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Проверка здоровья сервиса.
    """
    return {"status": "healthy", "timestamp": time.time()}


# Запуск приложения
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
