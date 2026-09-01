from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from .. import ollama_client
from ..config import get_settings
from ..database import SessionLocal
from ..mailer import MailError, smtp_ready, send_request
from ..main import TEMPLATE_DIR
from ..models import (
    Broker,
    LawBasis,
    Profile,
    RequestStatus,
    TakedownRequest,
    utcnow,
)
from ..templates_mail import build_request_text

router = APIRouter()


def _templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATE_DIR))


def _get_request_or_404(db, request_id: int) -> TakedownRequest:
    tr = db.get(TakedownRequest, request_id)
    if tr is None:
        raise HTTPException(404, f"Anfrage {request_id} nicht gefunden")
    return tr


def _load_refs(db, tr: TakedownRequest) -> tuple[Profile, Broker]:
    profile = db.get(Profile, tr.profile_id)
    broker = db.get(Broker, tr.broker_id)
    if profile is None or broker is None:
        raise HTTPException(500, "Profil oder Broker fehlt (Datenbank inkonsistent)")
    return profile, broker


def _append_history(tr: TakedownRequest, text: str) -> None:
    history = list(tr.history or [])
    history.append({"at": utcnow().isoformat(), "entry": text})
    tr.history = history


@router.get("/requests", response_class=HTMLResponse)
def list_requests(request: Request, status: str = ""):
    stmt = select(TakedownRequest).order_by(TakedownRequest.updated_at.desc())
    if status:
        try:
            wanted = RequestStatus(status)
        except ValueError:
            wanted = None
        if wanted:
            stmt = stmt.where(TakedownRequest.status == wanted)
    with SessionLocal() as db:
        rows = db.execute(stmt).scalars().all()
        broker_names = {
            b.id: b.name
            for b in db.execute(
                select(Broker.id, Broker.name).where(
                    Broker.id.in_([r.broker_id for r in rows] or [0])
                )
            ).all()
        }
        profile_names = {
            p.id: f"{p.first_name} {p.last_name}"
            for p in db.execute(
                select(Profile.id, Profile.first_name, Profile.last_name).where(
                    Profile.id.in_([r.profile_id for r in rows] or [0])
                )
            ).all()
        }
    return _templates().TemplateResponse(
        request,
        "requests.html",
        {
            "rows": rows,
            "broker_names": broker_names,
            "profile_names": profile_names,
            "status_filter": status,
            "statuses": [s.value for s in RequestStatus],
            "smtp_ready": smtp_ready(),
            "ollama_enabled": ollama_client.is_enabled(),
        },
    )


@router.get("/requests/new", response_class=HTMLResponse)
def new_request_form(
    request: Request,
    profile_id: int | None = None,
    broker_id: int | None = None,
):
    with SessionLocal() as db:
        profiles = db.execute(select(Profile).order_by(Profile.id)).scalars().all()
        brokers = db.execute(select(Broker).order_by(Broker.name)).scalars().all()
    return _templates().TemplateResponse(
        request,
        "request_form.html",
        {
            "profiles": profiles,
            "brokers": brokers,
            "preselect_profile": profile_id,
            "preselect_broker": broker_id,
            "laws": [l.value for l in LawBasis],
        },
    )


@router.post("/requests/create")
def create_request(
    profile_id: int = Form(...),
    broker_pk: int = Form(...),
    law_basis: str = Form(default=LawBasis.gdpr.value),
):
    with SessionLocal() as db:
        profile = db.get(Profile, profile_id)
        broker = db.get(Broker, broker_pk)
        if profile is None or broker is None:
            raise HTTPException(400, "Profil oder Broker ungültig")
        try:
            law = LawBasis(law_basis)
        except ValueError:
            law = LawBasis.generic
        tr = TakedownRequest(
            profile_id=profile_id,
            broker_id=broker_pk,
            status=RequestStatus.planned,
            law_basis=law,
        )
        tr.request_text = build_request_text(profile, broker.name, law)
        db.add(tr)
        db.commit()
    return RedirectResponse(f"/requests/{tr.id}", status_code=303)


@router.get("/requests/{request_id}", response_class=HTMLResponse)
def show_request(request: Request, request_id: int):
    with SessionLocal() as db:
        tr = _get_request_or_404(db, request_id)
        profile, broker = _load_refs(db, tr)
        law = tr.law_basis
    return _templates().TemplateResponse(
        request,
        "request_detail.html",
        {
            "tr": tr,
            "profile": profile,
            "broker": broker,
            "law": law.value,
            "statuses": [s.value for s in RequestStatus],
            "smtp_ready": smtp_ready(),
            "ollama_enabled": ollama_client.is_enabled(),
        },
    )


