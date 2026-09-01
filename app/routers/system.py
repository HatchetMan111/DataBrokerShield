import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .. import ollama_client
from ..config import get_settings
from ..database import SessionLocal
from ..models import Broker, Profile, TakedownRequest
from ..seed import seed_brokers

router = APIRouter()


def _env_file() -> Path:
    return Path(get_settings().env_file)


def _read_env() -> dict[str, str]:
    env_file = _env_file()
    env: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    env_file = _env_file()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(f"{k}={v}" for k, v in sorted(env.items())) + "\n")
    env_file.chmod(0o600)


@router.post("/settings/save")
async def save_settings(request: Request):
    form = await request.form()
    env = _read_env()

    mapping = {
        "smtp_host": "BROKERSHIELD_SMTP_HOST",
        "smtp_user": "BROKERSHIELD_SMTP_USER",
        "smtp_from": "BROKERSHIELD_SMTP_FROM",
        "smtp_port": "BROKERSHIELD_SMTP_PORT",
        "ollama_url": "BROKERSHIELD_OLLAMA_URL",
        "ollama_model": "BROKERSHIELD_OLLAMA_MODEL",
        "recheck_days": "BROKERSHIELD_RECHECK_DAYS",
    }
    for field, key in mapping.items():
        val = str(form.get(field, "")).strip()
        # Leere Eingabe = Eintrag entfernen (z. B. Ollama deaktivieren);
        # Passwort bleibt separat: nur setzen, nie per Leerstring löschen.
        if val:
            env[key] = val
        else:
            env.pop(key, None)

    pw = str(form.get("smtp_password", "")).strip()
    if pw:
        env["BROKERSHIELD_SMTP_PASSWORD"] = pw

    # Admin-Passwort nur ändern, wenn explizit etwas eingegeben wurde.
    new_admin_pw = str(form.get("admin_password", "")).strip()
    if new_admin_pw:
        env["BROKERSHIELD_ADMIN_PASSWORD"] = new_admin_pw

    try:
        _write_env(env)
    except OSError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Konnte {_env_file()} nicht schreiben: {exc!r}"},
            status_code=500,
        )

    get_settings.cache_clear()
    return JSONResponse(
        {
            "ok": True,
            "note": "Einstellungen gespeichert – Dienst-Neustart empfohlen: systemctl restart brokershield",
        }
    )


@router.get("/api/health")
def health():
    with SessionLocal() as db:
        counts = {
            "brokers": db.execute(select(func.count()).select_from(Broker)).scalar(),
            "profiles": db.execute(select(func.count()).select_from(Profile)).scalar(),
            "requests": db.execute(select(func.count()).select_from(TakedownRequest)).scalar(),
        }
    return {"status": "ok", **counts}


@router.post("/api/reseed")
def reseed():
    inserted = seed_brokers()
    return {"ok": True, "inserted": inserted}


@router.get("/api/ollama/status")
async def ollama_status():
    return await ollama_client.healthy()
