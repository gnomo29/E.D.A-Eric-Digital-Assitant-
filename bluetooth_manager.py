"""Gestión de Bluetooth con bleak (modo degradado incluido)."""

from __future__ import annotations

import asyncio
from typing import Dict, List

from logger import get_logger
from memory import MemoryManager

log = get_logger("bluetooth")

try:
    from bleak import BleakClient, BleakScanner
except Exception:
    BleakClient = None
    BleakScanner = None


class BluetoothManager:
    """Escaneo y conexión de dispositivos BLE con persistencia de favoritos."""

    def __init__(self) -> None:
        self.memory = MemoryManager()
        self._active_clients: Dict[str, BleakClient] = {}

    @property
    def available(self) -> bool:
        return BleakScanner is not None and BleakClient is not None

    async def scan_devices_async(self, timeout: int = 6) -> List[Dict[str, str]]:
        if not self.available:
            return []
        devices = await BleakScanner.discover(timeout=timeout)
        parsed: List[Dict[str, str]] = []
        seen = set()
        for d in devices:
            addr = str(getattr(d, "address", "")).strip()
            if not addr or addr in seen:
                continue
            seen.add(addr)
            parsed.append(
                {
                    "name": str(getattr(d, "name", "") or "Desconocido"),
                    "address": addr,
                    "rssi": str(getattr(d, "rssi", "N/D")),
                }
            )
        self.memory.save_bt_devices(parsed)
        return parsed

    def scan_devices(self, timeout: int = 6) -> List[Dict[str, str]]:
        """Versión síncrona para GUI."""
        try:
            return asyncio.run(self.scan_devices_async(timeout=timeout))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.scan_devices_async(timeout=timeout))
        except Exception as exc:
            log.error("Error escaneando bluetooth: %s", exc)
            return []

    async def connect_async(self, address: str) -> bool:
        if not self.available:
            return False
        try:
            client = BleakClient(address)
            await client.connect(timeout=10.0)
            connected = bool(client.is_connected)
            if connected:
                self._active_clients[address] = client
            return connected
        except Exception as exc:
            log.error("Error conectando BLE (%s): %s", address, exc)
            return False

    def connect(self, address: str) -> bool:
        try:
            return asyncio.run(self.connect_async(address))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.connect_async(address))
        except Exception:
            return False

    async def disconnect_async(self, address: str) -> bool:
        client = self._active_clients.get(address)
        if not client:
            return True
        try:
            await client.disconnect()
            self._active_clients.pop(address, None)
            return True
        except Exception as exc:
            log.error("Error desconectando BLE (%s): %s", address, exc)
            return False

    def disconnect(self, address: str) -> bool:
        try:
            return asyncio.run(self.disconnect_async(address))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.disconnect_async(address))
        except Exception:
            return False

    def add_favorite(self, address: str) -> Dict[str, str]:
        data = self.memory.get_bt_devices()
        known = data.get("known_devices", [])
        candidate = next((d for d in known if str(d.get("address", "")) == address), None)
        if not candidate:
            return {"status": "error", "message": "Dispositivo no encontrado en escaneo"}
        if self.memory.add_bt_favorite(candidate):
            return {"status": "ok", "message": "Favorito guardado"}
        return {"status": "error", "message": "No se pudo guardar favorito"}

    def get_favorites(self) -> List[Dict[str, str]]:
        data = self.memory.get_bt_devices()
        return data.get("favorites", [])

    def get_status_summary(self) -> str:
        if not self.available:
            return "Bluetooth en modo degradado (bleak no disponible)"
        favorites = self.get_favorites()
        active = len(self._active_clients)
        return f"Bluetooth activo. Favoritos: {len(favorites)} | Conexiones activas: {active}"
