import os
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Ungültiger Wert für Umgebungsvariable {name}: {raw!r} (erwartet: Ganzzahl)"
        ) from exc


class Settings:
    def __init__(self) -> None:
        self.app_name: str = "BrokerShield"
        self.db_target: str = os.getenv(
            "BROKERSHIELD_DB", str(BASE_DIR / "data" / "brokershield.db")
        )
        self.admin_password: str = os.getenv(
            "BROKERSHIELD_ADMIN_PASSWORD", "admin"
        )

        # Ollama optional/extern: leer = deaktiviert
        self.ollama_url: str = os.getenv("BROKERSHIELD_OLLAMA_URL", "")
        self.ollama_model: str = os.getenv(
            "BROKERSHIELD_OLLAMA_MODEL", "llama3.1:8b"
        )

        # SMTP optional: nur für den direkten Mailversand der Anfragen
        self.smtp_host: str = os.getenv("BROKERSHIELD_SMTP_HOST", "")
        self.smtp_port: int = _int_env("BROKERSHIELD_SMTP_PORT", 587)
        self.smtp_user: str = os.getenv("BROKERSHIELD_SMTP_USER", "")
        self.smtp_password: str = os.getenv("BROKERSHIELD_SMTP_PASSWORD", "")
        self.smtp_from: str = os.getenv("BROKERSHIELD_SMTP_FROM", "")

        # Wiedervorlage: nach wie vielen Tagen soll erneut geprüft werden
        self.recheck_days: int = _int_env("BROKERSHIELD_RECHECK_DAYS", 180)

        # Persistente Einstellungsdatei der UI (Settings-Speichern).
        # Im Test überEnv überschreibbar.
        self.env_file: str = os.getenv(
            "BROKERSHIELD_ENV_FILE", "/etc/brokershield/brokershield.env"
        )

    @property
    def db_is_memory(self) -> bool:
        return self.db_target.strip() in {":memory:", "sqlite://"}

    @property
    def db_file(self) -> Path:
        return Path(self.db_target).expanduser().resolve()

    @property
    def db_url(self) -> str:
        if self.db_is_memory:
            return "sqlite://"
        return f"sqlite:///{self.db_file}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
