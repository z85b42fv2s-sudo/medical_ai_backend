import os
from supabase import create_client, Client

_client: Client | None = None

def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("Supabase configuration missing")
        _client = create_client(url, key)
    return _client


def get_bucket_name() -> str:
    bucket = os.getenv("SUPABASE_BUCKET")
    return bucket or "patient-documents"


def get_storage():
    return get_supabase().storage








