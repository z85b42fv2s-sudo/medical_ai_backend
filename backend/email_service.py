import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Optional

from dotenv import load_dotenv

load_dotenv()


SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}


def _is_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def send_email(subject: str, body: str, recipient: str) -> bool:
    if not _is_configured():
        print("[INFO] SMTP non configurato. Email non inviata.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = recipient
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD or "")
            server.send_message(msg)
        return True
    except Exception as exc:
        print(f"[WARN] Invio email fallito: {exc}")
        return False


def send_signup_credentials(
    email: str,
    patient_id: str,
    password: str,
    metadata: Optional[Dict[str, Optional[str]]] = None,
) -> bool:
    subject = "Credenziali di accesso Medical AI"
    meta = metadata or {}
    info_lines = [
        "Ciao,",
        "",
        "la tua registrazione su Medical AI è stata completata.",
        "",
        "Ecco il riepilogo delle informazioni associate al tuo profilo:",
        f"- ID paziente: {patient_id}",
        f"- Email di accesso: {meta.get('email') or email}",
    ]
    if meta.get("nome"):
        info_lines.append(f"- Nome e cognome: {meta['nome']}")
    if meta.get("codice_fiscale"):
        info_lines.append(f"- Codice fiscale: {meta['codice_fiscale']}")
    if meta.get("data_nascita"):
        info_lines.append(f"- Data di nascita: {meta['data_nascita']}")
    if meta.get("telefono"):
        info_lines.append(f"- Telefono: {meta['telefono']}")
    if meta.get("note"):
        info_lines.append(f"- Note: {meta['note']}")
    info_lines.append("- Domanda di sicurezza: " + (meta.get("security_question") or "non specificata"))
    info_lines.extend(
        [
            "",
            f"Password temporanea: {password}",
            "",
            "Accedi al portale e cambia la password dal pannello Impostazioni dopo il primo accesso.",
            "Se non hai richiesto tu questa registrazione contatta immediatamente il nostro supporto.",
            "",
            "Saluti,",
            "Medical AI",
        ]
    )
    body = "\n".join(info_lines)
    return send_email(subject, body, email)


def send_password_change_notification(email: str, patient_id: str) -> bool:
    subject = "Password aggiornata"
    body = (
        "Ciao,\n\n"
        "la password del tuo account Medical AI e' stata aggiornata correttamente.\n"
        "Se non sei stato tu, contatta subito il supporto per bloccare l'accesso.\n\n"
        f"ID paziente: {patient_id}\n"
        "Data e ora: aggiorna dal tuo portale personale.\n\n"
        "Saluti,\n"
        "Medical AI"
    )
    return send_email(subject, body, email)
