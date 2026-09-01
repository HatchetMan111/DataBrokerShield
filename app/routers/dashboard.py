from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from ..database import SessionLocal
from ..main import TEMPLATE_DIR
from ..models import Broker, Profile, RequestStatus, TakedownRequest
from .. import ollama_client

router = APIRouter()


def _count(db, model, *where):
    stmt = select(func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return db.execute(stmt).scalar() or 0


def status_rows(db) -> list[dict]:
    rows = (
        db.execute(
            select(TakedownRequest.status, func.count())
            .group_by(TakedownRequest.status)
            .order_by(TakedownRequest.status)
        )
        .all()
    )
    by_status = {r[0]: r[1] for r in rows}
    return [
        {"status": s, "count": by_status.pop(s, 0)}
        for s in RequestStatus
    ] + [
        {"status": k, "count": v} for k, v in by_status.items()
    ]


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with SessionLocal() as db:
        stats = {
            "brokers": _count(db, Broker),
            "profiles": _count(db, Profile),
            "requests": _count(db, TakedownRequest),
            "deleted": _count(db, TakedownRequest, TakedownRequest.status == RequestStatus.deleted),
            "pending_manual": _count(
                db,
                TakedownRequest,
                TakedownRequest.confirmation_pending.is_(True),
            ),
            "due_recheck": _count(
                db,
                TakedownRequest,
                TakedownRequest.next_check_at.is_not(None),
                TakedownRequest.next_check_at <= func.now(),
            ),
        }
        rows = status_rows(db)
        recent = db.execute(
            select(TakedownRequest).order_by(TakedownRequest.updated_at.desc()).limit(8)
        ).scalars().all()
        # Broker-Namen für Recent-Liste nachladen
        broker_names = {
            b.id: b.name
            for b in db.execute(
                select(Broker.id, Broker.name).where(
                    Broker.id.in_([r.broker_id for r in recent] or [0])
                )
            ).all()
        }
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "status_rows": rows,
            "recent": [
                {
                    "id": r.id,
                    "broker": broker_names.get(r.broker_id, f"#{r.broker_id}"),
                    "status": r.status.value,
                    "updated": r.updated_at,
                }
                for r in recent
            ],
            "ollama_enabled": ollama_client.is_enabled(),
        },
    )
