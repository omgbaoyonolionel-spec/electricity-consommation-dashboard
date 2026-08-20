"""Modèle metier de la couche domain
Permet la validation automatique des données qu'on extrait
"""

from datetime import datetime
from pydantic import BasedModel, ConfigDict, Field

class Device(BaseModel):
    """Cette classe stocke les configurations des éléments du réseau. Exemple : prise, chauffe eau
    """
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