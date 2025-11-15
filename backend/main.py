# -*- coding: utf-8 -*-
"""FastAPI backend per Medical AI con gestione profili paziente."""
import os
import json
import glob
import time
import shutil
import secrets
import tempfile
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Literal, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from . import document_repository, storage_service
from .storage_service import StorageServiceError
from .email_service import send_signup_credentials, send_password_change_notification
from pydantic import BaseModel, EmailStr, Field

from download_pdfs import build_chrome_driver, is_url, scan_local_folder, scan_page, remove_duplicate_pdfs
from analyze_pdf_ai import analyze_pdfs, load_all_results, qa_on_results, safe_write_json, RESULTS_DIR, remove_duplicate_results
from patient_profiles import (
    add_access_request,
    authenticate_patient,
    authorize_patient,
    consume_invite,
    create_invite,
    create_session,
    create_password_reset_token,
    get_patient_documents_dir,
    get_patient_document_path,
    get_patient_profile,
    get_pending_patients,
    get_security_question,
    is_patient_authorized,
    list_access_requests,
    list_authorized_patients,
    list_invites,
    list_patient_documents,
    list_patient_document_paths,
    load_patient_credentials,
    find_patient_by_email,
    register_patient_account,
    revoke_session,
    consume_password_reset_token,
    update_access_request_status,
    update_patient_password,
    update_patient_profile,
    validate_password_reset_token,
    validate_session,
    verify_patient_password,
    verify_security_answer,
)

load_dotenv()

PENDING_DOWNLOADS: Dict[str, Dict[str, Any]] = {}

app = FastAPI(title="Medical AI Backend", version="2.0")


def _remove_file_safely(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _remove_files_safely(paths: List[str]) -> None:
    for path in paths:
        _remove_file_safely(path)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "null",
        "http://127.0.0.1",
        "http://127.0.0.1:5500",
        "http://localhost",
        "http://localhost:5500",
    ],
    allow_origin_regex=r"null|https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PatientMetadata(BaseModel):
    nome: Optional[str] = None
    codice_fiscale: Optional[str] = None
    data_nascita: Optional[str] = None
    email: Optional[EmailStr] = None


class RegisterRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    security_question: str = Field(..., min_length=8, max_length=240)
    security_answer: str = Field(..., min_length=1, max_length=240)


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    token: str
    patient_id: str
    expires_at: str


class AskRequest(BaseModel):
    question: str = Field(..., min_length=4)
    mode: Literal["cached", "direct"] = "cached"


class AnalyzeOptions(BaseModel):
    overwrite: bool = True
    ocr: bool = True
    ocr_lang: str = "ita+eng"
    ocr_psm: str = "6"
    ocr_zoom: float = 3.0
    dump_text: bool = False
    vision_only: bool = False
    auto_authorize: bool = False
    category_filter: Optional[str] = None


class InviteRequest(BaseModel):
    expires_hours: int = Field(48, ge=1, le=24 * 14)
    note: Optional[str] = None
    created_by: Optional[str] = None


class InviteClaim(BaseModel):
    token: str


class AccessRequestIn(BaseModel):
    patient_id: str
    requester: str
    message: Optional[str] = None
    contact: Optional[str] = None


class AccessRequestStatus(BaseModel):
    status: str
    note: Optional[str] = None


class SignupRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    nome: Optional[str] = None
    codice_fiscale: Optional[str] = None
    data_nascita: Optional[str] = None
    email: EmailStr
    telefono: Optional[str] = None
    note: Optional[str] = None
    security_question: str = Field(..., min_length=8, max_length=240)
    security_answer: str = Field(..., min_length=1, max_length=240)


class SignupResponse(BaseModel):
    status: str
    patient_id: str
    password: Optional[str] = None
    email_sent: bool = False
    message: Optional[str] = None


class PasswordResetInitRequest(BaseModel):
    identifier: str = Field(..., min_length=1)


class PasswordResetInitResponse(BaseModel):
    status: str
    message: str
    question: Optional[str] = None
    token: Optional[str] = None


class PasswordResetCompleteRequest(BaseModel):
    token: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1, max_length=240)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


def sanitize_filename(name: str) -> str:
    name = (name or "document.pdf").strip()
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    safe_chars = []
    for ch in name:
        if ch.isalnum() or ch in {".", "_", "-"}:
            safe_chars.append(ch)
        else:
            safe_chars.append("-")
    sanitized = "".join(safe_chars).strip("-._")
    return sanitized or "document.pdf"


