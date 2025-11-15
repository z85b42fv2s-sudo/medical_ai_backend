import json
import os
import re
import shutil
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from medical_taxonomy import MEDICAL_SPECIALTIES
from backend.supabase_client import get_supabase
from backend import document_repository, storage_service
from backend.storage_service import StorageServiceError

BASE_DIR = os.getcwd()
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloaded_pdfs")
PATIENTS_DIR = os.path.join(DOWNLOAD_DIR, "patients")
os.makedirs(PATIENTS_DIR, exist_ok=True)

PATIENT_DOCUMENTS_SUBDIR = "documents"

COLLECTION_PATIENTS = "patients"
COLLECTION_PENDING = "pending_patients"
COLLECTION_CREDENTIALS = "patient_credentials"
COLLECTION_SESSIONS = "sessions"
COLLECTION_INVITES = "invites"
COLLECTION_ACCESS_REQUESTS = "access_requests"
COLLECTION_PASSWORD_RESETS = "password_resets"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def load_authorized_patients() -> Dict[str, Dict[str, Any]]:
    resp = get_supabase().table(COLLECTION_PATIENTS).select("*").execute()
    data = resp.data or []
    return {row["patient_id"]: row for row in data if row.get("patient_id")}


def is_patient_authorized(patient_id: str) -> bool:
    if not patient_id:
        return False
    resp = (
        get_supabase()
        .table(COLLECTION_PATIENTS)
        .select("patient_id")
        .eq("patient_id", patient_id)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def authorize_patient(patient_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    metadata = metadata or {}
    codice_fiscale = (metadata.get("codice_fiscale") or "").strip().upper() or None
    record = {
        "patient_id": patient_id,
        "nome": metadata.get("nome") or "",
        "codice_fiscale": codice_fiscale,
        "data_nascita": metadata.get("data_nascita") or None,
        "email": (metadata.get("email") or "").lower() or None,
        "telefono": metadata.get("telefono") or None,
        "note": metadata.get("note") or None,
        "updated_at": _now_iso(),
    }
    if not is_patient_authorized(patient_id):
        record["created_at"] = _now_iso()
    get_supabase().table(COLLECTION_PATIENTS).upsert(record, on_conflict="patient_id").execute()
    get_supabase().table(COLLECTION_PENDING).delete().eq("patient_id", patient_id).execute()


def record_pending_patient(patient_id: str, metadata: Dict[str, Any]) -> None:
    metadata = metadata or {}
    record = {
        "patient_id": patient_id,
        "nome": metadata.get("nome"),
        "codice_fiscale": metadata.get("codice_fiscale"),
        "data_nascita": metadata.get("data_nascita"),
        "email": metadata.get("email"),
        "last_seen": _now_iso(),
        "metadata": metadata,
    }
    get_supabase().table(COLLECTION_PENDING).upsert(record, on_conflict="patient_id").execute()


def get_pending_patients() -> Dict[str, Dict[str, Any]]:
    resp = get_supabase().table(COLLECTION_PENDING).select("*").execute()
    data = resp.data or []
    return {row["patient_id"]: row for row in data if row.get("patient_id")}


def list_authorized_patients() -> List[Dict[str, Any]]:
    return list(load_authorized_patients().values())


def get_patient_profile(patient_id: str) -> Optional[Dict[str, Any]]:
    if not patient_id:
        return None

    meta = load_authorized_patients().get(patient_id, {})
    profile = {
        "patient_id": patient_id,
        "nome": meta.get("nome") or "",
        "codice_fiscale": (meta.get("codice_fiscale") or "").upper(),
        "data_nascita": meta.get("data_nascita") or "",
        "email": (meta.get("email") or "").lower(),
        "documenti": [],
        "aggregati": {},
        "documents_by_specialty": {},
        "ultimo_aggiornamento": meta.get("updated_at") or None,
        "created_at": meta.get("created_at"),
    }

    documents = load_documents_from_supabase(patient_id)
    profile["documenti"] = documents
    profile["aggregati"] = compute_aggregates(documents)
    profile["documents_by_specialty"] = profile["aggregati"].get("per_specialita", {})

    return profile


def list_patient_documents(patient_id: str) -> List[Dict[str, Any]]:
    documents = load_documents_from_supabase(patient_id)
    if documents:
        return documents
    profile = get_patient_profile(patient_id)
    if not profile:
        return []
    return profile.get("documenti", [])


def get_patient_dir(patient_id: str) -> str:
    return os.path.join(PATIENTS_DIR, patient_id)


def ensure_patient_dirs(patient_id: str) -> str:
    base_dir = get_patient_dir(patient_id)
    docs_dir = os.path.join(base_dir, PATIENT_DOCUMENTS_SUBDIR)
    os.makedirs(docs_dir, exist_ok=True)
    return base_dir


def get_patient_documents_dir(patient_id: str, ensure: bool = False) -> str:
    base_dir = get_patient_dir(patient_id)
    documents_dir = os.path.join(base_dir, PATIENT_DOCUMENTS_SUBDIR)
    if ensure:
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(documents_dir, exist_ok=True)
    return documents_dir


def list_patient_document_paths(patient_id: str) -> List[str]:
    documents = load_documents_from_supabase(patient_id)
    entries: List[str] = []
    seen: Set[str] = set()
    if documents:
        for doc in documents:
            stored = doc.get("stored_filename") or doc.get("storage_path")
            if not stored:
                continue
            path = get_patient_document_path(patient_id, stored)
            if path and path not in seen:
                entries.append(path)
                seen.add(path)
    docs_dir = get_patient_documents_dir(patient_id, ensure=False)
    if not os.path.isdir(docs_dir):
        return sorted(entries)
    for filename in os.listdir(docs_dir):
        if not filename.lower().endswith(".pdf"):
            continue
        full_path = os.path.join(docs_dir, filename)
        if os.path.isfile(full_path):
            if full_path not in seen:
                entries.append(full_path)
                seen.add(full_path)
    if entries:
        return sorted(entries)
    fallback: List[str] = []
    for root, _, files in os.walk(docs_dir):
        for filename in files:
            if filename.lower().endswith(".pdf"):
                fallback.append(os.path.join(root, filename))
    return sorted(fallback)


def get_patient_document_path(patient_id: str, stored_filename: str) -> Optional[str]:
    if not stored_filename:
        return None

    rel = stored_filename.replace("\\", "/").strip()
    if not rel:
        return None

    patient_prefix = storage_service.build_storage_path(patient_id, "").rstrip("/")
    storage_path = rel.lstrip("/")
    if "/" not in storage_path:
        storage_path = storage_service.build_storage_path(patient_id, storage_path)
    if patient_prefix and storage_path.startswith(patient_prefix):
        try:
            record = document_repository.get_document_by_path(patient_id, storage_path)
        except Exception as exc:
            print(f"[WARN] Impossibile recuperare il documento {storage_path} da Supabase: {exc}")
            record = None
        if record:
            try:
                return storage_service.download_pdf_to_temp(storage_path)
            except StorageServiceError as exc:
                print(f"[WARN] Download da Supabase fallito per {storage_path}: {exc}")

    docs_dir = get_patient_documents_dir(patient_id, ensure=False)
    if not os.path.isdir(docs_dir):
        return None

    rel_norm = os.path.normpath(rel)
    if os.path.isabs(rel_norm):
        rel_norm = rel_norm.lstrip("\\/")
    if rel_norm.startswith(".."):
        return None
    docs_dir_abs = os.path.abspath(docs_dir)
    full_path = os.path.abspath(os.path.join(docs_dir_abs, rel_norm))
    if not full_path.startswith(docs_dir_abs):
        return None
    if not os.path.isfile(full_path):
        return None
    return full_path


def _hash_password(password: str, salt_hex: Optional[str] = None) -> Dict[str, str]:
    if not password:
        raise ValueError("Password non valida")
    if salt_hex:
        salt = bytes.fromhex(salt_hex)
    else:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return {"salt": salt.hex(), "hash": digest.hex()}


def load_patient_credentials(patient_id: str) -> Optional[Dict[str, Any]]:
    if not patient_id:
        return None
    resp = (
        get_supabase()
        .table(COLLECTION_CREDENTIALS)
        .select("*")
        .eq("patient_id", patient_id)
        .limit(1)
        .execute()
    )
    data = resp.data or []
    return data[0] if data else None


def register_patient_account(
    patient_id: str,
    email: str,
    password: str,
    security_question: Optional[str] = None,
    security_answer: Optional[str] = None,
) -> Dict[str, Any]:
    if not is_patient_authorized(patient_id):
        raise ValueError("Paziente non autorizzato")
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("Email obbligatoria")
    if find_patient_by_email(email) not in (None, patient_id):
        raise ValueError("Email già utilizzata da un altro paziente")

    question = (security_question or "").strip()
    answer = (security_answer or "").strip()
    if not question or not answer:
        raise ValueError("Domanda e risposta di sicurezza obbligatorie")

    if load_patient_credentials(patient_id):
        raise ValueError("Account già registrato")

    pw = _hash_password(password)
    answer_pw = _hash_password(answer)
    credentials = {
        "patient_id": patient_id,
        "email": email,
        "password_salt": pw["salt"],
        "password_hash": pw["hash"],
        "security_question": question,
        "security_answer_salt": answer_pw["salt"],
        "security_answer_hash": answer_pw["hash"],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    get_supabase().table(COLLECTION_CREDENTIALS).insert(credentials).execute()

    get_supabase().table(COLLECTION_PATIENTS).update(
        {"email": email, "updated_at": _now_iso()}
    ).eq("patient_id", patient_id).execute()

    return credentials


def update_patient_password(patient_id: str, password: str) -> Dict[str, Any]:
    if not is_patient_authorized(patient_id):
        raise ValueError("Paziente non autorizzato")
    creds = load_patient_credentials(patient_id)
    if not creds:
        raise ValueError("Account non registrato")
    pw = _hash_password(password)
    updated = {
        "password_salt": pw["salt"],
        "password_hash": pw["hash"],
        "updated_at": _now_iso(),
    }
    get_supabase().table(COLLECTION_CREDENTIALS).update(updated).eq("patient_id", patient_id).execute()
    creds.update(updated)
    return creds


def verify_patient_password(patient_id: str, password: str) -> bool:
    credentials = load_patient_credentials(patient_id)
    if not credentials:
        return False
    salt = credentials.get("password_salt") or credentials.get("salt")
    pw = _hash_password(password, salt_hex=salt)
    return pw["hash"] == credentials.get("password_hash")


def find_patient_by_email(email: str) -> Optional[str]:
    if not email:
        return None
    resp = (
        get_supabase()
        .table(COLLECTION_PATIENTS)
        .select("patient_id")
        .eq("email", email.strip().lower())
        .limit(1)
        .execute()
    )
    data = resp.data or []
    if not data:
        return None
    return data[0].get("patient_id")


def get_security_question(patient_id: str) -> Optional[str]:
    creds = load_patient_credentials(patient_id)
    if not creds:
        return None
    question = creds.get("security_question")
    if question:
        return str(question)
    return None


def verify_security_answer(patient_id: str, answer: str) -> bool:
    creds = load_patient_credentials(patient_id)
    if not creds:
        return False
    salt = creds.get("security_answer_salt")
    expected_hash = creds.get("security_answer_hash")
    if not salt or not expected_hash:
        return False
    try:
        candidate = _hash_password(answer.strip(), salt_hex=salt)
    except ValueError:
        return False
    return candidate["hash"] == expected_hash


def purge_expired_password_resets() -> None:
    resp = get_supabase().table(COLLECTION_PASSWORD_RESETS).select("token,expires_at,consumed_at").execute()
    now = datetime.utcnow()
    for entry in resp.data or []:
        token = entry.get("token")
        if not token:
            continue
        expires_at = _parse_iso(entry.get("expires_at"))
        consumed_at = _parse_iso(entry.get("consumed_at"))
        if consumed_at or (expires_at and expires_at < now):
            get_supabase().table(COLLECTION_PASSWORD_RESETS).delete().eq("token", token).execute()


def create_password_reset_token(patient_id: str, method: str = "email", ttl_minutes: int = 60) -> Dict[str, Any]:
    purge_expired_password_resets()
    token = secrets.token_urlsafe(24)
    entry = {
        "token": token,
        "patient_id": patient_id,
        "method": method,
        "created_at": _now_iso(),
        "expires_at": (datetime.utcnow() + timedelta(minutes=max(ttl_minutes, 5))).isoformat(timespec="seconds"),
    }
    get_supabase().table(COLLECTION_PASSWORD_RESETS).insert(entry).execute()
    return entry


def validate_password_reset_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    purge_expired_password_resets()
    resp = (
        get_supabase()
        .table(COLLECTION_PASSWORD_RESETS)
        .select("*")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    data = resp.data or []
    if not data:
        return None
    entry = data[0]
    if entry.get("consumed_at"):
        return None
    expires_at = _parse_iso(entry.get("expires_at"))
    if expires_at and expires_at < datetime.utcnow():
        get_supabase().table(COLLECTION_PASSWORD_RESETS).delete().eq("token", token).execute()
        return None
    return entry


def consume_password_reset_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    resp = (
        get_supabase()
        .table(COLLECTION_PASSWORD_RESETS)
        .select("*")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    data = resp.data or []
    if not data:
        return None
    entry = data[0]
    get_supabase().table(COLLECTION_PASSWORD_RESETS).delete().eq("token", token).execute()
    return entry


def authenticate_patient(identifier: str, password: str) -> Optional[str]:
    if not identifier or not password:
        return None
    identifier = identifier.strip()
    patient_id = identifier if is_patient_authorized(identifier) else find_patient_by_email(identifier)
    if not patient_id:
        return None
    if verify_patient_password(patient_id, password):
        return patient_id
    return None


SESSION_TTL_HOURS_DEFAULT = 24


def create_session(patient_id: str, ttl_hours: int = SESSION_TTL_HOURS_DEFAULT) -> Dict[str, Any]:
    token = secrets.token_hex(24)
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=max(ttl_hours, 1))
    session = {
        "token": token,
        "patient_id": patient_id,
        "created_at": now.isoformat(timespec="seconds"),
        "last_seen": now.isoformat(timespec="seconds"),
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }
    get_supabase().table(COLLECTION_SESSIONS).insert(session).execute()
    return session


def validate_session(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    resp = (
        get_supabase()
        .table(COLLECTION_SESSIONS)
        .select("*")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    data = resp.data or []
    if not data:
        return None
    session = data[0]
    expires_at = _parse_iso(session.get("expires_at"))
    if expires_at and expires_at < datetime.utcnow():
        get_supabase().table(COLLECTION_SESSIONS).delete().eq("token", token).execute()
        return None
    session["last_seen"] = _now_iso()
    get_supabase().table(COLLECTION_SESSIONS).update({"last_seen": session["last_seen"]}).eq("token", token).execute()
    return session


def revoke_session(token: str) -> None:
    if not token:
        return
    get_supabase().table(COLLECTION_SESSIONS).delete().eq("token", token).execute()


def revoke_sessions_for_patient(patient_id: str) -> None:
    get_supabase().table(COLLECTION_SESSIONS).delete().eq("patient_id", patient_id).execute()


def create_invite(
    patient_id: str,
    created_by: Optional[str] = None,
    expires_hours: int = 48,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    token = secrets.token_urlsafe(16)
    invite = {
        "token": token,
        "patient_id": patient_id,
        "created_by": created_by or None,
        "note": note or None,
        "created_at": _now_iso(),
        "expires_at": (datetime.utcnow() + timedelta(hours=max(expires_hours, 1))).isoformat(timespec="seconds"),
    }
    data = get_supabase().table(COLLECTION_INVITES).insert(invite).execute().data or []
    return data[0] if data else invite


def list_invites(patient_id: Optional[str] = None, include_expired: bool = False) -> List[Dict[str, Any]]:
    query = get_supabase().table(COLLECTION_INVITES).select("*")
    if patient_id:
        query = query.eq("patient_id", patient_id)
    if not include_expired:
        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        query = query.or_(f"expires_at.is.null,expires_at.gt.{now_iso}")
    resp = query.order("created_at", desc=True).execute()
    return resp.data or []


def consume_invite(token: str) -> Optional[Dict[str, Any]]:
    resp = (
        get_supabase()
        .table(COLLECTION_INVITES)
        .select("*")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    data = resp.data or []
    if not data:
        return None
    invite = data[0]
    expires_at = _parse_iso(invite.get("expires_at"))
    if expires_at and expires_at < datetime.utcnow():
        return None
    if invite.get("consumed_at"):
        return invite
    invite["consumed_at"] = _now_iso()
    get_supabase().table(COLLECTION_INVITES).update({"consumed_at": invite["consumed_at"]}).eq("token", token).execute()
    return invite


def add_access_request(
    requester: str,
    patient_id: str,
    message: Optional[str] = None,
    contact: Optional[str] = None,
) -> Dict[str, Any]:
    entry = {
        "patient_id": patient_id,
        "requester": requester,
        "message": message or None,
        "contact": contact or None,
        "status": "pending",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "note": None,
    }
    data = get_supabase().table(COLLECTION_ACCESS_REQUESTS).insert(entry).execute().data or []
    return data[0] if data else entry


def list_access_requests(patient_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
    query = get_supabase().table(COLLECTION_ACCESS_REQUESTS).select("*")
    if patient_id:
        query = query.eq("patient_id", patient_id)
    if status:
        query = query.eq("status", status)
    resp = query.order("created_at", desc=True).execute()
    return resp.data or []


def update_access_request_status(request_id: str, status: str, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    resp = (
        get_supabase()
        .table(COLLECTION_ACCESS_REQUESTS)
        .update({"status": status, "note": note or None, "updated_at": _now_iso()})
        .eq("id", request_id)
        .execute()
    )
    data = resp.data or []
    if not data:
        return None
    return data[0]


def safe_write_json(path: str, obj: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def slugify(value: str) -> str:
    keep = []
    for ch in value.lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in {" ", "-", "_"}:
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "sconosciuto"


def _generate_storage_filename(original_filename: str) -> str:
    name, ext = os.path.splitext(original_filename or "documento.pdf")
    safe_name = slugify(name) or "documento"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    ext = ext if ext else ".pdf"
    return f"{safe_name}_{timestamp}_{suffix}{ext}"


def supabase_row_to_document_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    metadata = row.get("metadata") or {}
    stored_path = row.get("stored_path") or ""
    original_filename = (
        row.get("original_filename")
        or metadata.get("file")
        or os.path.basename(stored_path)
        or ""
    )
    entry: Dict[str, Any] = {
        "id": row.get("id"),
        "file": original_filename,
        "analysis_json": metadata.get("analysis_json") or metadata.get("analysis_json_storage"),
        "pdf_path": metadata.get("local_pdf_path"),
        "stored_filename": stored_path,
        "data_documento": row.get("data_documento") or metadata.get("data_documento") or "",
        "tipologia": row.get("tipologia") or metadata.get("tipologia") or "",
        "specialita": row.get("specialty") or metadata.get("specialita") or "",
        "riassunto": row.get("summary") or metadata.get("riassunto") or "",
        "diagnosi_principali": metadata.get("diagnosi_principali", []),
        "farmaci_prescritti": metadata.get("farmaci_prescritti", []),
        "terapie": metadata.get("terapie", []),
        "esami_laboratorio": metadata.get("esami_laboratorio", []),
        "esami_diagnostica": metadata.get("esami_diagnostica", []),
        "esami_principali": metadata.get("esami_principali", []),
        "anamnesi": metadata.get("anamnesi", []),
        "note_rilevanti": metadata.get("note_rilevanti", []),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if metadata.get("analysis_json_storage"):
        entry["analysis_json_storage"] = metadata.get("analysis_json_storage")
    if metadata.get("analysis_json_local"):
        entry["analysis_json_local"] = metadata.get("analysis_json_local")
    if metadata:
        entry["metadata"] = metadata
    entry.setdefault("storage_path", stored_path)
    return entry


def load_documents_from_supabase(patient_id: str) -> List[Dict[str, Any]]:
    try:
        rows = document_repository.list_documents(patient_id)
    except Exception as exc:
        print(f"[WARN] Impossibile ottenere i documenti da Supabase per {patient_id}: {exc}")
        return []
    return [supabase_row_to_document_entry(row) for row in rows]


def strip_copy_suffix(value: str) -> str:
    match = re.match(r"^(.*)\s+\((\d+)\)$", value)
    return match.group(1) if match else value


def copy_pdf_if_needed(src: str, dest_dir: str) -> Optional[str]:
    if not src or not os.path.exists(src):
        return None
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    if os.path.exists(dest):
        if os.path.getsize(dest) == os.path.getsize(src):
            return dest
        base, ext = os.path.splitext(dest)
        suffix = 1
        new_dest = f"{base}_{suffix}{ext}"
        while os.path.exists(new_dest):
            if os.path.getsize(new_dest) == os.path.getsize(src):
                return new_dest
            suffix += 1
            new_dest = f"{base}_{suffix}{ext}"
        dest = new_dest
    shutil.copy2(src, dest)
    return dest


def unique(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in seq:
        if not item:
            continue
        key = item.strip()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def select_speciality(raw: Optional[str]) -> str:
    if not raw:
        return "altro"
    raw_norm = raw.strip().lower()
    for spec in MEDICAL_SPECIALTIES:
        if raw_norm == spec.lower():
            return spec
    return raw_norm if raw_norm else "altro"


def build_patient_id(patient_info: Dict[str, Any], fallback_name: str) -> str:
    cf = (patient_info.get("codice_fiscale") or "").strip().upper()
    if cf:
        return slugify(cf)
    fallback_name = strip_copy_suffix(fallback_name)
    parts = []
    name = (patient_info.get("nome") or "").strip()
    birth = (patient_info.get("data_nascita") or "").strip()
    if name:
        parts.append(name)
    if birth:
        parts.append(birth)
    if not parts:
        parts.append(fallback_name)
    return slugify("_".join(parts))


def compute_patient_id_for_result(patient_info: Dict[str, Any], fallback_name: str) -> str:
    return build_patient_id(patient_info, fallback_name)


def compute_aggregates(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    agg_anamnesi: List[str] = []
    agg_terapie: List[str] = []
    agg_lab: List[str] = []
    agg_diag: List[str] = []
    per_specialita: Dict[str, List[Dict[str, Any]]] = {
        spec: [] for spec in MEDICAL_SPECIALTIES
    }

    for doc in documents:
        agg_anamnesi.extend(doc.get("anamnesi", []))
        agg_terapie.extend(doc.get("terapie", []))
        agg_lab.extend(doc.get("esami_laboratorio", []))
        agg_lab.extend(doc.get("esami_principali", []))
        agg_diag.extend(doc.get("esami_diagnostica", []))

        spec = select_speciality(doc.get("specialita"))
        stored = doc.get("stored_filename") or os.path.basename(doc.get("pdf_path") or "")
        per_specialita.setdefault(spec, [])
        per_specialita[spec].append(
            {
                "file": doc.get("file"),
                "stored_filename": stored,
                "data_documento": doc.get("data_documento"),
                "tipologia": doc.get("tipologia"),
                "riassunto": doc.get("riassunto"),
            }
        )

    return {
        "anamnesi": unique(agg_anamnesi),
        "terapie": unique(agg_terapie),
        "esami_laboratorio": unique(agg_lab),
        "esami_diagnostica": unique(agg_diag),
        "per_specialita": per_specialita,
    }


def render_profile_txt(profile: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"Profilo paziente: {profile.get('nome') or 'Sconosciuto'}")
    cf = profile.get("codice_fiscale") or "-"
    dob = profile.get("data_nascita") or "-"
    email = profile.get("email") or "-"
    lines.append(f"Codice fiscale: {cf}")
    lines.append(f"Email: {email}")
    lines.append(f"Data di nascita: {dob}")
    lines.append(f"Ultimo aggiornamento: {profile.get('ultimo_aggiornamento', '-')}")
    lines.append("")

    agg = profile.get("aggregati", {})
    lines.append("Anamnesi:")
    lines.extend(f"  - {item}" for item in agg.get("anamnesi", []) or ["Nessuna informazione"])
    lines.append("")
    lines.append("Terapie:")
    lines.extend(f"  - {item}" for item in agg.get("terapie", []) or ["Nessuna informazione"])
    lines.append("")
    lines.append("Esami di laboratorio:")
    lines.extend(f"  - {item}" for item in agg.get("esami_laboratorio", []) or ["Nessuna informazione"])
    lines.append("")
    lines.append("Esami diagnostica per immagini:")
    lines.extend(f"  - {item}" for item in agg.get("esami_diagnostica", []) or ["Nessuna informazione"])
    lines.append("")

    lines.append("Documenti per specialità:")
    per_spec = agg.get("per_specialita", {})
    for spec in MEDICAL_SPECIALTIES:
        docs = per_spec.get(spec) or []
        lines.append(f"- {spec.title()}:")
        if not docs:
            lines.append("    * Nessun documento")
            continue
        for doc in docs:
            lines.append(
                f"    * {doc.get('file')} ({doc.get('data_documento') or 'data n/d'})"
            )
            if doc.get("riassunto"):
                lines.append(f"      Riassunto: {doc['riassunto']}")
    lines.append("")

    lines.append("Elenco documenti:")
    for doc in profile.get("documenti", []):
        lines.append(f"* {doc.get('file')}")
        lines.append(f"  Tipologia: {doc.get('tipologia') or '-'}")
        lines.append(f"  Specialità: {doc.get('specialita') or '-'}")
        lines.append(f"  Data: {doc.get('data_documento') or '-'}")
        if doc.get("riassunto"):
            lines.append(f"  Riassunto: {doc['riassunto']}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def update_patient_profile(
    result: Dict[str, Any],
    analysis_json_path: str,
    forced_patient_id: Optional[str] = None,
    forced_patient_meta: Optional[Dict[str, Any]] = None,
) -> None:
    patient_info = result.get("paziente") or {}
    if forced_patient_meta:
        for key in ("nome", "codice_fiscale", "data_nascita", "email"):
            value = forced_patient_meta.get(key)
            if value and not patient_info.get(key):
                patient_info[key] = value
    fallback_name = os.path.splitext(result.get("file") or "paziente")[0]
    patient_id = forced_patient_id or build_patient_id(patient_info, fallback_name)

    metadata_for_registry = {
        "nome": patient_info.get("nome") or "",
        "codice_fiscale": patient_info.get("codice_fiscale") or "",
        "data_nascita": patient_info.get("data_nascita") or "",
        "email": (patient_info.get("email") or "").lower(),
        "analysis_json": analysis_json_path,
    }

    if not is_patient_authorized(patient_id):
        record_pending_patient(patient_id, metadata_for_registry)
        print(
            f"[WARN] Paziente '{patient_id}' non autorizzato. "
            "Autorizzalo con: python analyze_pdf_ai.py --authorize-patient "
            f"{patient_id}"
        )
        return

    patient_dir = ensure_patient_dirs(patient_id)
    documents_dir = get_patient_documents_dir(patient_id, ensure=True)
    documents_dir_abs = os.path.abspath(documents_dir)

    existing_meta = load_authorized_patients().get(patient_id, {})
    existing_documents = load_documents_from_supabase(patient_id)
    profile = {
        "patient_id": patient_id,
        "nome": patient_info.get("nome") or existing_meta.get("nome") or "",
        "codice_fiscale": (patient_info.get("codice_fiscale") or existing_meta.get("codice_fiscale") or "").upper(),
        "data_nascita": patient_info.get("data_nascita") or existing_meta.get("data_nascita") or "",
        "email": (patient_info.get("email") or existing_meta.get("email") or "").lower(),
        "documenti": existing_documents or [],
        "aggregati": {},
        "documents_by_specialty": {},
        "ultimo_aggiornamento": existing_meta.get("updated_at"),
    }

    # aggiorna info paziente se nuove disponibili
    for key in ("nome", "codice_fiscale", "data_nascita", "email"):
        new_value = patient_info.get(key) or ""
        if new_value:
            if key == "codice_fiscale":
                new_value = new_value.upper()
            if key == "email":
                new_value = new_value.lower()
            profile[key] = new_value

    documento = result.get("documento", {}) or {}
    specialita = select_speciality(documento.get("specialita"))
    spec_slug = slugify(specialita or "altro") or "altro"
    spec_dir = os.path.join(documents_dir, spec_slug)
    os.makedirs(spec_dir, exist_ok=True)

    pdf_source = result.get("path") or ""
    pdf_dest: Optional[str] = None
    if pdf_source:
        src_abs = os.path.abspath(pdf_source)
        spec_abs = os.path.abspath(spec_dir)
        if src_abs.startswith(spec_abs):
            pdf_dest = src_abs
        elif os.path.exists(src_abs):
            base_name = os.path.basename(src_abs)
            name, ext = os.path.splitext(base_name)
            dest_path = os.path.join(spec_dir, base_name)
            counter = 1
            while os.path.exists(dest_path):
                if os.path.getsize(dest_path) == os.path.getsize(src_abs):
                    pdf_dest = dest_path
                    break
                dest_path = os.path.join(spec_dir, f"{name}_{counter}{ext or '.pdf'}")
                counter += 1
            if not pdf_dest:
                try:
                    shutil.copy2(src_abs, dest_path)
                    pdf_dest = dest_path
                except Exception:
                    pdf_dest = None
    current_abs: Optional[str] = None
    if pdf_dest and os.path.exists(pdf_dest):
        current_abs = os.path.abspath(pdf_dest)
    elif pdf_source and os.path.exists(pdf_source):
        current_abs = os.path.abspath(pdf_source)

    if current_abs:
        root_path = os.path.join(documents_dir, os.path.basename(current_abs))
        needs_copy = not os.path.exists(root_path)
        if not needs_copy:
            try:
                needs_copy = os.path.getsize(root_path) != os.path.getsize(current_abs)
            except Exception:
                needs_copy = True
        if needs_copy:
            try:
                shutil.copy2(current_abs, root_path)
            except Exception:
                pass
        result["path"] = current_abs

    stored_filename = ""
    if current_abs and current_abs.startswith(documents_dir_abs):
        stored_filename = os.path.relpath(current_abs, documents_dir_abs).replace("\\", "/")
    elif current_abs:
        stored_filename = os.path.basename(current_abs)

    doc_entry = {
        "file": result.get("file"),
        "analysis_json": analysis_json_path,
        "pdf_path": current_abs or result.get("path"),
        "stored_filename": stored_filename,
        "data_documento": documento.get("data_documento") or "",
        "tipologia": documento.get("tipologia") or "",
        "specialita": specialita,
        "riassunto": result.get("riassunto") or "",
        "diagnosi_principali": result.get("diagnosi_principali", []),
        "farmaci_prescritti": result.get("farmaci_prescritti", []),
        "terapie": result.get("terapie", []),
        "esami_laboratorio": result.get("esami_laboratorio", []),
        "esami_diagnostica": result.get("esami_diagnostica", []),
        "esami_principali": result.get("esami_principali", []),
        "anamnesi": result.get("anamnesi", []),
        "note_rilevanti": result.get("note_rilevanti", []),
    }

    if doc_entry["esami_principali"]:
        if not doc_entry["esami_laboratorio"] and not doc_entry["esami_diagnostica"]:
            doc_entry["esami_laboratorio"] = doc_entry["esami_principali"]

    documents_list = profile.setdefault("documenti", [])
    updated = False
    for idx, existing in enumerate(documents_list):
        if existing.get("file") == doc_entry["file"]:
            documents_list[idx] = doc_entry
            updated = True
            break
    if not updated:
        documents_list.append(doc_entry)

    analysis_storage_path: Optional[str] = None
    if analysis_json_path and os.path.exists(analysis_json_path):
        try:
            analysis_storage_name = _generate_storage_filename(os.path.basename(analysis_json_path))
            analysis_storage_path = storage_service.upload_pdf(
                patient_id,
                analysis_json_path,
                stored_filename=analysis_storage_name,
                folder="analysis",
            )
        except StorageServiceError as exc:
            print(f"[WARN] Impossibile caricare l'analisi JSON su Supabase: {exc}")
        except Exception as exc:
            print(f"[WARN] Errore inatteso durante upload analisi JSON: {exc}")

    if analysis_storage_path:
        doc_entry["analysis_json"] = analysis_storage_path
        doc_entry["analysis_json_storage"] = analysis_storage_path
        if os.path.exists(analysis_json_path):
            try:
                os.remove(analysis_json_path)
            except Exception:
                pass
    else:
        doc_entry["analysis_json"] = analysis_json_path
    if analysis_json_path:
        doc_entry["analysis_json_local"] = analysis_json_path

    storage_path: Optional[str] = None
    document_record: Optional[Dict[str, Any]] = None
    supabase_documents: List[Dict[str, Any]] = []

    if current_abs:
        original_filename = doc_entry.get("file") or os.path.basename(current_abs) or "documento.pdf"
        if not original_filename.lower().endswith(".pdf"):
            original_filename = f"{original_filename}.pdf"
        candidate_name = _generate_storage_filename(original_filename)
        try:
            storage_path = storage_service.upload_pdf(
                patient_id,
                current_abs,
                stored_filename=candidate_name,
                folder="documents",
            )
        except StorageServiceError as exc:
            print(f"[WARN] Impossibile caricare il PDF su Supabase Storage: {exc}")
            storage_path = None

    if storage_path:
        doc_metadata = {
            "analysis_json": analysis_storage_path or analysis_json_path,
            "analysis_json_storage": analysis_storage_path,
            "analysis_json_local": analysis_json_path,
            "diagnosi_principali": doc_entry.get("diagnosi_principali", []),
            "farmaci_prescritti": doc_entry.get("farmaci_prescritti", []),
            "terapie": doc_entry.get("terapie", []),
            "esami_laboratorio": doc_entry.get("esami_laboratorio", []),
            "esami_diagnostica": doc_entry.get("esami_diagnostica", []),
            "esami_principali": doc_entry.get("esami_principali", []),
            "anamnesi": doc_entry.get("anamnesi", []),
            "note_rilevanti": doc_entry.get("note_rilevanti", []),
            "local_pdf_path": current_abs,
            "file": doc_entry.get("file"),
            "tipologia": documento.get("tipologia"),
            "specialita": specialita,
            "data_documento": documento.get("data_documento"),
        }
        try:
            document_record = document_repository.upsert_document(
                patient_id,
                storage_path,
                original_filename=doc_entry.get("file"),
                specialty=specialita,
                tipologia=documento.get("tipologia"),
                data_documento=documento.get("data_documento"),
                summary=doc_entry.get("riassunto"),
                metadata=doc_metadata,
            )
            stored_value = (document_record or {}).get("stored_path") or storage_path
            doc_entry["stored_filename"] = stored_value
            doc_entry["storage_path"] = stored_value
            try:
                supabase_documents = document_repository.list_documents(patient_id)
            except Exception as exc:
                print(f"[WARN] Impossibile recuperare i documenti da Supabase: {exc}")
        except Exception as exc:
            print(f"[WARN] Impossibile aggiornare i metadati documento su Supabase: {exc}")
        try:
            document_repository.save_analysis_result(
                patient_id,
                (document_record or {}).get("id"),
                analysis_storage_path or analysis_json_path,
                result,
            )
        except Exception as exc:
            print(f"[WARN] Impossibile salvare il risultato di analisi su Supabase: {exc}")
    elif current_abs:
        doc_entry["storage_path"] = doc_entry.get("stored_filename")

    if supabase_documents:
        profile["documenti"] = [supabase_row_to_document_entry(row) for row in supabase_documents]
    else:
        if storage_path and storage_path != doc_entry.get("stored_filename"):
            doc_entry["stored_filename"] = storage_path
            doc_entry["storage_path"] = storage_path

    documents_for_profile = profile.get("documenti", [])
    profile["aggregati"] = compute_aggregates(documents_for_profile)
    profile["documents_by_specialty"] = profile["aggregati"].get("per_specialita", {})
    profile["ultimo_aggiornamento"] = datetime.now().isoformat(timespec="seconds")

    try:
        get_supabase().table(COLLECTION_PATIENTS).update({"updated_at": _now_iso()}).eq("patient_id", patient_id).execute()
    except Exception:
        pass


__all__ = [
    "update_patient_profile",
    "PATIENTS_DIR",
    "MEDICAL_SPECIALTIES",
    "is_patient_authorized",
    "authorize_patient",
    "list_authorized_patients",
    "get_patient_profile",
    "list_patient_documents",
    "get_pending_patients",
    "record_pending_patient",
    "load_authorized_patients",
    "load_pending_patients",
    "get_patient_dir",
    "get_patient_documents_dir",
    "list_patient_document_paths",
    "get_patient_document_path",
    "register_patient_account",
    "update_patient_password",
    "load_patient_credentials",
    "find_patient_by_email",
    "verify_patient_password",
    "get_security_question",
    "verify_security_answer",
    "authenticate_patient",
    "create_session",
    "validate_session",
    "revoke_session",
    "revoke_sessions_for_patient",
    "create_invite",
    "list_invites",
    "consume_invite",
    "add_access_request",
    "list_access_requests",
    "update_access_request_status",
    "compute_patient_id_for_result",
    "create_password_reset_token",
    "validate_password_reset_token",
    "consume_password_reset_token",
]
