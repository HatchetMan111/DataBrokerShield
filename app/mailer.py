import asyncio
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

from .config import get_settings


class MailError(RuntimeError):
    pass


def smtp_ready() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send_request(broker_email: str, subject: str, body: str) -> str:
    """Versendet eine Löschungsanfrage per SMTP. Liefert Status-Text."""
    s = get_settings()
    if not smtp_ready():
        raise MailError(
            "SMTP nicht konfiguriert (BROKERSHIELD_SMTP_HOST/-FROM fehlen). "
            "Text manuell kopieren oder SMTP in den Einstellungen hinterlegen."
        )
    if not broker_email:
        raise MailError("Broker hat keine Kontakt-E-Mail hinterlegt.")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = s.smtp_from
    msg["To"] = broker_email
    msg["Date"] = formatdate(localtime=True)

    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as server:
            server.starttls()
            if s.smtp_user and s.smtp_password:
                server.login(s.smtp_user, s.smtp_password)
            server.sendmail(s.smtp_from, [broker_email], msg.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"SMTP-Versand fehlgeschlagen: {exc!r}") from exc
    return f"Anfrage an {broker_email} per SMTP versendet."


def asyncio_send(broker_email: str, subject: str, body: str) -> str:
    """Thread-Offload für FastAPI-Endpunkte."""
    return asyncio.get_running_loop().run_in_executor(
        None, send_request, broker_email, subject, body
    )