def _build_storage_filename(original: str) -> str:
    sanitized = sanitize_filename(original)
    base, ext = os.path.splitext(sanitized)
    ext = ext or ".pdf"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = secrets.token_hex(3)
    return f"{base}_{timestamp}_{suffix}{ext}"


def _cleanup_pending_download(token: str) -> None:
    pending = PENDING_DOWNLOADS.pop(token, None)
    if not pending:
        return
    driver = pending.get("driver")
    if driver:
        try:
            driver.quit()
        except Exception:
            pass


def _copy_downloads_to_patient(patient_id: str, download_dir: str, filenames: List[str]) -> Dict[str, List[str]]:
    ensure_authorized_patient(patient_id)
    dest_dir = get_patient_documents_dir(patient_id, ensure=True)
    copied: List[str] = []
    skipped: List[str] = []

    for name in filenames:
        if not name.lower().endswith(".pdf"):
            continue
        src_path = os.path.join(download_dir, name)
        if not os.path.exists(src_path):
            continue

        sanitized_name = sanitize_filename(name)
        base, ext = os.path.splitext(sanitized_name)
        ext = ext or ".pdf"
        dest_path = os.path.join(dest_dir, sanitized_name)

        counter = 1
        while os.path.exists(dest_path):
            if os.path.getsize(dest_path) == os.path.getsize(src_path):
                skipped.append(os.path.basename(dest_path))
                dest_path = ""
                break
            dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
            counter += 1

        if not dest_path:
            continue

        try:
            shutil.copy2(src_path, dest_path)
            copied_name = os.path.basename(dest_path)
            copied.append(copied_name)

            stored_path = None
            try:
                storage_name = _build_storage_filename(copied_name)
                stored_path = storage_service.upload_pdf(
                    patient_id,
                    dest_path,
                    stored_filename=storage_name,
                    folder="documents",
                )
            except StorageServiceError as exc:
                print(f"[WARN] Upload su Supabase fallito per '{dest_path}': {exc}")
            except Exception as exc:
                print(f"[WARN] Errore inatteso durante upload '{dest_path}': {exc}")

            if stored_path:
                metadata = {
                    "source": "download",
                    "local_pdf_path": dest_path,
                    "file": copied_name,
                    "uploaded_at": datetime.utcnow().isoformat(timespec="seconds"),
                }
                try:
                    document_repository.upsert_document(
                        patient_id,
                        stored_path,
                        original_filename=copied_name,
                        metadata=metadata,
                    )
                except Exception as exc:
                    print(f"[WARN] Metadati documento non salvati su Supabase per '{stored_path}': {exc}")
        except Exception:
            skipped.append(os.path.basename(src_path))

    if copied:
        removed = remove_duplicate_pdfs(dest_dir)
        if removed:
            print(f"[INFO] Duplicati rimossi nella cartella paziente '{patient_id}': {removed}")

    return {"copied": copied, "skipped": skipped}


