"""Optionale Ollama-Anbindung (externer Server). Nie hart erforderlich:
Fehlt OLLAMA_URL oder ist der Server nicht erreichbar, arbeiten alle
Endpoint-Funktionen mit klaren Fehlertexten statt Absturz weiter.
"""

import logging
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
TIMEOUT = httpx.Timeout(90.0, connect=5.0)


class OllamaError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(get_settings().ollama_url.strip())


def ollama_url() -> str:
    return get_settings().ollama_url.strip().rstrip("/")


async def chat(prompt: str, system: str = "") -> str:
    if not is_enabled():
        raise OllamaError(
            "Ollama nicht konfiguriert (BROKERSHIELD_OLLAMA_URL leer). "
            "UI: Einstellungen → Ollama-URL setzen."
        )
    payload: dict[str, Any] = {
        "model": get_settings().ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{ollama_url()}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
    except httpx.HTTPError as exc:
        raise OllamaError(
            f"Ollama nicht erreichbar unter {ollama_url()} "
            f"(HTTP-Fehler: {exc!r}). Server/Modell prüfen."
        ) from exc


async def healthy() -> dict[str, Any]:
    """Liefert Status-Info für UI/Diagnose, wirft nie."""
    if not is_enabled():
        return {"enabled": False, "ok": False, "error": "nicht konfiguriert"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{ollama_url()}/api/tags")
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return {
                "enabled": True,
                "ok": True,
                "models": models,
                "model": get_settings().ollama_model,
            }
    except httpx.HTTPError as exc:
        return {"enabled": True, "ok": False, "error": repr(exc)}


SYSTEM_PROMPT = (
    "Du bist ein präziser Datenschutz-Assistent. Du hilfst, Löschungsanfragen "
    "an Datenbroker zu formulieren (DSGVO Art. 17, CCPA). Antworte klar, "
    "rechtskonform aber ohne Rechtsberatung, auf Deutsch."
)
