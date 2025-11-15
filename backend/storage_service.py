import os
import tempfile
from pathlib import Path
from typing import Optional

from .supabase_client import get_storage, get_bucket_name


class StorageServiceError(RuntimeError):
    """Raised when a Supabase Storage operation fails."""


def _storage():
    return get_storage().from_(get_bucket_name())


def _normalize_filename(filename: str) -> str:
    return Path(filename).name.replace("\\", "_").replace("/", "_")


def build_storage_path(patient_id: str, filename: str, folder: Optional[str] = None) -> str:
    patient_slug = patient_id.strip().replace(" ", "_").lower()
    normalized = _normalize_filename(filename)
    if folder:
        folder_slug = Path(folder).name.replace("\\", "_").replace("/", "_")
        return f"{patient_slug}/{folder_slug}/{normalized}"
    return f"{patient_slug}/{normalized}"


def upload_pdf(patient_id: str, local_path: str, stored_filename: Optional[str] = None, folder: Optional[str] = None) -> str:
    if not os.path.exists(local_path):
        raise StorageServiceError(f"File not found: {local_path}")
    stored_filename = stored_filename or os.path.basename(local_path)
    stored_path = build_storage_path(patient_id, stored_filename, folder=folder)
    with open(local_path, "rb") as fh:
        response = _storage().upload(stored_path, fh, {"cacheControl": "3600", "upsert": "true"})
    if isinstance(response, dict) and response.get("error"):
        raise StorageServiceError(response["error"]["message"])
    return stored_path


def download_pdf_to_temp(stored_path: str) -> str:
    response = _storage().download(stored_path)
    if isinstance(response, dict) and response.get("error"):
        raise StorageServiceError(response["error"]["message"])
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as temp_file:
        temp_file.write(response)
    return temp_path


def delete_pdf(stored_path: str) -> None:
    response = _storage().remove([stored_path])
    if isinstance(response, dict) and response.get("error"):
        raise StorageServiceError(response["error"]["message"])


def generate_signed_url(stored_path: str, expires_in: int = 3600) -> str:
    response = _storage().create_signed_url(stored_path, expires_in)
    if isinstance(response, dict) and response.get("error"):
        raise StorageServiceError(response["error"]["message"])
    return response["signedURL"]