def ensure_authorized_patient(patient_id: str) -> None:
    if not is_patient_authorized(patient_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paziente non trovato o non autorizzato")


def get_session_from_header(authorization: Optional[str] = Header(None)) -> Dict[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token assente o non valido")
    token = authorization.split(" ", 1)[1].strip()
    session = validate_session(token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessione non valida o scaduta")
    session["token"] = token
    return session


def require_patient_session(patient_id: str, session: Dict[str, str] = Depends(get_session_from_header)) -> Dict[str, str]:
    if session.get("patient_id") != patient_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token non autorizzato per questo paziente")
    return session


def get_patient_results_dir(patient_id: str) -> str:
    path = os.path.join(RESULTS_DIR, patient_id)
    os.makedirs(path, exist_ok=True)
    return path


def _resolve_patient_identifier(identifier: str) -> Optional[str]:
    ident = (identifier or "").strip()
    if not ident:
        return None
    if is_patient_authorized(ident):
        return ident
    return find_patient_by_email(ident)


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "Backend Medical AI attivo"}


@app.post("/auth/register")
def auth_register(payload: RegisterRequest) -> Dict[str, str]:
    patient_id = payload.patient_id.strip()
    ensure_authorized_patient(patient_id)
    try:
        creds = register_patient_account(
            patient_id,
            payload.email,
            payload.password,
            payload.security_question,
            payload.security_answer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"status": "ok", "patient_id": patient_id, "email": creds.get("email", payload.email)}


@app.post("/auth/login", response_model=TokenResponse)
def auth_login(payload: LoginRequest) -> TokenResponse:
    patient_id = authenticate_patient(payload.identifier, payload.password)
    if not patient_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")
    session = create_session(patient_id)
    return TokenResponse(token=session["token"], patient_id=patient_id, expires_at=session["expires_at"])


@app.post("/auth/logout")
def auth_logout(session: Dict[str, str] = Depends(get_session_from_header)) -> Dict[str, str]:
    token = session.get("token")
    revoke_session(token)
    if token:
        _cleanup_pending_download(token)
    return {"status": "ok"}


@app.post("/auth/password-reset/init", response_model=PasswordResetInitResponse)
def password_reset_init(payload: PasswordResetInitRequest) -> PasswordResetInitResponse:
    generic_message = "Se l'account esiste, riceverai un'email con le istruzioni per il reset."
    patient_id = _resolve_patient_identifier(payload.identifier)
    if not patient_id:
        return PasswordResetInitResponse(status="ok", message=generic_message)

    question = get_security_question(patient_id)
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Domanda di sicurezza non configurata per questo account. Contatta l'assistenza.",
        )

    reset_entry = create_password_reset_token(patient_id, method="email")
    print(f"[INFO] Password reset richiesto per {patient_id}. Token: {reset_entry['token']}")
    return PasswordResetInitResponse(
        status="ok",
        message=generic_message,
        question=question,
        token=reset_entry["token"],
    )


@app.post("/auth/password-reset/complete")
def password_reset_complete(payload: PasswordResetCompleteRequest) -> Dict[str, str]:
    entry = validate_password_reset_token(payload.token)
    if not entry:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token non valido o scaduto")
    patient_id = entry.get("patient_id")
    if not patient_id or not is_patient_authorized(patient_id):
        consume_password_reset_token(payload.token)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token non valido")

    if not verify_security_answer(patient_id, payload.answer):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Risposta di sicurezza non corretta")

    try:
        update_patient_password(patient_id, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    consume_password_reset_token(payload.token)
    try:
        creds = load_patient_credentials(patient_id) or {}
        email = creds.get("email")
        if email:
            send_password_change_notification(str(email), patient_id)
    except Exception as exc:
        print(f"[WARN] Email reset password non inviata per {patient_id}: {exc}")
    return {"status": "ok", "message": "Password aggiornata con successo"}


@app.post("/auth/password/change")
def password_change(
    payload: PasswordChangeRequest,
    session: Dict[str, str] = Depends(get_session_from_header),
) -> Dict[str, str]:
    patient_id = session["patient_id"]
    if not verify_patient_password(patient_id, payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password attuale non corretta")
    try:
        update_patient_password(patient_id, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    try:
        creds = load_patient_credentials(patient_id) or {}
        email = creds.get("email")
        if email:
            send_password_change_notification(str(email), patient_id)
    except Exception as exc:
        print(f"[WARN] Email cambio password non inviata per {patient_id}: {exc}")
    return {"status": "ok", "message": "Password aggiornata con successo"}


@app.get("/auth/me")
def auth_me(session: Dict[str, str] = Depends(get_session_from_header)) -> Dict[str, Optional[Dict[str, Any]]]:
    patient_id = session["patient_id"]
    profile = get_patient_profile(patient_id)
    creds = load_patient_credentials(patient_id)
    return {
        "status": "ok",
        "patient_id": patient_id,
        "profile": profile,
        "email": creds.get("email") if creds else None,
    }


@app.get("/patients")
def patients_list(include_profile: bool = Query(False)) -> Dict[str, Any]:
    patients = list_authorized_patients()
    response: List[Dict[str, Any]] = []
    for meta in patients:
        entry = meta.copy()
        if include_profile:
            entry["profile"] = get_patient_profile(meta["patient_id"])
        response.append(entry)
    return {"status": "ok", "count": len(response), "patients": response}


@app.get("/patients/pending")
def patients_pending() -> Dict[str, Any]:
    pending = get_pending_patients()
    return {"status": "ok", "count": len(pending), "patients": list(pending.values())}


@app.post("/patients/{patient_id}/authorize")
def patients_authorize(patient_id: str, body: PatientMetadata = Body(default_factory=PatientMetadata)) -> Dict[str, str]:
    authorize_patient(
        patient_id,
        {
            "nome": body.nome,
            "codice_fiscale": body.codice_fiscale,
            "data_nascita": body.data_nascita,
            "email": str(body.email) if body.email else None,
        },
    )
    return {"status": "ok", "patient_id": patient_id}


@app.get("/patients/{patient_id}")
def patients_profile(patient_id: str, session: Dict[str, str] = Depends(require_patient_session)) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    profile = get_patient_profile(patient_id)
    if not profile:
        # costruisci un profilo minimale partendo dal registro autorizzati
        meta = next((entry for entry in list_authorized_patients() if entry.get("patient_id") == patient_id), {})
        profile = {
            "patient_id": patient_id,
            "nome": meta.get("nome") or "",
            "codice_fiscale": meta.get("codice_fiscale") or "",
            "data_nascita": meta.get("data_nascita") or "",
            "email": meta.get("email") or "",
            "documenti": [],
            "aggregati": {},
            "ultimo_aggiornamento": None,
        }
    return {"status": "ok", "profile": profile}


@app.get("/patients/{patient_id}/documents")
def patients_documents(patient_id: str, session: Dict[str, str] = Depends(require_patient_session)) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    profile = get_patient_profile(patient_id) or {}
    docs = profile.get("documenti") or []
    grouped = profile.get("documents_by_specialty") or profile.get("aggregati", {}).get("per_specialita") or {}
    return {
        "status": "ok",
        "count": len(docs),
        "documents": docs,
        "documents_by_specialty": grouped,
    }


@app.get("/patients/{patient_id}/documents/download")
def patients_download_document(
    patient_id: str,
    filename: str = Query(..., description="Nome del file memorizzato (stored_filename)"),
    session: Dict[str, str] = Depends(require_patient_session),
):
    ensure_authorized_patient(patient_id)
    normalized = filename.replace("\\", "/")
    documents = list_patient_documents(patient_id)
    display_name = os.path.basename(normalized)
    for doc in documents:
        stored = (doc.get("stored_filename") or "").replace("\\", "/")
        storage_path = (doc.get("storage_path") or stored).replace("\\", "/")
        if normalized in {stored, storage_path}:
            display_name = doc.get("file") or display_name
            break

    path = get_patient_document_path(patient_id, filename)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento non trovato")
    abs_path = os.path.abspath(path)
    background = None
    temp_root = os.path.abspath(tempfile.gettempdir())
    try:
        if os.path.commonpath([abs_path, temp_root]) == temp_root:
            background = BackgroundTask(_remove_file_safely, abs_path)
    except ValueError:
        pass
    download_name = display_name or os.path.basename(abs_path)
    return FileResponse(abs_path, media_type="application/pdf", filename=download_name, background=background)


@app.get("/patients/{patient_id}/documents/download-all")
def patients_download_all_documents(
    patient_id: str,
    session: Dict[str, str] = Depends(require_patient_session),
):
    ensure_authorized_patient(patient_id)
    paths = list_patient_document_paths(patient_id)
    if not paths:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nessun documento disponibile per il download")

    try:
        fd, archive_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Archivio temporaneo non disponibile") from exc

    temp_root = os.path.abspath(tempfile.gettempdir())
    temp_files_to_cleanup: List[str] = []
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            seen_names: Set[str] = set()
            for idx, path in enumerate(paths, start=1):
                if not os.path.isfile(path):
                    continue
                arcname = os.path.basename(path) or f"documento_{idx}.pdf"
                if arcname in seen_names:
                    base, ext = os.path.splitext(arcname)
                    arcname = f"{base}_{idx}{ext or '.pdf'}"
                seen_names.add(arcname)
                bundle.write(path, arcname=arcname)
                abs_path = os.path.abspath(path)
                try:
                    if os.path.commonpath([abs_path, temp_root]) == temp_root:
                        temp_files_to_cleanup.append(abs_path)
                except ValueError:
                    pass
    except Exception:
        _remove_file_safely(archive_path)
        for temp_path in temp_files_to_cleanup:
            _remove_file_safely(temp_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Impossibile preparare l'archivio dei documenti")

    download_name = f"{patient_id}_documenti.zip".replace(" ", "_")
    background = BackgroundTask(_remove_files_safely, [archive_path, *temp_files_to_cleanup])
    return FileResponse(archive_path, media_type="application/zip", filename=download_name, background=background)


@app.post("/patients/{patient_id}/documents/upload")
async def upload_patient_document(
    patient_id: str,
    file: UploadFile = File(...),
    session: Dict[str, str] = Depends(require_patient_session),
) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    docs_dir = get_patient_documents_dir(patient_id, ensure=True)
    filename = sanitize_filename(file.filename or "document.pdf")
    base, ext = os.path.splitext(filename)
    dest_path = os.path.join(docs_dir, filename)
    counter = 1
    while os.path.exists(dest_path):
        suffix = f"_{counter}"
        dest_path = os.path.join(docs_dir, f"{base}{suffix}{ext or '.pdf'}")
        counter += 1
    file.file.seek(0)
    with open(dest_path, "wb") as out_file:
        shutil.copyfileobj(file.file, out_file)
    await file.close()
    size = os.path.getsize(dest_path)

    storage_path = None
    document_record: Optional[Dict[str, Any]] = None
    try:
        storage_name = _build_storage_filename(os.path.basename(dest_path))
        storage_path = storage_service.upload_pdf(
            patient_id,
            dest_path,
            stored_filename=storage_name,
            folder="documents",
        )
    except StorageServiceError as exc:
        print(f"[WARN] Upload su Supabase fallito per '{dest_path}': {exc}")
    except Exception as exc:
        print(f"[WARN] Errore inatteso durante upload '{dest_path}': {exc}")

    if storage_path:
        metadata = {
            "source": "upload",
            "local_pdf_path": dest_path,
            "file": os.path.basename(dest_path),
            "uploaded_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        try:
            document_record = document_repository.upsert_document(
                patient_id,
                storage_path,
                original_filename=os.path.basename(dest_path),
                metadata=metadata,
            )
        except Exception as exc:
            print(f"[WARN] Metadati documento non salvati su Supabase per '{storage_path}': {exc}")

    stored_name = storage_path or os.path.basename(dest_path)
    return {
        "status": "ok",
        "filename": os.path.basename(dest_path),
        "size": size,
        "path": dest_path,
        "stored_filename": stored_name,
        "document": document_record,
    }


@app.post("/patients/{patient_id}/analyze")
def analyze_patient(
    patient_id: str,
    options: AnalyzeOptions = Body(default_factory=AnalyzeOptions),
    session: Dict[str, str] = Depends(require_patient_session),
) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    pdf_paths = list_patient_document_paths(patient_id)
    if not pdf_paths:
        return {"status": "ok", "count": 0, "message": "Nessun documento da analizzare"}

    temp_root = os.path.abspath(tempfile.gettempdir())
    temp_paths_to_cleanup = set()
    for path in pdf_paths:
        try:
            abs_path = os.path.abspath(path)
            if os.path.commonpath([abs_path, temp_root]) == temp_root:
                temp_paths_to_cleanup.add(abs_path)
        except ValueError:
            continue

    results_dir = get_patient_results_dir(patient_id)
    raw_text_dir = os.path.join(results_dir, "_raw_text")

    n_saved = 0
    n_skipped = 0
    outputs: List[Dict[str, Any]] = []
    use_ocr = options.ocr and not options.vision_only
    vision_fallback = not options.vision_only

    pending: List[Tuple[str, str, str]] = []
    for fpath in pdf_paths:
        base_name = os.path.splitext(os.path.basename(fpath))[0]
        out_json = os.path.join(results_dir, f"{base_name}.json")
        if not options.overwrite and os.path.exists(out_json):
            n_skipped += 1
            outputs.append({"status": "skipped", "file": os.path.basename(fpath), "reason": "exists", "output": out_json})
            continue
        pending.append((fpath, out_json, base_name))

    batch_size = 2

    authorized_meta: Dict[str, Any] = next(
        (entry for entry in list_authorized_patients() if entry.get("patient_id") == patient_id),
        {},
    )

    def run_analysis(path: str) -> Dict[str, Any]:
        return analyze_pdfs(
            "gpt-5",
            path,
            use_ocr=use_ocr,
            ocr_lang=options.ocr_lang,
            ocr_zoom=options.ocr_zoom,
            ocr_psm=options.ocr_psm,
            dump_text=options.dump_text,
            raw_text_dir=raw_text_dir,
            vision_only=options.vision_only,
            vision_fallback=vision_fallback,
        )

    for idx in range(0, len(pending), batch_size):
        batch = pending[idx: idx + batch_size]
        if not batch:
            continue
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            future_map = {
                executor.submit(run_analysis, fpath): (fpath, out_json, base_name)
                for fpath, out_json, base_name in batch
            }
            for future in as_completed(future_map):
                fpath, out_json, base_name = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    outputs.append({"status": "error", "file": f"{base_name}.pdf", "error": str(exc)})
                    continue

                safe_write_json(out_json, result)
                update_patient_profile(
                    result,
                    out_json,
                    forced_patient_id=patient_id,
                    forced_patient_meta=authorized_meta,
                )
                outputs.append(
                    {
                        "status": "saved",
                        "file": f"{base_name}.pdf",
                        "output": out_json,
                        "mode": "vision" if options.vision_only else "standard",
                    }
                )
                n_saved += 1

    if pending:
        removed_json = remove_duplicate_results(results_dir)
        if removed_json:
            print(f"[INFO] Risultati duplicati rimossi per paziente '{patient_id}': {removed_json}")

    for tmp_path in temp_paths_to_cleanup:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    return {
        "status": "ok",
        "count": n_saved,
        "skipped": n_skipped,
        "results": outputs,
    }


@app.post("/patients/{patient_id}/ask")
def ask_patient_ai(
    patient_id: str,
    body: AskRequest,
    session: Dict[str, str] = Depends(require_patient_session),
) -> Dict[str, str]:
    ensure_authorized_patient(patient_id)
    mode = (body.mode or "cached").lower()
    if mode not in {"cached", "direct"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Modalita' richiesta non supportata")
    if mode == "direct":
        try:
            analyze_patient(
                patient_id,
                AnalyzeOptions(
                    overwrite=True,
                    ocr=False,
                    vision_only=True,
                ),
                session=session,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    try:
        answer = qa_on_results("gpt-5", body.question, patient_id=patient_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return {"status": "success", "mode": mode, "question": body.question, "answer": answer}


@app.get("/patients/{patient_id}/analysis-results")
def patient_analysis_results(
    patient_id: str,
    file: Optional[str] = Query(None, description="Nome del file JSON (senza estensione)", alias="file"),
    session: Dict[str, str] = Depends(require_patient_session),
) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    results_dir = get_patient_results_dir(patient_id)
    targets: List[str]
    if file:
        clean = os.path.basename(file)
        if not clean.lower().endswith(".json"):
            clean = f"{clean}.json"
        targets = [os.path.join(results_dir, clean)]
    else:
        targets = glob.glob(os.path.join(results_dir, "*.json"))

    data = []
    for path in sorted(set(targets)):
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            data.append({"file": os.path.basename(path), "data": json.load(fh)})
    return {"status": "ok", "count": len(data), "results": data}


@app.post("/patients/{patient_id}/invite")
def patients_create_invite_endpoint(
    patient_id: str,
    req: InviteRequest,
    session: Dict[str, str] = Depends(require_patient_session),
) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    invite = create_invite(
        patient_id,
        created_by=req.created_by,
        expires_hours=req.expires_hours,
        note=req.note,
    )
    return {"status": "ok", "invite": invite}


@app.get("/patients/{patient_id}/invites")
def patients_list_invites_endpoint(
    patient_id: str,
    include_expired: bool = Query(False),
    session: Dict[str, str] = Depends(require_patient_session),
) -> Dict[str, Any]:
    ensure_authorized_patient(patient_id)
    invites = list_invites(patient_id=patient_id, include_expired=include_expired)
    return {"status": "ok", "count": len(invites), "invites": invites}


@app.post("/access/request")
def access_request(req: AccessRequestIn) -> Dict[str, Any]:
    entry = add_access_request(
        requester=req.requester,
        patient_id=req.patient_id,
        message=req.message,
        contact=req.contact,
    )
    return {"status": "ok", "request": entry}


@app.get("/access/requests")
def access_list_requests_endpoint(
    patient_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    session: Optional[Dict[str, str]] = None
    if authorization:
        session = get_session_from_header(authorization)
    if patient_id:
        if not session or session.get("patient_id") != patient_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token non valido per questo paziente")
    entries = list_access_requests(patient_id=patient_id, status=status_filter)
    return {"status": "ok", "count": len(entries), "requests": entries}


@app.post("/access/requests/{request_id}/status")
def access_update_request_endpoint(
    request_id: str,
    update: AccessRequestStatus,
    session: Dict[str, str] = Depends(get_session_from_header),
) -> Dict[str, Any]:
    patient_id = session.get("patient_id")
    if not patient_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token non valido")
    entry = update_access_request_status(request_id, update.status, update.note)
    if not entry or entry.get("patient_id") != patient_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Richiesta non trovata")
    return {"status": "ok", "request": entry}


@app.post("/access/claim")
def access_claim_invite(body: InviteClaim) -> Dict[str, Any]:
    invite = consume_invite(body.token)
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invito non trovato")
    return {"status": "ok", "invite": invite}


@app.get("/analysis-results")
def analysis_results(file: Optional[str] = Query(None, description="Nome file JSON (senza estensione)")) -> Dict[str, Any]:
    records = load_all_results()
    if file:
        filtered = [r for r in records if os.path.splitext(r.get("file", ""))[0] == file]
        records = filtered
    return {"status": "ok", "count": len(records), "results": records}


@app.get("/query-history")
def query_history() -> Dict[str, Any]:
    history_path = os.path.join(RESULTS_DIR, "query_history.json")
    if not os.path.exists(history_path):
        return {"status": "ok", "count": 0, "entries": []}
    try:
        with open(history_path, "r", encoding="utf-8") as fh:
            entries = json.load(fh)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return {"status": "ok", "count": len(entries), "entries": entries}


@app.get("/download")
def download_route(
    source: str = Query(..., description="Percorso locale o URL da cui scaricare PDF"),
    patient_id: Optional[str] = Query(None, description="ID paziente a cui associare i PDF"),
    session: Dict[str, str] = Depends(get_session_from_header),
) -> Dict[str, Any]:
    try:
        start = time.time()
        if not source:
            return {"status": "error", "message": "Nessun percorso o URL fornito"}

        download_dir = os.path.join(os.getcwd(), "downloaded_pdfs")
        os.makedirs(download_dir, exist_ok=True)
        before_files = {f for f in os.listdir(download_dir) if f.lower().endswith(".pdf")}

        session_patient = session.get("patient_id")
        target_patient = patient_id or session_patient
        if patient_id and session_patient and patient_id != session_patient:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Non autorizzato per questo paziente")

        copy_report: Dict[str, List[str]] = {"copied": [], "skipped": []}

        token = session.get("token")
        if token:
            _cleanup_pending_download(token)
        if is_url(source):
            driver, wait = build_chrome_driver()
            try:
                driver.get(source)
            except Exception:
                driver.quit()
                raise
            if token:
                PENDING_DOWNLOADS[token] = {
                    "driver": driver,
                    "wait": wait,
                    "source": source,
                    "start": start,
                    "download_dir": download_dir,
                    "before_files": list(before_files),
                    "patient_id": target_patient,
                }
            message = (
                "Completa l'accesso SPID nella finestra aperta, raggiungi l'elenco dei documenti (senza aprire i PDF) e poi premi \"Continua download\"."
            )
            return {
                "status": "waiting_for_login",
                "message": message,
                "pending": True,
                "ticket": token,
            }

        folder = os.path.abspath(source)
        result = scan_local_folder(folder, download_dir)
        remove_duplicate_pdfs(download_dir)
        after_files = {f for f in os.listdir(download_dir) if f.lower().endswith(".pdf")}
        new_files = sorted(after_files - before_files)
        if target_patient:
            files_to_copy = new_files or sorted(after_files)
            copy_report = _copy_downloads_to_patient(target_patient, download_dir, files_to_copy)
        elapsed = time.time() - start
        return {
            "status": "ok",
            "result": result,
            "elapsed_sec": round(elapsed, 1),
            "copied_files": copy_report.get("copied"),
            "skipped_files": copy_report.get("skipped"),
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.post("/download/continue")
def download_continue(
    session: Dict[str, str] = Depends(get_session_from_header),
) -> Dict[str, Any]:
    token = session.get("token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessione non valida")
    pending = PENDING_DOWNLOADS.pop(token, None)
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nessun download in attesa")

    driver = pending.get("driver")
    wait = pending.get("wait")
    source = pending.get("source")
    start = pending.get("start") or time.time()
    download_dir = pending.get("download_dir") or os.path.join(os.getcwd(), "downloaded_pdfs")
    before_files = set(pending.get("before_files") or [])
    target_patient = pending.get("patient_id")

    if target_patient:
        session_patient = session.get("patient_id")
        if session_patient and session_patient != target_patient:
            _cleanup_pending_download(token)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sessione non autorizzata")

    if not driver or not wait or not source:
        _cleanup_pending_download(token)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Stato download non valido")

    copy_report: Dict[str, List[str]] = {"copied": [], "skipped": []}

    try:
        result = scan_page(driver, wait, source, max_depth=2, open_url=False)
        removed = remove_duplicate_pdfs(download_dir)
        after_files = {f for f in os.listdir(download_dir) if f.lower().endswith(".pdf")}
        new_files = sorted(after_files - before_files)
        if target_patient:
            files_to_copy = new_files or sorted(after_files)
            copy_report = _copy_downloads_to_patient(target_patient, download_dir, files_to_copy)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    elapsed = time.time() - start
    return {
        "status": "ok",
        "result": result,
        "elapsed_sec": round(elapsed, 1),
        "copied_files": copy_report.get("copied"),
        "skipped_files": copy_report.get("skipped"),
    }


@app.post("/download/upload")
async def upload_download_pdfs(
    files: List[UploadFile] = File(...),
    session: Dict[str, str] = Depends(get_session_from_header),
) -> Dict[str, Any]:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nessun file caricato")

    download_dir = os.path.join(os.getcwd(), "downloaded_pdfs")
    os.makedirs(download_dir, exist_ok=True)

    saved: List[Dict[str, Any]] = []
    saved_names: List[str] = []
    for upload in files:
        filename = sanitize_filename(upload.filename or "document.pdf")
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File non PDF: {upload.filename}")

        base, ext = os.path.splitext(filename)
        dest = os.path.join(download_dir, filename)
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(download_dir, f"{base}_{counter}{ext or '.pdf'}")
            counter += 1

        upload.file.seek(0)
        with open(dest, "wb") as out_file:
            shutil.copyfileobj(upload.file, out_file)
        await upload.close()
        saved.append({"filename": os.path.basename(dest), "size": os.path.getsize(dest)})
        saved_names.append(os.path.basename(dest))

    copy_report: Dict[str, List[str]] = {"copied": [], "skipped": []}
    target_patient = session.get("patient_id")
    if target_patient and saved_names:
        copy_report = _copy_downloads_to_patient(target_patient, download_dir, saved_names)

    return {
        "status": "ok",
        "count": len(saved),
        "files": saved,
        "folder": download_dir,
        "copied_files": copy_report.get("copied"),
        "skipped_files": copy_report.get("skipped"),
    }


@app.get("/downloaded-pdfs-list")
def downloaded_pdfs_list() -> Dict[str, Any]:
    download_dir = os.path.join(os.getcwd(), "downloaded_pdfs")
    if not os.path.exists(download_dir):
        return {"files": [], "count": 0, "folder": download_dir}
    files: List[str] = []
    for ext in ("*.pdf", "*.PDF"):
        files.extend([os.path.basename(p) for p in glob.glob(os.path.join(download_dir, ext))])
    files = sorted(set(files))
    return {"files": files, "count": len(files), "folder": download_dir}


@app.post("/public/signup", response_model=SignupResponse)
def public_signup(req: SignupRequest) -> SignupResponse:
    patient_id = req.patient_id.strip()
    if not patient_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="patient_id obbligatorio")

    existing_credentials = load_patient_credentials(patient_id)
    if existing_credentials:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account già registrato")

    metadata = {
        "nome": req.nome,
        "codice_fiscale": req.codice_fiscale,
        "data_nascita": req.data_nascita,
        "email": str(req.email),
        "telefono": req.telefono,
        "note": req.note,
        "security_question": req.security_question,
    }

    authorize_patient(patient_id, metadata)
    password = secrets.token_urlsafe(6)
    try:
        register_patient_account(
            patient_id,
            str(req.email),
            password,
            req.security_question,
            req.security_answer,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    email_sent = False
    try:
        email_sent = send_signup_credentials(str(req.email), patient_id, password, metadata)
    except Exception as exc:
        print(f"[WARN] Invio email registrazione fallito per {patient_id}: {exc}")
    if email_sent:
        print(f"[INFO] Credenziali inviate via email a {req.email}")
    else:
        print(f"[INFO] Email non inviata per {req.email}.")

    message = (
        "Registrazione completata. Controlla la tua casella di posta per il riepilogo e conserva la password qui sotto."
        if email_sent
        else "Registrazione completata ma non siamo riusciti a inviare l'email di conferma. Contatta il supporto e conserva la password mostrata."
    )

    return SignupResponse(
        status="ok",
        patient_id=patient_id,
        password=password,
        email_sent=email_sent,
        message=message,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
