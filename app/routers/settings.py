from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import ollama_client
from ..config import get_settings
from ..main import TEMPLATE_DIR

router = APIRouter()


def _templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, saved: int = 0):
    s = get_settings()
    ollama_status = await ollama_client.healthy()
    return _templates().TemplateResponse(
        request,
        "settings.html",
        {
            "saved": saved,
            "smtp": {
                "host": s.smtp_host,
                "port": s.smtp_port,
                "user": s.smtp_user,
                "from": s.smtp_from,
                "ready": bool(s.smtp_host and s.smtp_from),
                "has_password": bool(s.smtp_password),
            },
            "ollama": {
                "url": s.ollama_url,
                "model": s.ollama_model,
                "status": ollama_status,
            },
            "recheck_days": s.recheck_days,
        },
    )
