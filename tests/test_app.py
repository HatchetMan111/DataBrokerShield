import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("BROKERSHIELD_DB", ":memory:")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        c.post("/login", data={"password": get_settings().admin_password})
        yield c


@pytest.fixture()
def profile_id(client):
    resp = client.post(
        "/profiles/save",
        data={
            "first_name": "Erika",
            "last_name": "Muster",
            "email": "erika@example.com",
            "address": "Testweg 1",
            "city": "Berlin",
            "zip_code": "10115",
            "country": "DE",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return 1


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seed_brokers_loaded(client):
    r = client.get("/api/health")
    data = r.json()
    assert data["status"] == "ok"
    assert data["brokers"] >= 700  # eraser-Seed + EU-Broker


def test_dashboard_requires_auth(client):
    from app.config import get_settings as gs

    gs.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        r = anon.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"


def test_profiles_crud(client, profile_id):
    r = client.get("/profiles")
    assert "Erika" in r.text
    r = client.post(
        "/profiles/save",
        data={
            "profile_id": profile_id,
            "first_name": "Erika",
            "last_name": "Musterfrau",
            "email": "",
            "address": "",
            "city": "",
            "zip_code": "",
            "country": "DE",
            "phone": "",
            "date_of_birth": "",
            "notes": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/profiles")
    assert "Musterfrau" in r.text


def test_brokers_search(client):
    r = client.get("/brokers", params={"q": "spokeo"})
    assert r.status_code == 200
    assert "Spokeo" in r.text
    r = client.get("/brokers", params={"region": "eu"})
    assert "SCHUFA" in r.text


def test_request_lifecycle(client, profile_id):
    r = client.get("/brokers", params={"q": "spokeo"})
    assert "brokers/1" in r.text
    r = client.post(
        "/requests/create",
        data={"profile_id": profile_id, "broker_pk": 1, "law_basis": "DSGVO Art. 17"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    rid = r.headers["location"].rsplit("/", 1)[-1]

    r = client.get(f"/requests/{rid}")
    assert "Art. 17" in r.text
    assert "Muster" in r.text

    r = client.post(
        f"/requests/{rid}/status", data={"status": "gelöscht"}, follow_redirects=False
    )
    assert r.status_code == 303

    r = client.get("/rechecks")
    assert r.status_code == 200


def test_ollama_disabled_by_default(client):
    r = client.get("/api/ollama/status")
    data = r.json()
    assert data["enabled"] is False


def test_regenerate_text(client, profile_id):
    client.post(
        "/requests/create",
        data={"profile_id": profile_id, "broker_pk": 1, "law_basis": "CCPA"},
        follow_redirects=False,
    )
    r = client.get("/requests/1")
    assert "CCPA" in r.text


def test_settings_save_writes_env(client, tmp_path, monkeypatch):
    env_file = tmp_path / "brokershield.env"
    monkeypatch.setenv("BROKERSHIELD_ENV_FILE", str(env_file))
    get_settings.cache_clear()

    r = client.post(
        "/settings/save",
        data={
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_from": "x@example.com",
            "ollama_url": "http://ollama.lan:11434",
            "ollama_model": "llama3.1:8b",
            "recheck_days": "90",
            "admin_password": "neues-pw",
        },
    )
    data = r.json()
    assert data["ok"] is True

    content = env_file.read_text()
    assert "BROKERSHIELD_SMTP_HOST=smtp.example.com" in content
    assert "BROKERSHIELD_OLLAMA_URL=http://ollama.lan:11434" in content
    assert "BROKERSHIELD_ADMIN_PASSWORD=neues-pw" in content
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    # Passwort-Änderung hat Session ungültig gemacht → neu einloggen
    get_settings.cache_clear()
    client.post("/login", data={"password": "neues-pw"})

    # Leere Felder löschen Einträge (Ollama deaktivieren)
    r = client.post(
        "/settings/save",
        data={"ollama_url": "", "ollama_model": "", "smtp_host": "", "admin_password": ""},
    )
    assert r.json()["ok"] is True
    content = env_file.read_text()
    assert "BROKERSHIELD_OLLAMA_URL" not in content
    assert "BROKERSHIELD_ADMIN_PASSWORD=neues-pw" in content  # bleibt erhalten

    import os

    monkeypatch.delenv("BROKERSHIELD_ENV_FILE", raising=False)
    os.environ.pop("BROKERSHIELD_ENV_FILE", None)
    get_settings.cache_clear()


def test_reseed_is_post_only(client):
    r = client.get("/api/reseed", follow_redirects=False)
    assert r.status_code == 405
    r = client.post("/api/reseed")
    assert r.json()["ok"] is True


def test_help_page(client):
    r = client.get("/help")
    assert r.status_code == 200
    assert "Schritt für Schritt" in r.text
    assert "DSGVO Art. 17" in r.text
    assert "Bulk-Anfragen" in r.text


def test_bulk_create_requests(client, profile_id):
    # Zwei Broker auswählen → 2 Anfragen erstellen
    r = client.post(
        "/requests/bulk-create",
        data={
            "profile_id": profile_id,
            "broker_pks": [1, 2],
            "law_basis": "DSGVO Art. 17",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/requests"

    r = client.get("/requests")
    assert r.status_code == 200
    #mind. 2 Anfragen in der Liste
    assert r.text.count("geplant") >= 2

    # Detail-Ansicht der ersten Anfrage prüfen
    r = client.get("/requests/1")
    assert "Art. 17" in r.text
    assert "Muster" in r.text
