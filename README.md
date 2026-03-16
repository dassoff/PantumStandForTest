# Print Test Stand для Pantum BM5100ADN

Тестовый стенд для валидации сценариев печати перед интеграцией в основное приложение.

## Требования

- Python 3.10+
- Windows 10/11 или Linux
- Сетевой доступ к принтеру Pantum BM5100ADN

## Установка

```bash
cd print-test-stand
pip install -r requirements.txt
```

## Настройка

Отредактируйте `config/settings.yaml`:

```yaml
printer:
  ip: "192.168.1.100"
  port: 9100
  protocol: "raw_tcp"
```

## Использование

### Быстрый тест

```bash
python run_tests.py quick --printer-ip 192.168.1.100
```

### Полное тестирование

```bash
python run_tests.py full --printer-ip 192.168.1.100
```

### Бенчмарк

```bash
python run_tests.py benchmark --printer-ip 192.168.1.100 --iterations 10
```

### Печать файла

```bash
python run_tests.py print-file document.pdf --copies 2 --duplex
```

### Проверка статуса

```bash
python run_tests.py status --printer-ip 192.168.1.100
```

### Валидация конфигурации

```bash
python run_tests.py validate --config ./config/settings.yaml
```

## CLI команды

| Команда | Описание |
|---------|----------|
| `quick` | Быстрый тест печати (1 страница) |
| `full` | Полное тестирование всех сценариев |
| `benchmark` | Бенчмарк производительности |
| `print-file` | Печать указанного файла |
| `status` | Проверка статуса принтера |
| `clean` | Очистка временных файлов |
| `validate` | Валидация конфигурации |

## Запуск тестов через pytest

```bash
pytest tests/ -v --printer-ip 192.168.1.100
```

## Интеграция с FastAPI

```python
from core.printer import FastPrinter

printer = FastPrinter(printer_ip="192.168.1.100")

# Печать PDF
job = await printer.print_pdf_fast("document.pdf", copies=1, duplex=True)

# Печать из потока
job = await printer.print_pdf_stream(pdf_bytes, copies=1)

# Печать DOCX
job = await printer.print_docx_fast("document.docx", copies=1)

# Статус принтера
status = await printer.get_status()
```

## Запуск API сервера

```bash
uvicorn integration.fastapi_endpoint:app --host 0.0.0.0 --port 8000
```

Доступные эндпоинты:
- `POST /print/pdf` — печать PDF файла
- `POST /print/docx` — печать DOCX файла
- `GET /printer/status` — статус принтера
- `POST /printer/cancel` — отмена задания

## Docker

### Сборка

```bash
docker build -t print-test-stand .
```

### Запуск

```bash
docker run --rm --network host \
  -e PRINT_PRINTER_IP=192.168.1.100 \
  -v $(pwd)/reports:/app/reports \
  print-test-stand python run_tests.py quick
```

### Docker Compose

```bash
# Тестирование
docker-compose up print-test

# API сервер
docker-compose --profile api up api

# Бенчмарк
docker-compose --profile benchmark up benchmark
```

## Структура проекта

```
print-test-stand/
├── config/
│   ├── settings.yaml          # Конфигурация принтера и путей
│   └── validator.py           # Валидация конфигурации
├── core/
│   ├── printer.py             # Класс FastPrinter
│   ├── converters.py          # Конвертация PDF/DOCX
│   ├── network.py             # RAW TCP и SNMP
│   └── fallback.py            # Fallback цепочка
├── tests/
│   ├── test_pdf.py            # Тесты PDF печати
│   ├── test_docx.py           # Тесты DOCX печати
│   ├── test_speed.py          # Бенчмарки скорости
│   └── test_fallback.py       # Тесты отказоустойчивости
├── benchmarks/
│   └── runner.py              # Запуск бенчмарков
├── integration/
│   └── fastapi_endpoint.py    # FastAPI приложение
├── utils/
│   ├── logger.py              # Логирование
│   └── helpers.py             # Вспомогательные функции
├── reports/                   # Отчёты о тестах
├── requirements.txt
├── setup.py
└── run_tests.py               # CLI интерфейс
```

## Конфигурация

### settings.yaml

```yaml
printer:
  name: "Pantum BM5100ADN"
  ip: "192.168.1.100"
  port: 9100
  protocol: "raw_tcp"

  capabilities:
    duplex: true
    color: false
    max_resolution: 600

  defaults:
    copies: 1
    duplex: true
    paper: "A4"

paths:
  ghostscript: "C:\\Program Files\\gs\\gs10.02.0\\bin\\gswin64c.exe"
  libreoffice: "C:\\Program Files\\LibreOffice\\program\\soffice.exe"
  sumatra: "C:\\Program Files\\SumatraPDF\\SumatraPDF.exe"

performance:
  tcp_timeout: 10
  conversion_timeout: 30
  max_concurrent_jobs: 5
  enable_cache: true

logging:
  level: "INFO"
  file: "./reports/print.log"
  format: "json"
```

## Методы печати

1. **RAW TCP (PCL6)** — основной метод, максимальная скорость
2. **SumatraPDF** — fallback через внешний PDF-просмотрщик
3. **Windows API** — fallback через системную печать

## Зависимости

### Обязательные
- Python 3.10+
- fastapi, uvicorn
- pydantic, pyyaml
- aiofiles, aiohttp
- pytest, pytest-asyncio
- click, rich, structlog

### Опциональные (для конвертации)
- Ghostscript (PDF → PCL6)
- LibreOffice (DOCX → PDF)
- SumatraPDF (fallback печать)

## Troubleshooting

### Принтер не отвечает
1. Проверьте сетевое подключение
2. Убедитесь, что IP-адрес верный
3. Проверьте порт 9100: `telnet 192.168.1.100 9100`

### Ошибка конвертации DOCX
1. Установите LibreOffice
2. Укажите путь в `settings.yaml`

### Таймаут печати
1. Увеличьте `tcp_timeout` в конфигурации
2. Проверьте доступность принтера

## Лицензия

MIT License