@router.post("/requests/{request_id}/regenerate")
def regenerate_text(request_id: int, law_basis: str = Form(default="")):
    with SessionLocal() as db:
        tr = _get_request_or_404(db, request_id)
        profile, broker = _load_refs(db, tr)
        try:
            law = LawBasis(law_basis) if law_basis else tr.law_basis
        except ValueError:
            law = tr.law_basis
        tr.law_basis = law
        tr.request_text = build_request_text(profile, broker.name, law)
        _append_history(tr, f"Anfragetext neu erzeugt ({law.value})")
        db.commit()
    return RedirectResponse(f"/requests/{request_id}", status_code=303)


@router.post("/requests/{request_id}/send")
def mark_sent(request_id: int):
    with SessionLocal() as db:
        tr = _get_request_or_404(db, request_id)
        _, broker = _load_refs(db, tr)
        if not broker.email:
            raise HTTPException(400, "Broker ohne E-Mail – Text manuell über Opt-out-Link senden")
        if not smtp_ready():
            raise HTTPException(400, "SMTP nicht konfiguriert (Einstellungen) – Text manuell kopieren")
        subjects = {
            LawBasis.gdpr: "Antrag auf Löschung personenbezogener Daten gemäß Art. 17 DSGVO",
            LawBasis.ccpa: "Deletion Request under CCPA (Cal. Civ. Code § 1798.105)",
            LawBasis.generic: "Privacy Deletion Request",
        }
        subject = subjects.get(tr.law_basis, "Privacy Deletion Request")
        try:
            result = send_request(broker.email, subject, tr.request_text)
        except MailError as exc:
            raise HTTPException(400, str(exc))
        tr.status = RequestStatus.sent
        tr.sent_at = utcnow()
        tr.response_note = result
        _append_history(tr, f"Per SMTP versendet an {broker.email}")
        db.commit()
    return RedirectResponse(f"/requests/{request_id}", status_code=303)


@router.post("/requests/{request_id}/status")
def set_status(request_id: int, status: str = Form(...)):
    with SessionLocal() as db:
        tr = _get_request_or_404(db, request_id)
        try:
            new_status = RequestStatus(status)
        except ValueError:
            raise HTTPException(400, f"Unbekannter Status: {status}")
        tr.status = new_status
        now = utcnow()
        if new_status == RequestStatus.sent:
            tr.sent_at = now
        if new_status == RequestStatus.confirmed:
            tr.response_at = now
        if new_status == RequestStatus.deleted:
            tr.deleted_at = now
            tr.next_check_at = now + timedelta(days=get_settings().recheck_days)
            tr.confirmation_pending = False
        if new_status == RequestStatus.resurfaced:
            tr.next_check_at = now + timedelta(days=7)
        _append_history(tr, f"Status → {new_status.value}")
        db.commit()
    return RedirectResponse(f"/requests/{request_id}", status_code=303)


@router.get("/rechecks", response_class=HTMLResponse)
def due_rechecks(request: Request):
    now = utcnow()
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(TakedownRequest)
                .where(TakedownRequest.next_check_at.is_not(None))
                .where(TakedownRequest.next_check_at <= now)
                .order_by(TakedownRequest.next_check_at)
            )
            .scalars()
            .all()
        )
        broker_names = {
            b.id: b.name
            for b in db.execute(
                select(Broker.id, Broker.name).where(
                    Broker.id.in_([r.broker_id for r in rows] or [0])
                )
            ).all()
        }
    return _templates().TemplateResponse(
        request,
        "rechecks.html",
        {"rows": rows, "broker_names": broker_names, "now": now},
    )


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request):
    return _templates().TemplateResponse(
        request, "assistant.html", {"ollama_enabled": ollama_client.is_enabled()}
    )


@router.post("/assistant/ask")
async def assistant_ask(request: Request):
    import json as _json

    form = await request.form()
    prompt = str(form.get("prompt", "")).strip()
    if not prompt:
        return _templates().TemplateResponse(
            request,
            "assistant.html",
            {"ollama_enabled": ollama_client.is_enabled(), "answer": None,
             "error": "Bitte eine Frage eingeben."},
        )
    answer = ""
    error = ""
    try:
        answer = await ollama_client.chat(prompt, ollama_client.SYSTEM_PROMPT)
    except ollama_client.OllamaError as exc:
        error = str(exc)
    return _templates().TemplateResponse(
        request,
        "assistant.html",
        {"ollama_enabled": ollama_client.is_enabled(), "answer": answer, "error": error,
         "prompt": prompt, "model": get_settings().ollama_model},
    )
