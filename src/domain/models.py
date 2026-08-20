"""
Modèles métier de la couche domaine, exprimés en Pydantic.

Compromis assumé : le domaine dépend ici de Pydantic (ce n'est plus du
"zéro dépendance externe" strict), en échange de la validation automatique
des données et d'une sérialisation JSON prête à l'emploi pour les futurs
cas d'usage (API, export, dashboard...).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Device(BaseModel):
    """Une prise connectée telle que configurée par l'utilisateur."""

    model_config = ConfigDict(frozen=True)

    name: str
    ip: str


class DeviceReading(BaseModel):
    """Un relevé de consommation instantané pour une prise donnée."""

    model_config = ConfigDict(frozen=True)

    device_name: str
    ip: str
    timestamp: datetime
    current_power_mw: int = Field(ge=0)
    today_energy_wh: int = Field(ge=0)
    month_energy_wh: int = Field(ge=0)
    on_state: bool