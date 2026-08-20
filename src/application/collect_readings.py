"""
Cas d'usage : collecter les relevés de consommation de toutes les prises
configurées, et les persister.
 
Cette classe n'orchestre que via les ports (`DeviceClientPort`,
`ReadingRepositoryPort`) : elle ne sait rien de Tapo ni de PostgreSQL.
C'est le modèle à suivre pour vos futurs cas d'usage d'exploitation de la
donnée (ex: `application/compute_daily_summary.py`,
`application/detect_anomaly.py`, `application/export_csv.py`...), qui
dépendront eux aussi uniquement des ports du domaine.
"""

import logging

from src.domain.ports import DeviceClientPort, ReadingRepositoryPort
 
logger = logging.getLogger(__name__)

class CollectReadingsUseCase:
    def __init__(
        self,
        device_client: DeviceClientPort,
        repository: ReadingRepositoryPort,
    ) -> None:
        self._device_client = device_client
        self._repository = repository
 
    async def execute(self, devices: dict[str, str]) -> None:
        """Interroge chaque prise et enregistre son relevé. Isole les erreurs
        par prise pour qu'une prise indisponible ne bloque pas les autres."""
        for name, ip in devices.items():
            try:
                reading = await self._device_client.read_energy(name, ip)
                await self._repository.save(reading)
                logger.info(
                    "%s (%s) : %s mW, état=%s -> enregistré",
                    name,
                    ip,
                    reading.current_power_mw,
                    "ON" if reading.on_state else "OFF",
                )
            except Exception:
                logger.exception("Échec de la collecte pour %s (%s)", name, ip)
 