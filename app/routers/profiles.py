from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ..database import SessionLocal
from ..main import TEMPLATE_DIR
from ..models import Profile

router = APIRouter()


def _templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATE_DIR))


def _get_profile_or_404(db, profile_id: int) -> Profile:
    profile = db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, f"Profil {profile_id} nicht gefunden")
    return profile


@router.get("/profiles", response_class=HTMLResponse)
def list_profiles(request: Request):
    with SessionLocal() as db:
        profiles = db.execute(select(Profile).order_by(Profile.id)).scalars().all()
    return _templates().TemplateResponse(
        request, "profiles.html", {"profiles": profiles}
    )


@router.get("/profiles/new", response_class=HTMLResponse)
def new_profile(request: Request):
    return _templates().TemplateResponse(request, "profile_form.html", {"p": None})


@router.get("/profiles/{profile_id}", response_class=HTMLResponse)
def edit_profile(request: Request, profile_id: int):
    with SessionLocal() as db:
        p = _get_profile_or_404(db, profile_id)
    return _templates().TemplateResponse(request, "profile_form.html", {"p": p})


@router.post("/profiles/save")
def save_profile(
    profile_id: int | None = Form(default=None),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(default=""),
    address: str = Form(default=""),
    city: str = Form(default=""),
    zip_code: str = Form(default=""),
    country: str = Form(default="DE"),
    phone: str = Form(default=""),
    date_of_birth: str = Form(default=""),
    notes: str = Form(default=""),
):
    with SessionLocal() as db:
        if profile_id:
            p = _get_profile_or_404(db, profile_id)
        else:
            p = Profile()
            db.add(p)
        p.first_name = first_name.strip()
        p.last_name = last_name.strip()
        p.email = email.strip()
        p.address = address.strip()
        p.city = city.strip()
        p.zip_code = zip_code.strip()
        p.country = country.strip()[:2].upper()
        p.phone = phone.strip()
        p.date_of_birth = date_of_birth.strip()
        p.notes = notes.strip()
        db.commit()
    return RedirectResponse("/profiles", status_code=303)


@router.post("/profiles/{profile_id}/delete")
def delete_profile(profile_id: int):
    with SessionLocal() as db:
        p = _get_profile_or_404(db, profile_id)
        db.delete(p)
        db.commit()
    return RedirectResponse("/profiles", status_code=303)
