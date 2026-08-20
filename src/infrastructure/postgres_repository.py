"""
Implémentation concrète de ReadingRepositoryPort pour PostgreSQL.

Seule cette classe connaît `asyncpg` et le schéma SQL. Remplacer PostgreSQL
par une autre base (TimescaleDB, SQLite pour les tests...) se fait en
écrivant un nouvel adaptateur qui implémente le même port.
"""
from datetime import datetime
import asyncpg
 
from app.domain.models import DeviceReading
from app.domain.ports import ReadingRepositoryPort

INSER_SQL = """
INSERT INTO tapo_readings
        (device_name, ip, "timestamp", current_power_mw,
         today_energy_wh, month_energy_wh, on_state)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
"""
_SELECT_SQL = """
    SELECT device_name, ip, "timestamp", current_power_mw,
           today_energy_wh, month_energy_wh, on_state
    FROM tapo_readings
    WHERE device_name = $1 AND "timestamp" >= $2
    ORDER BY "timestamp" DESC
    LIMIT $3
"""

class PostgresReadingRepository(ReadingRepositoryPort):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
    
    async def save(self, reading: DeviceReading) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                reading.device_name,
                reading.ip,
                reading.timestamp,
                reading.current_power_mw,
                reading.today_energy_wh,
                reading.month_energy_wh,
                reading.on_state,
            )
    async def save_many(self, readings: list[DeviceReading]) -> None:
        for reading in readings:
            await self.save(reading)
 
    async def find_by_device(
        self, device_name: str, since: datetime, limit: int = 1000
    ) -> list[DeviceReading]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_SQL, device_name, since, limit)
 
        return [
            DeviceReading(
                device_name=row["device_name"],
                ip=row["ip"],
                timestamp=row["timestamp"],
                current_power_mw=row["current_power_mw"],
                today_energy_wh=row["today_energy_wh"],
                month_energy_wh=row["month_energy_wh"],
                on_state=row["on_state"],
            )
            for row in rows
        ]
 
    async def close(self) -> None:
        await self._pool.close()