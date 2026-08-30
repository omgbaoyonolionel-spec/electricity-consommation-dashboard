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

import asyncio
import logging

from src.domain.ports import DeviceClientPort, ReadingRepositoryPort

logger = logging.getLogger(__name__)

#: Délai maximal accordé à la lecture d'une prise (secondes).
#: Une prise saine sur le réseau local répond en moins d'une seconde ;
#: au-delà, on abandonne ce cycle pour ne pas retarder la boucle de collecte.
READ_TIMEOUT_S = 3.0


class CollectReadingsUseCase:
    def __init__(
        self,
        device_client: DeviceClientPort,
        repository: ReadingRepositoryPort,
    ) -> None:
        self._device_client = device_client
        self._repository = repository

    async def _collect_one(self, name: str, ip: str) -> None:
        """Lit une prise (avec délai borné) et persiste son relevé."""
        try:
            reading = await asyncio.wait_for(
                self._device_client.read_energy(name, ip),
                timeout=READ_TIMEOUT_S,
            )
            await self._repository.save(reading)
            logger.info(
                "%s (%s) : %s mW, état=%s -> enregistré",
                name,
                ip,
                reading.current_power_mw,
                "ON" if reading.on_state else "OFF",
            )
        except asyncio.TimeoutError:
            logger.warning(
                "%s (%s) : injoignable (> %.0f s), cycle ignoré pour cette prise",
                name,
                ip,
                READ_TIMEOUT_S,
            )
        except Exception:
            logger.exception("Échec de la collecte pour %s (%s)", name, ip)

    async def execute(self, devices: dict[str, str]) -> None:
        """Interroge toutes les prises EN PARALLÈLE et enregistre leurs relevés.

        Chaque prise est isolée des autres, en erreur comme en latence :
        une prise injoignable coûte au plus READ_TIMEOUT_S au cycle,
        sans retarder ni bloquer la collecte des prises saines.
        """
        await asyncio.gather(
            *(self._collect_one(name, ip) for name, ip in devices.items())
        )