from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from ..database import SessionLocal
from ..main import TEMPLATE_DIR
from ..models import Broker, Profile

router = APIRouter()

PAGE_SIZE = 50


def _templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATE_DIR))


def _get_broker_or_404(db, broker_id: int) -> Broker:
    broker = db.get(Broker, broker_id)
    if broker is None:
        raise HTTPException(404, f"Broker {broker_id} nicht gefunden")
    return broker


@router.get("/brokers", response_class=HTMLResponse)
def list_brokers(
    request: Request,
    q: str = "",
    region: str = "",
    page: int = 1,
):
    filters = []
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(Broker.name.ilike(like), Broker.broker_id.ilike(like)))
    if region:
        filters.append(Broker.region == region)

    base = select(Broker).where(*filters) if filters else select(Broker)
    count_stmt = select(func.count()).select_from(Broker).where(*filters) if filters else select(func.count()).select_from(Broker)
    with SessionLocal() as db:
        total = db.execute(count_stmt).scalar() or 0
        page = max(1, page)
        rows = (
            db.execute(
                base.order_by(Broker.name)
                .offset((page - 1) * PAGE_SIZE)
                .limit(PAGE_SIZE)
            )
            .scalars()
            .all()
        )
        regions = sorted({r[0] for r in db.execute(select(Broker.region).distinct()).all()})
        profiles = db.execute(select(Profile).order_by(Profile.id)).scalars().all()
    return _templates().TemplateResponse(
        request,
        "brokers.html",
        {
            "brokers": rows,
            "q": q,
            "region": region,
            "regions": regions,
            "page": page,
            "total": total,
            "page_size": PAGE_SIZE,
            "profiles": profiles,
        },
    )


@router.get("/brokers/new", response_class=HTMLResponse)
def new_broker(request: Request):
    return _templates().TemplateResponse(request, "broker_form.html", {"b": None})


@router.get("/brokers/{broker_id}", response_class=HTMLResponse)
def edit_broker(request: Request, broker_id: int):
    with SessionLocal() as db:
        b = _get_broker_or_404(db, broker_id)
    return _templates().TemplateResponse(request, "broker_form.html", {"b": b})


@router.post("/brokers/save")
def save_broker(
    broker_pk: int | None = Form(default=None),
    name: str = Form(...),
    email: str = Form(default=""),
    website: str = Form(default=""),
    opt_out_url: str = Form(default=""),
    region: str = Form(default="global"),
    category: str = Form(default="marketing"),
    notes: str = Form(default=""),
):
    with SessionLocal() as db:
        if broker_pk:
            b = _get_broker_or_404(db, broker_pk)
        else:
            slug = name.strip().lower().replace(" ", "-")[:100]
            b = Broker(broker_id=slug)
            db.add(b)
        b.name = name.strip()
        b.email = email.strip()
        b.website = website.strip()
        b.opt_out_url = opt_out_url.strip()
        b.region = region.strip()
        b.category = category.strip()
        b.notes = notes.strip()
        b.source = "manuell"
        db.commit()
    return RedirectResponse("/brokers", status_code=303)


@router.post("/brokers/{broker_pk}/delete")
def delete_broker(broker_pk: int):
    with SessionLocal() as db:
        b = _get_broker_or_404(db, broker_pk)
        db.delete(b)
        db.commit()
    return RedirectResponse("/brokers", status_code=303)
