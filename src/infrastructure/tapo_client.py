"""
Implémentation concrète de DeviceClientPort pour les prises TP-Link Tapo
(modèles avec mesure d'énergie : P110, P115, P110M...).

Seule cette classe connaît la bibliothèque `tapo` et son protocole local
chiffré. Si demain vous ajoutez un autre modèle de prise ou une autre
marque, vous créez un nouvel adaptateur qui implémente le même port, sans
toucher au reste du système.
"""

from datetime import datetime, timezone

from tapo import ApiClient

from src.domain.models import DeviceReading
from src.domain.ports import DeviceClientPort


class TapoDeviceClient(DeviceClientPort):
    def __init__(self, email: str, password: str) -> None:
        self._client = ApiClient(email, password)

    async def read_energy(self, device_name: str, ip: str) -> DeviceReading:
        device = await self._client.p110(ip)
        info = await device.get_device_info()
        energy = await device.get_energy_usage()

        return DeviceReading(
            device_name=device_name,
            ip=ip,
            timestamp=datetime.now(timezone.utc),
            current_power_mw=energy.current_power,
            today_energy_wh=energy.today_energy,
            month_energy_wh=energy.month_energy,
            on_state=info.device_on,
        )