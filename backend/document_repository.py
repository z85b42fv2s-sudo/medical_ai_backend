from datetime import datetime
from typing import Any, Dict, List, Optional

from .supabase_client import get_supabase

COLLECTION_DOCUMENTS = "documents"
COLLECTION_ANALYSIS = "analysis_results"


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def list_documents(patient_id: str) -> List[Dict[str, Any]]:
    resp = (
        get_supabase()
        .table(COLLECTION_DOCUMENTS)
        .select("*")
        .eq("patient_id", patient_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def get_document_by_path(patient_id: str, stored_path: str) -> Optional[Dict[str, Any]]:
    resp = (
        get_supabase()
        .table(COLLECTION_DOCUMENTS)
        .select("*")
        .eq("patient_id", patient_id)
        .eq("stored_path", stored_path)
        .limit(1)
        .execute()
    )
    data = resp.data or []
    return data[0] if data else None


def upsert_document(
    patient_id: str,
    stored_path: str,
    *,
    original_filename: Optional[str] = None,
    specialty: Optional[str] = None,
    tipologia: Optional[str] = None,
    data_documento: Optional[str] = None,
    summary: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    current = get_document_by_path(patient_id, stored_path)
    payload = {
        "patient_id": patient_id,
        "stored_path": stored_path,
        "original_filename": original_filename or (current or {}).get("original_filename"),
        "specialty": specialty or (current or {}).get("specialty"),
        "tipologia": tipologia or (current or {}).get("tipologia"),
        "data_documento": data_documento or (current or {}).get("data_documento"),
        "summary": summary or (current or {}).get("summary"),
        "metadata": metadata or (current or {}).get("metadata") or {},
        "updated_at": _now_iso(),
    }
    if current:
        resp = (
            get_supabase()
            .table(COLLECTION_DOCUMENTS)
            .update(payload)
            .eq("id", current["id"])
            .execute()
        )
    else:
        payload["created_at"] = _now_iso()
        resp = get_supabase().table(COLLECTION_DOCUMENTS).insert(payload).execute()
    data = resp.data or []
    return data[0] if data else payload


def delete_document(document_id: str) -> None:
    get_supabase().table(COLLECTION_DOCUMENTS).delete().eq("id", document_id).execute()


def save_analysis_result(
    patient_id: str,
    document_id: Optional[str],
    json_path: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    record = {
        "patient_id": patient_id,
        "document_id": document_id,
        "json_path": json_path,
        "payload": payload,
        "created_at": _now_iso(),
    }
    resp = get_supabase().table(COLLECTION_ANALYSIS).insert(record).execute()
    return resp.data[0] if resp.data else record


def list_analysis_results(patient_id: str) -> List[Dict[str, Any]]:
    resp = (
        get_supabase()
        .table(COLLECTION_ANALYSIS)
        .select("*")
        .eq("patient_id", patient_id)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []
