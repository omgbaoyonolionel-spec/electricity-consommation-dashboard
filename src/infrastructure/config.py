"""
Contient la configuration technique du projet. 
"""

from __future__ import annotations
 
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _parse_devices(raw: str) -> dict[str, str]:
    devices: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, _, ip = pair.partition("=")
        if name and ip:
            devices[name.strip()] = ip.strip()
    return devices
 
 
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
 
    tapo_email: str
    tapo_password: str
    pg_dsn: str = "postgresql://tapo:tapo_password@postgres:5432/tapo"
 
    tapo_devices_raw: str = Field(default="", alias="TAPO_DEVICES")
 
    @property
    def devices(self) -> dict[str, str]:
        return _parse_devices(self.tapo_devices_raw)
 
    @model_validator(mode="after")
    def _check_devices_not_empty(self) -> "Settings":
        if not self.devices:
            raise ValueError(
                "Aucune prise configurée (variable TAPO_DEVICES vide) — voir .env.example"
            )
        return self