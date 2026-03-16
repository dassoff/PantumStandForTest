# Dockerfile для тестового стенда печати
# Кроссплатформенная версия для тестирования

FROM python:3.11-slim

# Устанавливаем зависимости для конвертации
RUN apt-get update && apt-get install -y \
    ghostscript \
    poppler-utils \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код проекта
COPY . .

# Создаем директорию для отчётов
RUN mkdir -p /app/reports

# Переменные окружения
ENV PRINT_PRINTER_IP=""
ENV PRINT_PRINTER_PORT="9100"
ENV PRINT_TCP_TIMEOUT="10"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from core.printer import FastPrinter; print('OK')" || exit 1

# Команда по умолчанию
CMD ["python", "run_tests.py", "--help"]
