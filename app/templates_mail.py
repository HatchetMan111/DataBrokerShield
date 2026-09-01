"""Brief-/Mail-Vorlagen für Löschungsanfragen (DSGVO, CCPA, generisch)."""

from .models import LawBasis, Profile


def _gdpr_body(p: Profile, broker_name: str) -> str:
    address = ", ".join(x for x in [p.address, f"{p.zip_code} {p.city}".strip(), p.country] if x)
    lines = [
        f"Betreff: Antrag auf Löschung personenbezogener Daten gemäß Art. 17 DSGVO",
        "",
        f"Sehr geehrte Damen und Herren bei {broker_name},",
        "",
        "hiermit fordere ich Sie gemäß Art. 17 der Datenschutz-Grundverordnung (DSGVO) auf,",
        "sämtliche personenbezogenen Daten, die Sie über mich gespeichert haben, unverzüglich",
        "zu löschen. Bitte bestätigen Sie mir die Löschung schriftlich bzw. per E-Mail.",
        "",
        "Zu meiner Identifikation:",
        f"  Name           : {p.first_name} {p.last_name}",
    ]
    if address:
        lines.append(f"  Anschrift      : {address}")
    if p.email:
        lines.append(f"  E-Mail         : {p.email}")
    if p.phone:
        lines.append(f"  Telefon        : {p.phone}")
    if p.date_of_birth:
        lines.append(f"  Geburtsdatum   : {p.date_of_birth}")
    lines += [
        "",
        "Bitte teilen Sie mir außerdem mit, an welche Dritte Sie meine Daten weitergegeben",
        "haben (Art. 19 DSGVO).",
        "",
        "Mit freundlichen Grüßen",
        f"{p.first_name} {p.last_name}",
    ]
    return "\n".join(lines)


def _ccpa_body(p: Profile, broker_name: str) -> str:
    return "\n".join(
        [
            "Subject: Deletion Request under CCPA (Cal. Civ. Code § 1798.105)",
            "",
            f"Dear {broker_name},",
            "",
            "I request that you delete all personal information you have collected",
            "about me, as provided by the California Consumer Privacy Act.",
            "",
            f"Name : {p.first_name} {p.last_name}",
            f"Email: {p.email}",
            "",
            "Please confirm completion of this request as required by law.",
            "",
            "Sincerely,",
            f"{p.first_name} {p.last_name}",
        ]
    )


def _generic_body(p: Profile, broker_name: str) -> str:
    return "\n".join(
        [
            f"Subject: Privacy Deletion Request – {p.first_name} {p.last_name}",
            "",
            f"Dear {broker_name},",
            "",
            "I request the deletion of all personal data you hold about me.",
            "This request is based on applicable privacy law (GDPR, CCPA or similar).",
            "",
            f"Name : {p.first_name} {p.last_name}",
            f"Email: {p.email}",
            "",
            "Please confirm once the data has been removed.",
            "",
            "Sincerely,",
            f"{p.first_name} {p.last_name}",
        ]
    )


def build_request_text(p: Profile, broker_name: str, law: LawBasis) -> str:
    if law == LawBasis.gdpr:
        return _gdpr_body(p, broker_name)
    if law == LawBasis.ccpa:
        return _ccpa_body(p, broker_name)
    return _generic_body(p, broker_name)
