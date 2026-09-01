"""Seed-Datenbank: eraser-Broker (MIT) + kuratierte EU-/DE-Broker."""

import json
import logging
from pathlib import Path

from sqlalchemy import select
from .database import SessionLocal
from .models import Broker

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).resolve().parent / "data" / "brokers_seed.json"

# Kuratierte EU-/DE-Broker (DSGVO/DSA-relevant). Quellen: öffentliche
# Datenschutzerklärungen und Auskunfts-/Löschungsadressen der Anbieter.
EU_BROKERS = [
    {
        "id": "schufa-holding",
        "name": "SCHUFA Holding AG",
        "email": "datenschutz@schufa.de",
        "website": "https://www.schufa.de",
        "opt_out_url": "https://www.meineschufa.de",
        "region": "eu",
        "category": "people-search",
    },
    {
        "id": "boniversum",
        "name": "Boniversum GmbH (CRIF)",
        "email": "datenschutz@boniversum.de",
        "website": "https://www.boniversum.de",
        "opt_out_url": "https://www.boniversum.de/datenschutz/",
        "region": "eu",
        "category": "people-search",
    },
    {
        "id": "crif-at-informs",
        "name": "CRIF GmbH (infoscore Österreich)",
        "email": "datenschutz@crif.at",
        "website": "https://www.crif.at",
        "opt_out_url": "https://www.crif.at/datenschutz/",
        "region": "eu",
        "category": "people-search",
    },
    {
        "id": "delta-vista",
        "name": "DeltaVista GmbH",
        "email": "datenschutz@deltavista.com",
        "website": "https://www.deltavista.com",
        "opt_out_url": "https://www.deltavista.com/datenschutz/",
        "region": "eu",
        "category": "people-search",
    },
    {
        "id": "buergel",
        "name": "BÜRGEL Wirtschaftsinformationen",
        "email": "datenschutz@buergel.de",
        "website": "https://www.buergel.de",
        "opt_out_url": "https://www.buergel.de/datenschutz/",
        "region": "eu",
        "category": "people-search",
    },
    {
        "id": "deltastand",
        "name": "Creditreform (Creditreform-Büro)",
        "email": "datenschutz@creditreform.de",
        "website": "https://www.creditreform.de",
        "opt_out_url": "https://www.creditreform.de/datenschutz",
        "region": "eu",
        "category": "people-search",
    },
    {
        "id": "klarmelde",
        "name": "klarmelde.de (Rechtsdienstleister)",
        "email": "datenschutz@klarmelde.de",
        "website": "https://www.klarmelde.de",
        "opt_out_url": "https://www.klarmelde.de/datenschutz",
        "region": "eu",
        "category": "marketing",
    },
    {
        "id": "the-trade-desk-eu",
        "name": "The Trade Desk (EU)",
        "email": "privacy@thetradedesk.com",
        "website": "https://www.thetradedesk.com",
        "opt_out_url": "https://www.adsrvr.org",
        "region": "eu",
        "category": "adtech",
    },
]


def load_seed() -> list[dict]:
    if SEED_FILE.exists():
        with SEED_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    logger.warning("Seed-Datei fehlt: %s", SEED_FILE)
    return []


def seed_brokers() -> int:
    """Füllt Broker-Tabelle einmalig. Liefert Anzahl neu eingefügter Broker."""
    entries = load_seed() + EU_BROKERS
    inserted = 0
    with SessionLocal() as db:
        existing = {b[0] for b in db.query(Broker.broker_id).all()}
        for entry in entries:
            broker_id = entry.get("id")
            if not broker_id or broker_id in existing:
                continue
            db.add(
                Broker(
                    broker_id=broker_id,
                    name=entry.get("name", broker_id),
                    email=entry.get("email", ""),
                    website=entry.get("website", ""),
                    opt_out_url=entry.get("opt_out_url", ""),
                    region=entry.get("region", "global"),
                    category=entry.get("category", "marketing"),
                    source="curated" if entry in EU_BROKERS else "eraser",
                )
            )
            existing.add(broker_id)
            inserted += 1
        db.commit()
    return inserted


def get_broker_by_broker_id(db: SessionLocal, broker_id: str) -> Broker | None:
    return db.execute(
        select(Broker).where(Broker.broker_id == broker_id)
    ).scalar_one_or_none()
