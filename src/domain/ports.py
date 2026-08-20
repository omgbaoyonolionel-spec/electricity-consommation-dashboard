"""
Ports de la couche domaine : interfaces abstraites que l'infrastructure doit
implémenter, et que la couche application consomme sans jamais connaître les
détails techniques concrets (Tapo, PostgreSQL, ou n'importe quelle autre
technologie future).

Ajouter un nouveau moyen de collecte (ex: un autre modèle de prise) ou un
nouveau moyen de stockage (ex: TimescaleDB, InfluxDB) ne nécessite que
d'implémenter ces ports, sans toucher au domaine ni aux cas d'usage.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.models import DeviceReading


class DeviceClientPort(ABC):
    """Port pour récupérer un relevé de consommation depuis un appareil."""

    @abstractmethod
    async def read_energy(self, device_name: str, ip: str) -> DeviceReading:
        """Retourne le relevé instantané d'une prise identifiée par son IP."""
        raise NotImplementedError


class ReadingRepositoryPort(ABC):
    """Port pour la persistance et la lecture des relevés de consommation."""

    @abstractmethod
    async def save(self, reading: DeviceReading) -> None:
        """Enregistre un relevé unique."""
        raise NotImplementedError

    @abstractmethod
    async def save_many(self, readings: list[DeviceReading]) -> None:
        """Enregistre plusieurs relevés en une seule fois."""
        raise NotImplementedError

    @abstractmethod
    async def find_by_device(
        self, device_name: str, since: datetime, limit: int = 1000
    ) -> list[DeviceReading]:
        """
        Récupère l'historique des relevés d'une prise depuis une date donnée.

        Réservé aux futurs cas d'usage d'exploitation de la donnée
        (agrégations, graphiques, alertes...) : la collecte ne s'en sert pas.
        """
        raise NotImplementedError