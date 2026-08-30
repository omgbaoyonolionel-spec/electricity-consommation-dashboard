"""
Point de composition (composition root) et point d'entrée du programme.
C'est le seul module autorisé à connaître à la fois le domaine,
l'infrastructure et l'application : il assemble les implémentations
concrètes (Tapo, PostgreSQL) et les injecte dans les cas d'usage.
"""
import argparse
import asyncio
import logging

from src.application.collect_readings import CollectReadingsUseCase
from src.infrastructure.config import Settings
from src.infrastructure.postgres_repository import PostgresReadingRepository
from src.infrastructure.tapo_client import TapoDeviceClient

logger = logging.getLogger(__name__)


async def run(loop_seconds: int) -> None:
    settings = Settings()
    device_client = TapoDeviceClient(settings.tapo_email, settings.tapo_password)
    repository = await PostgresReadingRepository.create(settings.pg_dsn)
    use_case = CollectReadingsUseCase(device_client, repository)
    try:
        if loop_seconds > 0:
            logger.info("Collecte en boucle toutes les %ss", loop_seconds)
            while True:
                debut = asyncio.get_event_loop().time()
                await use_case.execute(settings.devices)
                duree = asyncio.get_event_loop().time() - debut
                attente = loop_seconds - duree
                if attente > 0:
                    await asyncio.sleep(attente)
                else:
                    logger.warning(
                        "Cycle plus long (%.1f s) que l'intervalle (%s s) : "
                        "collecte immédiate", duree, loop_seconds,
                    )
        else:
            await use_case.execute(settings.devices)
    finally:
        await repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Collecteur Tapo -> PostgreSQL")
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Collecte en boucle toutes les N secondes (0 = une seule fois)",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(run(args.loop))


if __name__ == "__main__":
    main()