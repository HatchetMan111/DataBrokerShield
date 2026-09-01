import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import auth_middleware, is_authenticated, login_response, logout_response
from .config import BASE_DIR, get_settings
from .database import Base, SessionLocal, engine
from .seed import seed_brokers

settings = get_settings()

STATIC_DIR = BASE_DIR / "app" / "static"
TEMPLATE_DIR = BASE_DIR / "app" / "templates"

logger = logging.getLogger("brokershield")


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)


def seed_if_empty() -> int:
    with SessionLocal() as db:
        from sqlalchemy import func, select

        from .models import Broker
        count = db.execute(select(func.count()).select_from(Broker)).scalar() or 0
    if count == 0:
        return seed_brokers()
    return 0


@asynccontextmanager
async def lifespan(_: FastAPI):
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    ensure_schema()
    inserted = seed_if_empty()
    if inserted:
        logger.info("Seed: %d Broker eingefügt", inserted)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.middleware("http")(auth_middleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

from .routers import brokers, dashboard, profiles, requests, settings as settings_routes, system  # noqa: E402

app.include_router(dashboard.router)
app.include_router(profiles.router)
app.include_router(brokers.router)
app.include_router(requests.router)
app.include_router(settings_routes.router)
app.include_router(system.router)


@app.get("/login")
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    resp = login_response(str(form.get("password", "")))
    if resp is None:
        from fastapi.templating import Jinja2Templates

        templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Passwort falsch"},
            status_code=401,
        )
    return resp


@app.get("/logout")
def logout():
    return logout_response()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    return templates.TemplateResponse(request, "help.html")
