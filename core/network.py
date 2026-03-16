"""Сетевые операции и RAW TCP печать."""

import asyncio
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class PrinterStatus:
    """Статус принтера."""

    online: bool = False
    ready: bool = False
    paper_jam: bool = False
    low_toner: bool = False
    door_open: bool = False
    error_message: Optional[str] = None
    snmp_data: Optional[Dict[str, Any]] = None


class TCPConnection:
    """TCP соединение для отправки данных на принтер."""

    def __init__(
        self,
        host: str,
        port: int = 9100,
        timeout: int = 10,
    ):
        """Инициализация TCP соединения."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    async def connect(self) -> bool:
        """Подключение к принтеру."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            self._connected = True
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            return False

    async def send(self, data: bytes) -> int:
        """Отправка данных."""
        if not self._connected or not self._writer:
            raise ConnectionError("Not connected")

        self._writer.write(data)
        await self._writer.drain()
        return len(data)

    async def close(self) -> None:
        """Закрытие соединения."""
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._connected = False

    async def __aenter__(self) -> "TCPConnection":
        """Контекстный менеджер: вход."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Контекстный менеджер: выход."""
        await self.close()


class NetworkPrinter:
    """Сетевой принтер с поддержкой RAW TCP печати."""

    # SNMP OID для принтеров (стандартные)
    SNMP_OIDS = {
        "status": "1.3.6.1.2.1.43.18.1.1.5.1.1",  # Printer status
        "marker_supplies": "1.3.6.1.2.1.43.12.1.1.4",  # Toner level
        "input_tray": "1.3.6.1.2.1.43.8.2.1.10",  # Paper tray
    }

    def __init__(
        self,
        ip: Optional[str],
        port: int = 9100,
        timeout: int = 10,
    ):
        """Инициализация сетевого принтера."""
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._connection_pool: asyncio.Queue = asyncio.Queue(maxsize=5)
        self._pool_initialized = False

    async def send_raw(self, data: bytes) -> int:
        """Отправка RAW данных на принтер через TCP порт 9100."""
        if not self.ip:
            raise ValueError("Printer IP not specified")

        # Пробуем использовать пул соединений
        conn = None
        try:
            if self._pool_initialized and not self._connection_pool.empty():
                conn = self._connection_pool.get_nowait()
            else:
                conn = TCPConnection(self.ip, self.port, self.timeout)

            if not await conn.connect():
                raise ConnectionError(f"Cannot connect to printer at {self.ip}:{self.port}")

            bytes_sent = await conn.send(data)

            # Возвращаем соединение в пул
            if self._pool_initialized:
                try:
                    self._connection_pool.put_nowait(conn)
                except asyncio.QueueFull:
                    await conn.close()
            else:
                await conn.close()

            return bytes_sent

        except Exception as e:
            if conn:
                await conn.close()
            raise

    async def get_status(self) -> PrinterStatus:
        """Получение статуса принтера."""
        if not self.ip:
            return PrinterStatus(
                online=False,
                error_message="Printer IP not specified",
            )

        # Пробуем SNMP
        try:
            snmp_data = await self._get_snmp_status()
            if snmp_data:
                return PrinterStatus(
                    online=True,
                    ready=snmp_data.get("ready", False),
                    low_toner=snmp_data.get("low_toner", False),
                    snmp_data=snmp_data,
                )
        except Exception:
            pass

        # Fallback: TCP проверка
        try:
            conn = TCPConnection(self.ip, self.port, self.timeout)
            connected = await conn.connect()
            await conn.close()

            return PrinterStatus(
                online=connected,
                ready=connected,
            )
        except Exception as e:
            return PrinterStatus(
                online=False,
                error_message=str(e),
            )

    async def _get_snmp_status(self) -> Optional[Dict[str, Any]]:
        """Получение статуса через SNMP."""
        try:
            from pysnmp.hlapi.asyncio import SnmpEngine, CommunityData, UdpTransportTarget
            from pysnmp.hlapi.asyncio import ContextData, ObjectType, ObjectIdentity
            from pysnmp.hlapi.asyncio import getCmd

            iterator = getCmd(
                SnmpEngine(),
                CommunityData("public", mpModel=0),
                UdpTransportTarget((self.ip, 161), timeout=self.timeout / 1000),
                ContextData(),
                ObjectType(ObjectIdentity(self.SNMP_OIDS["status"])),
                ObjectType(ObjectIdentity(self.SNMP_OIDS["marker_supplies"])),
            )

            error_indication, error_status, error_index, var_binds = await next(iterator)

            if error_indication:
                return None

            result = {"ready": True, "low_toner": False}

            for var_bind in var_binds:
                oid = str(var_bind[0])
                value = var_bind[1]

                if self.SNMP_OIDS["status"] in oid:
                    result["ready"] = int(value) == 3  # 3 = idle/ready
                elif self.SNMP_OIDS["marker_supplies"] in oid:
                    # Проверяем уровень тонера
                    result["low_toner"] = int(value) < 10

            return result

        except ImportError:
            # pysnmp не установлен
            return None
        except Exception:
            return None

    async def is_available(self) -> bool:
        """Проверка доступности принтера."""
        status = await self.get_status()
        return status.online

    async def wait_for_ready(self, timeout: int = 30, interval: float = 1.0) -> bool:
        """Ожидание готовности принтера."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = await self.get_status()
            if status.ready:
                return True
            await asyncio.sleep(interval)

        return False

    async def initialize_pool(self, size: int = 5) -> None:
        """Инициализация пула соединений."""
        for _ in range(size):
            conn = TCPConnection(self.ip, self.port, self.timeout)
            if await conn.connect():
                await self._connection_pool.put(conn)
        self._pool_initialized = True

    async def close_pool(self) -> None:
        """Закрытие пула соединений."""
        while not self._connection_pool.empty():
            conn = self._connection_pool.get_nowait()
            await conn.close()
        self._pool_initialized = False


async def discover_printers(
    subnet: str = "192.168.1",
    port: int = 9100,
    timeout: int = 1,
) -> Dict[str, bool]:
    """Поиск принтеров в локальной сети."""
    results = {}

    async def check_host(host: str) -> None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            results[host] = True
        except Exception:
            results[host] = False

    tasks = []
    for i in range(1, 255):
        host = f"{subnet}.{i}"
        tasks.append(check_host(host))

    await asyncio.gather(*tasks, return_exceptions=True)

    return {k: v for k, v in results.items() if v}
