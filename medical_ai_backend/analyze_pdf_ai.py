# analyze_pdf_ai.py
# -*- coding: utf-8 -*-
"""
Analisi clinica dei PDF + Q&A sui risultati
- Estrae testo dai PDF (PyMuPDF/fitz)
- Genera JSON strutturati per ogni documento in analysis_results/
- Modalità Q&A per interrogare i JSON già prodotti
Requisiti:
  pip install pymupdf python-dotenv openai==1.* tqdm
  # Per OCR (PDF scansionati): pip install pillow pytesseract
Ambiente:
  Variabile OPENAI_API_KEY impostata (o .env con OPENAI_API_KEY=...)
Uso:
  # Analizza tutti i PDF in una cartella (con filtri opzionali)
  python analyze_pdf_ai.py --dir downloaded_pdfs --from 2024-01-01 --to 2025-12-31 --category cardiologia --kw antibiotico

  # Q&A sui risultati già analizzati
  python analyze_pdf_ai.py --ask "Quali farmaci sono stati prescritti nel 2025?"

  # Forza il modello (default: gpt-5)
  python analyze_pdf_ai.py --model gpt-5
"""

import os
import re
import io
import sys
import json
import time
import glob
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
from dotenv import load_dotenv
from tqdm import tqdm

from openai import OpenAI

from medical_taxonomy import MEDICAL_SPECIALTIES
from patient_profiles import (
    update_patient_profile,
    authorize_patient,
    is_patient_authorized,
    get_pending_patients,
    compute_patient_id_for_result,
    get_patient_documents_dir,
    list_authorized_patients,
)

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None  # OCR opzionale
    Image = None

try:
    DEFAULT_OCR_ZOOM = float(os.getenv("OCR_ZOOM", "3.0"))
except ValueError:
    DEFAULT_OCR_ZOOM = 3.0
DEFAULT_OCR_PSM = os.getenv("OCR_PSM", "6")

# =========================
# Config di base
# =========================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY mancante. Impostalo nell'ambiente o nel file .env"
    )

client = OpenAI(api_key=OPENAI_API_KEY)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

if pytesseract is not None:
    tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    elif os.name == "nt":
        # su Windows Tesseract non è nel PATH per default; segnala come configurarlo
        log_hint = (
            "Per usare l'OCR imposta la variabile TESSERACT_CMD con il percorso di tesseract.exe "
            "(es. C:\\Program Files\\Tesseract-OCR\\tesseract.exe)."
        )
        # usiamo print diretto per non dipendere da log()
        print(log_hint)

DEFAULT_MODEL = os.getenv("DEFAULT_ANALYSIS_MODEL", os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"))
FALLBACK_CHAT_MODEL = os.getenv("FALLBACK_CHAT_MODEL", "gpt-4o-mini")
VISION_MODEL = os.getenv(
    "VISION_ANALYSIS_MODEL",
    os.getenv("DEFAULT_VISION_MODEL", os.getenv("OPENAI_VISION_MODEL", "gpt-4o"))
)
RESULTS_DIR = os.path.join(os.getcwd(), "analysis_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

QUERY_HISTORY = os.path.join(RESULTS_DIR, "query_history.json")


# =========================
# Utility
# =========================
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def safe_write_json(path: str, obj: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_all_results(patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    visited: set[str] = set()

    def ingest(path: str) -> None:
        if not os.path.exists(path):
            return
        key = os.path.abspath(path)
        if key in visited:
            return
        visited.add(key)
        if os.path.basename(path) == os.path.basename(QUERY_HISTORY):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                items.append(json.load(f))
        except Exception:
            return

    patterns: List[str] = []
    if patient_id:
        patient_dir = os.path.join(RESULTS_DIR, patient_id)
        patterns.append(os.path.join(patient_dir, "*.json"))
    else:
        patterns.append(os.path.join(RESULTS_DIR, "*.json"))
        patterns.append(os.path.join(RESULTS_DIR, "*", "*.json"))

    for pattern in patterns:
        for fp in glob.glob(pattern):
            ingest(fp)

    return items


def add_query_history(question: str, answer: str) -> None:
    item = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "answer": answer,
    }
    hist = []
    if os.path.exists(QUERY_HISTORY):
        try:
            with open(QUERY_HISTORY, "r", encoding="utf-8") as f:
                hist = json.load(f)
        except Exception:
            hist = []
    hist.append(item)
    safe_write_json(QUERY_HISTORY, hist)


DOCUMENT_TIPOLOGIES = [
    "prescrizione_medica",
    "referto_laboratorio",
    "referto_diagnostica",
    "lettera_dimissione",
    "cartella_clinica",
    "altro",
]

CATEGORY_CHOICES = [
    "cardiologia",
    "allergologia",
    "ortopedia",
    "gastroenterologia",
    "oncologia",
    "pneumologia",
    "nefrologia",
    "neurologia",
    "urologia",
    "ginecologia",
    "ematologia",
    "endocrinologia",
    "infettivologia",
    "dermatologia",
    "medicina_generale",
    "altro",
]


SPECIALTY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "ematologia": (
        "ematolog",
        "emocromo",
        "globuli rossi",
        "eritroblast",
        "piastrin",
        "mchc",
        "rdw",
        "ferritin",
        "hgb",
        "hct",
    ),
    "cardiologia": (
        "cardiolog",
        "elettrocardiogramma",
        "ecg",
        "holter",
        "troponin",
        "bnp",
        "ipertensione",
        "dispnea",
        "ramipril",
        "ritmo sinusale",
        "pressione arteriosa",
        "soffio",
        "fc ",
        "mmhg",
        "mitral",
    ),
    "gastroenterologia": (
        "transaminas",
        "alt (gpt)",
        "ast (got)",
        "gamma gt",
        "bilirubina",
        "fegato",
        "gastro",
    ),
    "endocrinologia": (
        "tiroide",
        "tsh",
        "ft3",
        "ft4",
        "endocrinolog",
        "insulina",
        "glicemia",
    ),
    "nefrologia": (
        "creatinina",
        "clearance",
        "proteinuria",
        "nefrolog",
        "azotemia",
    ),
    "oncologia": (
        "oncolog",
        "chemioterapia",
        "marker tumorale",
        "metastasi",
        "neoplasia",
    ),
    "pneumologia": (
        "spirometria",
        "pneumolog",
        "saturazione",
        "polmon",
        "torac",
    ),
    "dermatologia": (
        "dermatolog",
        "cute",
        "lesione cutane",
        "dermatite",
        "epiderm",
    ),
    "allergologia": (
        "ige",
        "prick test",
        "allerg",
        "reattivita",
        "sensibilizzazione",
        "kua",
        "ku/l",
        "kuaa/l",
        "kuaa",
        "anisakis",
        "arachide",
        "tropomiosina",
        "albumina",
        "pru",
        "f75",
        "f95",
        "f1",
        "f2",
        "p4",
    ),
    "ginecologia": (
        "ginecolog",
        "pap test",
        "ecografia transvaginale",
        "utero",
        "ovaio",
    ),
    "urologia": (
        "psa",
        "prostata",
        "vescica",
        "urolog",
        "renale",
    ),
    "ortopedia": (
        "ortoped",
        "frattura",
        "articolazione",
        "protesi",
        "osteoporosi",
        "ginocchio",
        "menisc",
        "legamento crociato",
        "legamento collaterale",
        "rotula",
        "tibia",
        "femore",
        "cartilagin",
        "condilo",
        "gonartrosi",
        "caviglia",
        "rm ginocchio",
        "rx ginocchio",
        "risonanza ginocchio",
        "jsw",
        "mjsw",
        "cmf",
        "imft",
    ),
    "neurologia": (
        "neurolog",
        "elettromiografia",
        "rm encefalo",
        "epilessia",
        "sclerosi",
    ),
    "radiologia": (
        "radiolog",
        "tomografia",
        "risonanza",
        "radiografia",
        "ecografia",
    ),
    "medicina generale": (
        "medico curante",
        "medicina generale",
        "mmg",
        "medicina di base",
    ),
}


def infer_specialty_from_text(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    if not lowered:
        return None
    for specialty, keywords in SPECIALTY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return specialty
    return None


def normalize_specialty_field(record: Dict[str, Any]) -> None:
    doc = record.setdefault("documento", {"specialita": "altro"})
    spec_raw = (doc.get("specialita") or "").strip().lower()
    for known in MEDICAL_SPECIALTIES:
        if spec_raw == known.lower():
            doc["specialita"] = known
            return
    doc["specialita"] = spec_raw or "altro"


def merge_record_with_fallback(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(fallback, dict):
        return primary

    for nested in ("documento", "paziente"):
        dest = primary.setdefault(nested, {})
        src = fallback.get(nested) or {}
        for key, value in src.items():
            if not value:
                continue
            current = dest.get(key)
            if not current or (nested == "documento" and key == "specialita" and (current.lower() in ("", "altro"))):
                dest[key] = value

    for field in ("categoria", "riassunto", "medico_ente"):
        value = fallback.get(field)
        if value and (not primary.get(field) or primary.get(field) in ("", "altro")):
            primary[field] = value

    list_fields = [
        "diagnosi_principali",
        "farmaci_prescritti",
        "terapie",
        "esami_laboratorio",
        "esami_diagnostica",
        "anamnesi",
        "date_rilevanti",
        "note_rilevanti",
    ]
    for field in list_fields:
        existing = primary.setdefault(field, [])
        for item in fallback.get(field, []) or []:
            if item and item not in existing:
                existing.append(item)

    if not primary.get("file") and fallback.get("file"):
        primary["file"] = fallback["file"]
    if not primary.get("path") and fallback.get("path"):
        primary["path"] = fallback["path"]

    return primary


def build_authorized_index() -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    try:
        for entry in list_authorized_patients():
            pid = entry.get("patient_id")
            if pid:
                index[pid] = entry
    except Exception:
        pass
    return index


def make_empty_record(name: str, fpath: str) -> Dict[str, Any]:
    timestamp = datetime.now().isoformat(timespec="seconds")
    return {
        "file": name,
        "path": fpath,
        "analysis_timestamp": timestamp,
        "documento": {
            "tipologia": "",
            "specialita": "altro",
            "data_documento": "",
        },
        "paziente": {
            "nome": "",
            "codice_fiscale": "",
            "data_nascita": "",
        },
        "categoria": "altro",
        "riassunto": "",
        "diagnosi_principali": [],
        "farmaci_prescritti": [],
        "terapie": [],
        "esami_laboratorio": [],
        "esami_diagnostica": [],
        "anamnesi": [],
        "date_rilevanti": [],
        "medico_ente": "",
        "note_rilevanti": [],
    }


def _normalize_result_name(filename: str) -> str:
    name, ext = os.path.splitext(filename.lower())
    name = re.sub(r"\s+\(\d+\)$", "", name)
    name = re.sub(r"--\d+-*$", "", name)
    name = re.sub(r"[_\-]+(\d+)$", "", name)
    return f"{name}{ext}"


def remove_duplicate_results(directory: str) -> int:
    removed = 0
    seen: set[str] = set()
    paths = sorted(
        glob.glob(os.path.join(directory, "*.json")),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for path in paths:
        base = _normalize_result_name(os.path.basename(path))
        if base in seen:
            try:
                os.remove(path)
                removed += 1
            except Exception:
                continue
        else:
            seen.add(base)
    return removed


def upload_file_for_vision(path: str):
    last_error: Optional[Exception] = None
    for purpose in ("vision", "assistants"):
        try:
            with open(path, "rb") as fh:
                return client.files.create(file=fh, purpose=purpose)
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"Caricamento file per analisi vision fallito: {last_error}")


def analyze_pdf_with_vision(model: str, fpath: str, doc_name: str) -> Dict[str, Any]:
    upload = upload_file_for_vision(fpath)
    try:
        resp = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": VISION_SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": build_vision_prompt(doc_name)},
                        {"type": "input_file", "file_id": upload.id},
                    ],
                },
            ],
            max_output_tokens=1400,
        )
        txt = _collect_output_text(resp)
        if not txt:
            raise RuntimeError("Vision: risposta vuota")
        try:
            return json.loads(txt)
        except Exception:
            match = re.search(r"\{.*\}", txt, re.S)
            if match:
                return json.loads(match.group(0))
            raise
    finally:
        try:
            client.files.delete(upload.id)
        except Exception:
            pass


DATE_SEARCH_PATTERNS = [
    r"\d{4}-\d{1,2}-\d{1,2}",
    r"\d{1,2}/\d{1,2}/\d{4}",
    r"\d{1,2}-\d{1,2}-\d{4}",
    r"\d{1,2}\.\d{1,2}\.\d{4}",
]

CF_REGEX = re.compile(r"\b([A-Z]{6}[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z])\b", re.I)
NAME_HINT_REGEX = re.compile(
    r"(?:nome(?: del)?(?: paziente| assistito)?|assistito|paziente)\s*[:\-]\s*([A-ZÀ-ÖÙ-Ý' ]{3,})",
    re.IGNORECASE,
)
DOB_HINT_REGEXES = [
    re.compile(r"(?:nato/a?\s*il|data\s+di\s+nascita|nascita)\s*[:\-]?\s*([0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4})", re.I),
    re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})"),
]
DOC_DATE_HINT_REGEXES = [
    re.compile(r"data\s+(?:di\s+)?(?:prescrizione|erogazione|referto|esame|emissione)\s*[:\-]?\s*([0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4})", re.I),
    re.compile(r"(?:emesso|rilasciato)\s+il\s+([0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4})", re.I),
]

def strip_copy_suffix(value: str) -> str:
    match = re.match(r"^(.*)\s+\((\d+)\)$", value.strip())
    return match.group(1) if match else value.strip()


def normalize_date_token(token: str) -> Optional[str]:
    token = (token or "").strip()
    if not token:
        return None

    cleaned = token.replace("/", "-").replace(".", "-")
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    parts = cleaned.split("-")
    if len(parts) != 3:
        return None

    try:
        if len(parts[0]) == 4:  # formato YYYY-M-D
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts[2]) == 4:  # formato D-M-YYYY
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        else:
            return None
        dt = datetime(year, month, day)
    except Exception:
        return None
    return dt.strftime("%Y-%m-%d")


def looks_like_date(s: str) -> bool:
    return normalize_date_token(s) is not None


def extract_iso_date(value: str) -> Optional[tuple[str, str]]:
    for pattern in DATE_SEARCH_PATTERNS:
        m = re.search(pattern, value or "")
        if not m:
            continue
        iso = normalize_date_token(m.group(0))
        if iso:
            return iso, m.group(0)
    return None


def normalize_name(raw: str) -> str:
    raw = strip_copy_suffix(raw).strip()
    if not raw:
        return ""
    parts = [p for p in re.split(r"[\\s]+", raw) if len(p) > 1]
    return " ".join(p.capitalize() for p in parts)


def extract_patient_metadata_from_text(text: str) -> Dict[str, str]:
    info: Dict[str, str] = {}
    if not text:
        return info

    lines = text.splitlines()
    cf_candidates: List[tuple[int, int, str]] = []

    for idx, line in enumerate(lines):
        line_clean = line.strip()
        if not line_clean:
            continue

        lower_line = line_clean.lower()
        upper_line = line_clean.upper()

        sanitized = re.sub(r"[^A-Z0-9]", "", upper_line)
        for cf_match in CF_REGEX.findall(sanitized):
            score = 0
            neighborhood = " ".join(lines[max(0, idx - 2): min(len(lines), idx + 3)]).lower()
            if "codice" in neighborhood and "fisc" in neighborhood:
                score += 3
            if any(hint in neighborhood for hint in ("assistito", "paziente", "nome")):
                score += 2
            if "medico" in neighborhood or "dott" in neighborhood:
                score -= 2
            cf_candidates.append((score, idx, cf_match.upper()))

        if (
            "codice_fiscale" not in info
            and "codice" in lower_line
            and "fisc" in lower_line
            and "medic" not in lower_line
        ):
            m = CF_REGEX.search(upper_line)
            if m:
                info.setdefault("codice_fiscale", m.group(1).upper())

        if re.search(r"(cognome|nome|assistito|paziente)\s*[:\-]", lower_line):
            for j in range(idx + 1, min(idx + 5, len(lines))):
                candidate_line = lines[j].strip()
                if not candidate_line:
                    continue
                candidate = normalize_name(candidate_line)
                if len(candidate.split()) >= 2:
                    info.setdefault("nome", candidate)
                    break

        name_match = NAME_HINT_REGEX.search(line_clean)
        if name_match:
            candidate = normalize_name(name_match.group(1))
            if len(candidate.split()) >= 2:
                info.setdefault("nome", candidate)

        for regex in DOB_HINT_REGEXES:
            dob_match = regex.search(line_clean)
            if dob_match:
                iso = normalize_date_token(dob_match.group(1))
                if iso:
                    info.setdefault("data_nascita", iso)

        for regex in DOC_DATE_HINT_REGEXES:
            doc_match = regex.search(line_clean)
            if doc_match:
                iso = normalize_date_token(doc_match.group(1))
                if iso:
                    info.setdefault("data_documento", iso)

    if cf_candidates:
        cf_candidates.sort(key=lambda x: (-x[0], x[1]))
        best_score, _, best_cf = cf_candidates[0]
        if best_score >= 0 or not info.get("codice_fiscale"):
            info["codice_fiscale"] = best_cf

    if "codice_fiscale" not in info:
        upper_text = text.upper()
        m = CF_REGEX.search(upper_text)
        if m:
            info["codice_fiscale"] = m.group(1).upper()
        else:
            compact = re.sub(r"[^A-Z0-9]", "", upper_text)
            m2 = CF_REGEX.search(compact)
            if m2:
                info["codice_fiscale"] = m2.group(1).upper()

    if "nome" not in info:
        around: List[str] = []
        if info.get("codice_fiscale"):
            cf = info["codice_fiscale"]
            for idx, line in enumerate(lines):
                if cf and cf in re.sub(r"[^A-Z0-9]", "", line.upper()):
                    around.extend(lines[max(0, idx - 3): idx + 4])
                    break
        if not around:
            around = lines[:8]

        blacklist = {"tipo", "ricetta", "esenzione", "codice", "asl", "provincia", "note"}
        for segment in around:
            segment = segment.strip()
            if not segment:
                continue
            if any(bad in segment.lower() for bad in blacklist):
                continue
            m = re.search(r"([A-ZÀ-ÖÙ-Ý']+\s+[A-ZÀ-ÖÙ-Ý']+)", segment.upper())
            if m:
                candidate = normalize_name(m.group(1))
                if len(candidate.split()) >= 2:
                    info.setdefault("nome", candidate)
                    break

    if "data_documento" not in info:
        hit = extract_iso_date(text)
        if hit:
            info["data_documento"] = hit[0]

    return info


def enrich_record_with_heuristics(record: Dict[str, Any], raw_text: str) -> None:
    meta = extract_patient_metadata_from_text(raw_text)
    if not meta:
        return

    paziente = record.setdefault("paziente", {"nome": "", "codice_fiscale": "", "data_nascita": ""})
    doc = record.setdefault("documento", {"tipologia": "", "specialita": "altro", "data_documento": ""})

    if meta.get("codice_fiscale") and not paziente.get("codice_fiscale"):
        paziente["codice_fiscale"] = meta["codice_fiscale"].upper()
    if meta.get("nome") and not paziente.get("nome"):
        paziente["nome"] = meta["nome"].title()
    if meta.get("data_nascita") and not paziente.get("data_nascita"):
        paziente["data_nascita"] = meta["data_nascita"]

    if meta.get("data_documento") and not doc.get("data_documento"):
        doc["data_documento"] = meta["data_documento"]


def ensure_ocr_available() -> None:
    if pytesseract is None or Image is None:
        raise RuntimeError(
            "OCR richiesto ma i pacchetti pillow/pytesseract non sono installati. "
            "Esegui 'pip install pillow pytesseract' e assicurati che Tesseract sia configurato nel sistema."
        )


def ocr_page_text(
    page: "fitz.Page",
    page_index: int,
    lang: str,
    zoom: Optional[float] = None,
    psm: Optional[str] = None,
) -> str:
    """Esegue OCR su una pagina PyMuPDF restituendo il testo estratto."""
    ensure_ocr_available()
    try:
        zoom = zoom or DEFAULT_OCR_ZOOM  # fattore zoom (3.0 ≈ 216 DPI)
        psm = psm or DEFAULT_OCR_PSM
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        buffer = io.BytesIO(pix.tobytes("png"))
        with Image.open(buffer) as img:
            config = f"--psm {psm}".strip()
            text = pytesseract.image_to_string(
                img,
                lang=lang or "ita",
                config=config,
            )
        text = text.strip()
        if text:
            log(
                f"OCR pagina {page_index + 1}: testo estratto {len(text)} caratteri "
                f"(zoom={zoom}, psm={psm})"
            )
        else:
            log(f"OCR pagina {page_index + 1}: nessun testo rilevato")
        return text
    except Exception as exc:
        log(f"Errore OCR pagina {page_index + 1}: {exc}")
        return ""


# =========================
# Estrazione testo dai PDF
# =========================
def normalize_page_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_text_pdf(
    path: str,
    max_chars: int = 150000,
    use_ocr: bool = True,
    ocr_lang: str = "ita",
    ocr_zoom: Optional[float] = None,
    ocr_psm: Optional[str] = None,
) -> str:
    text_chunks: List[str] = []
    with fitz.open(path) as doc:
        for idx, page in enumerate(doc):
            page_text = normalize_page_text(page.get_text("text") or "")

            if len(page_text) < 80:
                blocks = page.get_text("blocks") or []
                block_text = "\n".join(
                    block[4] for block in blocks if len(block) >= 5 and isinstance(block[4], str)
                )
                block_text = normalize_page_text(block_text)
                if len(block_text) > len(page_text):
                    page_text = block_text

            if page_text:
                text_chunks.append(page_text)

            should_try_ocr = use_ocr and len(page_text) < 200
            if should_try_ocr:
                zoom_value = ocr_zoom or (DEFAULT_OCR_ZOOM * 1.15)
                ocr_text = ocr_page_text(
                    page,
                    idx,
                    ocr_lang,
                    zoom=zoom_value,
                    psm=ocr_psm,
                )
                ocr_text = normalize_page_text(ocr_text)
                if ocr_text:
                    if page_text and text_chunks:
                        candidate = ocr_text if len(ocr_text) > len(page_text) else page_text
                        text_chunks[-1] = candidate
                    else:
                        text_chunks.append(ocr_text)

    joined = "\n".join(text_chunks).strip()
    return joined[:max_chars]


def split_chunks(text: str, max_len: int = 7000) -> List[str]:
    # split grossolano per non superare limiti di token
    chunks = []
    buf = []
    cur = 0
    for line in text.splitlines():
        if cur + len(line) + 1 > max_len:
            chunks.append("\n".join(buf))
            buf = [line]
            cur = len(line) + 1
        else:
            buf.append(line)
            cur += len(line) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks


# =========================
# Chiamate AI (Responses API)
# =========================
ANALYSIS_SYSTEM = (
    "Sei un assistente medico che estrae informazioni cliniche strutturate in JSON rigoroso. "
    "Utilizza esclusivamente i dati presenti nel testo; se un campo non e menzionato lascia stringa o lista vuota. "
    "Quando il contenuto lo consente, classifica esplicitamente la specialita medica piu appropriata invece di 'altro'."
)

ANALYSIS_USER_TEMPLATE = """Analizza il seguente testo clinico. Restituisci SOLO un JSON valido (nessun testo libero esterno) con questa struttura:
{{
  "documento": {{
    "tipologia": "<scegli tra: {document_types}>",
    "specialita": "<scegli tra: {specialty_list}>",
    "data_documento": "YYYY-MM-DD"
  }},
  "paziente": {{
    "nome": "<nome e cognome se presenti>",
    "codice_fiscale": "<codice fiscale se presente>",
    "data_nascita": "YYYY-MM-DD"
  }},
  "categoria": "<scegli tra: {category_list}>",
  "riassunto": "<massimo 6-8 frasi, preciso e clinico>",
  "diagnosi_principali": ["..."],
  "farmaci_prescritti": ["<farmaco - dosaggio - posologia>"],
  "terapie": ["<farmaco/intervento - posologia/periodo>"],
  "esami_laboratorio": ["<nome esame: valore (unita) - range se disponibile>"],
  "esami_diagnostica": ["<tipo esame: risultato sintetico>"],
  "anamnesi": ["<evento clinico rilevante>"],
  "date_rilevanti": ["YYYY-MM-DD - descrizione"],
  "medico_ente": "<medico o struttura indicata nel documento>",
  "note_rilevanti": ["..."]
}}

Regole:
- Usa stringhe vuote o liste vuote solo se l'informazione NON e presente nel testo; se un dato e esplicitamente indicato trascrivilo nel campo corrispondente.
- Riporta soltanto informazioni esplicitamente presenti nel testo; non aggiungere, non dedurre e non inventare dati.
- Se il documento contiene codice fiscale, nome, cognome o data di nascita, riporta tali valori nei campi paziente corrispondenti (codice fiscale in maiuscolo).
- Utilizza le informazioni presenti anche in tabelle, intestazioni e note per valorizzare terapie, esami di laboratorio e diagnostica per immagini.
- Determina la tipologia e la specialita piu appropriate in base al contenuto del documento e usa \"altro\" solo se la specialita non e riconoscibile.
- Formatta tutte le date come YYYY-MM-DD quando possibile.
- Mantieni l'output rigorosamente in JSON valido.

Esempio di risposta:
{{
  "documento": {{
    "tipologia": "prescrizione_medica",
    "specialita": "cardiologia",
    "data_documento": "2025-02-25"
  }},
  "paziente": {{
    "nome": "Rossi Mario",
    "codice_fiscale": "MRRRSS80A01H501Z",
    "data_nascita": "1980-01-01"
  }},
  "categoria": "cardiologia",
  "riassunto": "Prescrizione di Tachipirina 500 mg per sintomi influenzali con visita cardiologica di controllo.",
  "diagnosi_principali": ["influenza"],
  "farmaci_prescritti": ["Tachipirina 500 mg - 1 compressa ogni 8 ore"],
  "terapie": ["Tachipirina 500 mg - 1 compressa ogni 8 ore per 5 giorni"],
  "esami_laboratorio": [],
  "esami_diagnostica": [],
  "anamnesi": [],
  "date_rilevanti": ["2025-02-25 - data prescrizione"],
  "medico_ente": "Studio Medico Rossi",
  "note_rilevanti": []
}}

Testo (chunk {{i}}/{{n}}) del documento {{doc_name}}:

{{chunk_text}}
"""

_analysis_user_template_prefilled = ANALYSIS_USER_TEMPLATE.format(
    document_types=", ".join(DOCUMENT_TIPOLOGIES),
    specialty_list=", ".join(MEDICAL_SPECIALTIES),
    category_list=", ".join(CATEGORY_CHOICES),
    i="{i}",
    n="{n}",
    doc_name="{doc_name}",
    chunk_text="{chunk_text}",
)
ANALYSIS_USER_TMPL = (
    _analysis_user_template_prefilled.replace("{", "{{").replace("}", "}}")
    .replace("{{i}}", "{i}")
    .replace("{{n}}", "{n}")
    .replace("{{doc_name}}", "{doc_name}")
    .replace("{{chunk_text}}", "{chunk_text}")
)

def build_analysis_prompt(i: int, n: int, doc_name: str, chunk_text: str) -> str:
    return ANALYSIS_USER_TEMPLATE.format(
        document_types=", ".join(DOCUMENT_TIPOLOGIES),
        specialty_list=", ".join(MEDICAL_SPECIALTIES),
        category_list=", ".join(CATEGORY_CHOICES),
        i=i,
        n=n,
        doc_name=doc_name,
        chunk_text=chunk_text,
    )

VISION_SYSTEM_PROMPT = (
    "Sei un assistente clinico. Devi analizzare il documento allegato (PDF o immagine) e restituire un JSON "
    "rigorosamente conforme allo schema richiesto. Usa solo le informazioni presenti nel documento."
)

VISION_USER_TEMPLATE = """Analizza il documento allegato "{doc_name}".
Restituisci SOLO un JSON valido (nessun testo extra) con la seguente struttura:
{{
  "documento": {{
    "tipologia": "<scegli tra: {document_types}>",
    "specialita": "<scegli tra: {specialty_list}>",
    "data_documento": "YYYY-MM-DD"
  }},
  "paziente": {{
    "nome": "<nome e cognome se presenti>",
    "codice_fiscale": "<codice fiscale se presente>",
    "data_nascita": "YYYY-MM-DD"
  }},
  "categoria": "<scegli tra: {category_list}>",
  "riassunto": "<massimo 6-8 frasi, preciso e clinico>",
  "diagnosi_principali": ["..."],
  "farmaci_prescritti": ["<farmaco - dosaggio - posologia>"],
  "terapie": ["<farmaco/intervento - posologia/periodo>"],
  "esami_laboratorio": ["<nome esame: valore (unita) - range se disponibile>"],
  "esami_diagnostica": ["<tipo esame: risultato sintetico>"],
  "anamnesi": ["<evento clinico rilevante>"],
  "date_rilevanti": ["YYYY-MM-DD - descrizione"],
  "medico_ente": "<medico o struttura indicata nel documento>",
  "note_rilevanti": ["..."]
}}

Regole:
- Non inventare informazioni non presenti nel documento.
- Riconosci la specialita clinica piu appropriata in base al contenuto e usa "altro" solo se realmente assente.
- Mantieni il JSON valido (nessun commento, nessun testo fuori struttura).
"""


def build_vision_prompt(doc_name: str) -> str:
    return VISION_USER_TEMPLATE.format(
        doc_name=doc_name,
        document_types=", ".join(DOCUMENT_TIPOLOGIES),
        specialty_list=", ".join(MEDICAL_SPECIALTIES),
        category_list=", ".join(CATEGORY_CHOICES),
    )

QUERY_SYSTEM = (
    "Sei un assistente che risponde a domande usando solo i CONTENUTI forniti (JSON clinici). "
    "Se l'informazione non è nei documenti, dillo chiaramente."
)

QUERY_USER_TMPL = """Hai a disposizione una lista di record clinici in JSON (uno per documento). Rispondi alla domanda in modo accurato e sintetico.

DOMANDA: {question}

RECORD_CLINICI (JSON):
{records_json}

Formato di risposta:
- Testo chiaro e conciso
- Se utile, una tabella (testuale) con colonne pertinenti (es. data, categoria, diagnosi, farmaco, medico)
- Cita sempre da quale documento proviene ogni informazione (campo "file")
"""


def _collect_output_text(resp: Any) -> str:
    txt = getattr(resp, "output_text", None)
    if txt:
        return txt

    pieces: List[str] = []
    for item in getattr(resp, "output", []) or []:
        content = getattr(item, "content", None)
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    pieces.append(c.get("text", ""))
        elif isinstance(content, str):
            pieces.append(content)
    return "".join(pieces).strip()


def call_ai_json(model: str, system: str, user: str, max_out: int = 1200) -> Dict[str, Any]:
    """
    Usa Responses API; restituisce dict.
    """
    txt = ""
    need_fallback = False
    last_error: Optional[Exception] = None
    try:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_output_tokens=max_out,
        )
        txt = _collect_output_text(resp)
        if not txt:
            need_fallback = True
    except Exception as exc:
        need_fallback = True
        last_error = exc

    if need_fallback or not txt:
        for chat_model in (model, FALLBACK_CHAT_MODEL):
            try:
                kwargs = {
                    "model": chat_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                }
                if chat_model != "gpt-5":
                    kwargs["temperature"] = 0
                chat = client.chat.completions.create(
                    **kwargs,
                )
                txt = chat.choices[0].message.content.strip()
                if txt:
                    break
            except Exception as exc:
                last_error = exc
                continue
        if not txt:
            raise RuntimeError(f"AI chat fallback failed: {last_error}") from last_error
    # parsing robusto
    try:
        return json.loads(txt)
    except Exception:
        # prova a estrarre la prima sezione che sembra JSON
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    raise RuntimeError("AI: impossibile decodificare JSON.")


def call_ai_text(model: str, system: str, user: str, max_out: int = 1200) -> str:
    try:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_output_tokens=max_out,
        )
        txt = _collect_output_text(resp)
        if not txt:
            raise ValueError("empty_output")
        return txt.strip()
    except Exception as fallback_exc:
        last_error = fallback_exc

    for chat_model in (model, FALLBACK_CHAT_MODEL):
        try:
            kwargs = {
                "model": chat_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if chat_model != "gpt-5":
                kwargs["temperature"] = 0
            chat = client.chat.completions.create(
                **kwargs,
            )
            return chat.choices[0].message.content.strip()
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"AI chat fallback failed: {last_error}")


# =========================
# Analisi singolo PDF
# =========================
def analyze_pdfs(
    model: str,
    fpath: str,
    *,
    use_ocr: bool = True,
    ocr_lang: str = "ita",
    ocr_zoom: Optional[float] = None,
    ocr_psm: Optional[str] = None,
    dump_text: bool = False,
    raw_text_dir: Optional[str] = None,
    vision_only: bool = False,
    vision_fallback: bool = True,
) -> Dict[str, Any]:
    name = os.path.basename(fpath)
    if vision_only:
        if not VISION_MODEL:
            raise RuntimeError("Vision model non configurato per l'analisi diretta.")
        base = make_empty_record(name, fpath)
        vision = analyze_pdf_with_vision(VISION_MODEL or model, fpath, name)
        merged = merge_record_with_fallback(base, vision)
        normalize_specialty_field(merged)
        merged["analysis_timestamp"] = datetime.now().isoformat(timespec="seconds")
        merged.setdefault("note_rilevanti", [])
        note = "Analisi eseguita direttamente con modello Vision."
        if note not in merged["note_rilevanti"]:
            merged["note_rilevanti"].append(note)
        return merged
    if use_ocr and vision_only:
        pass  # placeholder to satisfy type checker; branch returns above.

    text = extract_text_pdf(
        fpath,
        use_ocr=use_ocr,
        ocr_lang=ocr_lang,
        ocr_zoom=ocr_zoom,
        ocr_psm=ocr_psm,
    )
    if not text.strip():
        if use_ocr:
            raise RuntimeError(
                "Testo PDF vuoto anche dopo l'esecuzione dell'OCR. Verifica il documento."
            )
        raise RuntimeError(
            "Testo PDF vuoto: probabile scansione senza livello testuale. "
            "Riprova con l'opzione OCR (es. --ocr)."
        )

    if dump_text:
        dump_dir = raw_text_dir or os.path.join(RESULTS_DIR, "_raw_text")
        os.makedirs(dump_dir, exist_ok=True)
        dump_path = os.path.join(
            dump_dir, os.path.splitext(name)[0] + "_raw.txt"
        )
        with open(dump_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        log(f"Testo estratto salvato per debug: {dump_path}")

    chunks = split_chunks(text)
    results = []

    for i, chunk in enumerate(chunks, 1):
        prompt = build_analysis_prompt(i, len(chunks), name, chunk)
        try:
            out = call_ai_json(model, ANALYSIS_SYSTEM, prompt, max_out=1000)
            results.append(out)
        except Exception as e:
            results.append(
                {
                    "categoria": "altro",
                    "riassunto": "",
                    "diagnosi_principali": [],
                    "farmaci_prescritti": [],
                    "esami_principali": [],
                    "date_rilevanti": [],
                    "medico_ente": "",
                    "note_rilevanti": [f"Errore AI su chunk {i}: {e}"],
                }
            )

    # fusione semplice dei chunk
    merged = make_empty_record(name, fpath)

    def extend_list(key: str):
        merged.setdefault(key, [])
        for r in results:
            values = r.get(key)
            if isinstance(values, list):
                for x in values:
                    if x and x not in merged[key]:
                        merged[key].append(x)

    # categoria: prendi la più frequente diversa da 'altro'
    cats = [r.get("categoria", "altro") for r in results if isinstance(r, dict)]
    if cats:
        best = max(set(cats), key=cats.count)
        merged["categoria"] = best or "altro"

    # riassunto: prendi il più lungo
    summaries = [r.get("riassunto", "") for r in results if isinstance(r, dict)]
    merged["riassunto"] = max(summaries, key=len, default="").strip()

    extend_list("diagnosi_principali")
    extend_list("farmaci_prescritti")
    extend_list("terapie")
    extend_list("esami_laboratorio")
    extend_list("esami_diagnostica")
    extend_list("anamnesi")
    extend_list("date_rilevanti")
    extend_list("note_rilevanti")

    documento_candidates = [
        r.get("documento", {}) for r in results if isinstance(r, dict)
    ]
    paziente_candidates = [
        r.get("paziente", {}) for r in results if isinstance(r, dict)
    ]

    def pick_field(target: Dict[str, Any], candidates: List[Dict[str, Any]], key: str):
        if target.get(key):
            return
        for cand in candidates:
            value = cand.get(key)
            if value:
                target[key] = value
                break

    for field in ("tipologia", "data_documento", "specialita"):
        pick_field(merged["documento"], documento_candidates, field)
    for field in ("nome", "codice_fiscale", "data_nascita"):
        pick_field(merged["paziente"], paziente_candidates, field)

    normalize_specialty_field(merged)

    # medico_ente: primo non vuoto
    for r in results:
        me = r.get("medico_ente", "")
        if me:
            merged["medico_ente"] = me
            break

    # normalizza date
    norm_dates: List[str] = []
    for raw_date in merged["date_rilevanti"]:
        if not raw_date:
            continue

        parts = raw_date.split(" - ", 1)
        iso = normalize_date_token(parts[0]) if parts else None
        if iso:
            desc = parts[1].strip() if len(parts) > 1 else ""
            norm_dates.append(f"{iso} - {desc or 'evento'}")
            continue

        hit = extract_iso_date(raw_date)
        if hit:
            iso, original_fragment = hit
            remainder = raw_date.replace(original_fragment, "").strip(" -:;,.")
            norm_dates.append(f"{iso} - {remainder or 'evento'}")
            continue

        # Se non riusciamo a normalizzare, manteniamo l'informazione originale
        norm_dates.append(raw_date.strip())

    merged["date_rilevanti"] = list(dict.fromkeys(norm_dates))  # unique, preserve order

    if use_ocr:
        note_msg = "Testo estratto dal PDF tramite OCR abilitato."
        if note_msg not in merged["note_rilevanti"]:
            merged["note_rilevanti"].insert(0, note_msg)

    enrich_record_with_heuristics(merged, text)

    current_spec = (merged["documento"].get("specialita") or "").strip().lower()
    if current_spec in ("", "altro"):
        inferred_spec = infer_specialty_from_text(text)
        if inferred_spec:
            merged["documento"]["specialita"] = inferred_spec
            if merged.get("categoria") in ("", "altro", None):
                inferred_category = inferred_spec.replace(" ", "_")
                if inferred_category in CATEGORY_CHOICES:
                    merged["categoria"] = inferred_category
                else:
                    merged["categoria"] = inferred_spec

    specialty_unknown = (merged["documento"].get("specialita") or "").strip().lower() in ("", "altro")
    patient_info = merged.get("paziente") or {}
    patient_unknown = not any(patient_info.get(field) for field in ("codice_fiscale", "nome"))

    if vision_fallback and VISION_MODEL and (specialty_unknown or patient_unknown):
        reason_parts = []
        if specialty_unknown:
            reason_parts.append("specialita non determinata")
        if patient_unknown:
            reason_parts.append("paziente non identificato")
        log(f"[VISION] Avvio analisi vision ({', '.join(reason_parts)}).")
        try:
            vision_result = analyze_pdf_with_vision(VISION_MODEL, fpath, name)
            if isinstance(vision_result, dict):
                merged = merge_record_with_fallback(merged, vision_result)
                normalize_specialty_field(merged)
                vis_cat = vision_result.get("categoria")
                if vis_cat and (merged.get("categoria") in ("", "altro", None)):
                    merged["categoria"] = vis_cat
                merged.setdefault("note_rilevanti", [])
                note = "Analisi vision eseguita per completare la classificazione/identificazione."
                if note not in merged["note_rilevanti"]:
                    merged["note_rilevanti"].append(note)
        except Exception as vision_exc:
            merged.setdefault("note_rilevanti", [])
        merged["note_rilevanti"].append(f"[WARN] Vision fallback fallito: {vision_exc}")
    elif vision_fallback and not VISION_MODEL and (specialty_unknown or patient_unknown):
        merged.setdefault("note_rilevanti", [])
        merged["note_rilevanti"].append("[WARN] Vision fallback richiesto ma nessun modello vision configurato.")

    normalize_specialty_field(merged)
    merged["analysis_timestamp"] = datetime.now().isoformat(timespec="seconds")

    doc_date = merged["documento"].get("data_documento")
    if doc_date:
        iso_doc = normalize_date_token(doc_date)
        if iso_doc:
            formatted = f"{iso_doc} - data documento"
            if formatted not in merged["date_rilevanti"]:
                merged["date_rilevanti"].insert(0, formatted)

    return merged


# =========================
# Filtri per analisi batch
# =========================
def keep_file(name: str, after: Optional[str], before: Optional[str], kw: List[str]) -> bool:
    # Filtra per parole chiave nel nome file (se specificate)
    lower = name.lower()
    if kw:
        if not any(k.lower() in lower for k in kw):
            return False
    # Filtri data si applicano dopo (nel contenuto); qui non filtriamo per data
    return True


def sync_patient_profiles() -> int:
    count = 0
    for path in glob.glob(os.path.join(RESULTS_DIR, "*.json")):
        if os.path.basename(path) == os.path.basename(QUERY_HISTORY):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            update_patient_profile(data, path)
            count += 1
        except Exception as exc:
            log(f"[WARN] Impossibile sincronizzare profilo per {path}: {exc}")
    return count


# =========================
# Q&A sui risultati
# =========================
def qa_on_results(model: str, question: str, patient_id: Optional[str] = None) -> str:
    records = load_all_results(patient_id=patient_id)
    if not records:
        return "Non ci sono risultati analizzati in 'analysis_results/'. Esegui prima l'analisi dei PDF."

    # Per ridurre contesto, costruisci una vista compatta dei record
    compact = []
    for r in records:
        compact.append({
            "file": r.get("file"),
            "analysis_timestamp": r.get("analysis_timestamp"),
            "categoria": r.get("categoria"),
            "documento": r.get("documento", {}),
            "paziente": r.get("paziente", {}),
            "riassunto": r.get("riassunto"),
            "diagnosi_principali": r.get("diagnosi_principali", []),
            "farmaci_prescritti": r.get("farmaci_prescritti", []),
            "terapie": r.get("terapie", []),
            "esami_laboratorio": r.get("esami_laboratorio", []),
            "esami_diagnostica": r.get("esami_diagnostica", []),
            "anamnesi": r.get("anamnesi", []),
            "date_rilevanti": r.get("date_rilevanti", []),
            "medico_ente": r.get("medico_ente", ""),
            "note_rilevanti": r.get("note_rilevanti", []),
        })

    # Spezza in blocchi se troppo grande
    blob = json.dumps(compact, ensure_ascii=False)
    parts = [blob[i:i+180000] for i in range(0, len(blob), 180000)]

    answers = []
    for i, part in enumerate(parts, 1):
        user = QUERY_USER_TMPL.format(question=question, records_json=part)
        ans = call_ai_text(model, QUERY_SYSTEM, user, max_out=1200)
        answers.append(f"[Blocco {i}/{len(parts)}]\n{ans}")

    final_answer = "\n\n".join(answers)
    add_query_history(question, final_answer)
    return final_answer


# =========================
# Main
# =========================
def main():
    parser = argparse.ArgumentParser(description="Analisi PDF clinici + Q&A")
    parser.add_argument("--dir", default="downloaded_pdfs", help="Cartella PDF da analizzare")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Modello (default: {DEFAULT_MODEL})",
    )
    parser.add_argument("--from", dest="date_from", default=None, help="Filtro data iniziale (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", default=None, help="Filtro data finale (YYYY-MM-DD)")
    parser.add_argument("--category", default=None, help="Categoria attesa (es. cardiologia, allergologia...)")
    parser.add_argument("--kw", nargs="*", default=[], help="Parole-chiave sul nome file (facoltative)")
    parser.add_argument("--ask", default=None, help="Domanda diretta sui risultati già analizzati (Q&A)")
    parser.add_argument(
        "--patient-id",
        default=None,
        help="Limita analisi e Q&A al paziente indicato (usa cartella personale).",
    )
    parser.add_argument(
        "--ocr-lang",
        default="ita+eng",
        help="Codice lingua Tesseract da usare per l'OCR (es. ita, ita+eng)",
    )
    parser.add_argument(
        "--ocr-psm",
        default=DEFAULT_OCR_PSM or "6",
        help="Modalità di segmentazione pagina Tesseract (--psm). Default: 6",
    )
    parser.add_argument(
        "--ocr-zoom",
        type=float,
        default=DEFAULT_OCR_ZOOM,
        help="Fattore zoom PyMuPDF per l'OCR (3.0 circa 216 DPI).",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Disattiva l'OCR (sconsigliato se i PDF sono scansioni).",
    )
    parser.add_argument(
        "--dump-text",
        action="store_true",
        help="Salva il testo estratto (post-OCR) in file .txt per debug",
    )
    parser.add_argument(
        "--dump-dir",
        default=None,
        help="Cartella di destinazione per i .txt (default: analysis_results/_raw_text)",
    )
    parser.add_argument(
        "--vision-only",
        action="store_true",
        help="Invia i PDF direttamente al modello Vision (salta estrazione testo locale e OCR).",
    )
    parser.add_argument(
        "--sync-patients",
        action="store_true",
        help="Rigenera le schede paziente a partire dai JSON gia presenti e termina.",
    )
    parser.add_argument(
        "--authorize-patient",
        action="append",
        default=[],
        help="Autorizza l'ID paziente indicato (puo essere passato piu volte).",
    )
    parser.add_argument(
        "--list-pending-patients",
        action="store_true",
        help="Elenca gli ID paziente in attesa di autorizzazione.",
    )
    parser.add_argument(
        "--auto-authorize",
        action="store_true",
        help="Autorizza automaticamente tutti i nuovi pazienti incontrati durante l'analisi.",
    )
    args = parser.parse_args()

    model = args.model
    use_ocr = (not args.no_ocr) and (not args.vision_only)

    if args.authorize_patient:
        pending_meta = get_pending_patients()
        for raw_id in args.authorize_patient:
            pid = (raw_id or '').strip()
            if not pid:
                continue
            authorize_patient(pid, pending_meta.get(pid, {}))
            log(f'[INFO] Paziente autorizzato: {pid}')
        if not (args.sync_patients or args.ask or args.auto_authorize or args.list_pending_patients or args.dir != 'downloaded_pdfs'):
            return

    if args.list_pending_patients:
        pending = get_pending_patients()
        if not pending:
            print('[INFO] Nessun paziente in attesa di autorizzazione.')
        else:
            print('[INFO] Pazienti in attesa di autorizzazione:')
            for pid, meta in pending.items():
                nome = meta.get('nome') or '-'
                cf = meta.get('codice_fiscale') or '-'
                source = meta.get('analysis_json') or '-'
                last_seen = meta.get('last_seen') or '-'
                print(f"  - {pid} | nome: {nome} | CF: {cf} | ultimo file: {source} | last_seen: {last_seen}")
        return

    if args.sync_patients:
        updated = sync_patient_profiles()
        log(f"[INFO] Profili paziente aggiornati: {updated}")
        return

    # Modalità Q&A
    if args.ask:
        log("[Q&A] Modalità attiva (usa i JSON in analysis_results/)")
        ans = qa_on_results(model, args.ask, patient_id=args.patient_id)
        print("\n" + "=" * 80 + "\nRISPOSTA:\n" + ans + "\n" + "=" * 80)
        return

    # Modalità analisi
    in_dir = os.path.abspath(args.dir)
    if args.patient_id:
        if not is_patient_authorized(args.patient_id):
            raise RuntimeError(f"Paziente non autorizzato: {args.patient_id}")
        patient_docs_dir = get_patient_documents_dir(args.patient_id, ensure=False)
        if os.path.isdir(patient_docs_dir):
            in_dir = patient_docs_dir
        else:
            raise RuntimeError(
                f"Nessun documento trovato per il paziente {args.patient_id}. Atteso in {patient_docs_dir}"
            )

    if not os.path.isdir(in_dir):
        raise RuntimeError(f"Cartella non trovata: {in_dir}")

    fpaths = []
    for ext in ("*.pdf", "*.PDF"):
        fpaths.extend(glob.glob(os.path.join(in_dir, ext)))
    fpaths = sorted(set(fpaths))

    if not fpaths:
        log(f"Nessun PDF trovato in: {in_dir}")
        return

    results_root = os.path.join(RESULTS_DIR, args.patient_id) if args.patient_id else RESULTS_DIR
    os.makedirs(results_root, exist_ok=True)
    raw_text_dir = args.dump_dir or os.path.join(results_root, "_raw_text")
    authorized_index = build_authorized_index()

    log(f"Trovati {len(fpaths)} PDF da analizzare in: {in_dir}")
    if use_ocr:
        log(
            "OCR abilitato "
            f"(lingua: {args.ocr_lang}, psm: {args.ocr_psm}, zoom: {args.ocr_zoom})"
        )
    else:
        log("OCR disattivato (assicurati che i PDF contengano testo selezionabile).")
    if args.dump_text:
        log(f"Dump testo attivo (cartella: {raw_text_dir})")

    n_ok = n_skip = 0

    for fpath in tqdm(fpaths, desc="Analizzando", unit="pdf"):
        name = os.path.basename(fpath)

        # skip se esiste già un JSON con lo stesso nome
        out_json = os.path.join(results_root, os.path.splitext(name)[0] + ".json")
        if os.path.exists(out_json):
            log(f"⏭️  Saltato duplicato: {out_json}")
            n_skip += 1
            continue

        # filtri sul nome file (kw)
        if not keep_file(name, args.date_from, args.date_to, args.kw):
            log(f"⏭️  Escluso per keyword: {name}")
            n_skip += 1
            continue

        try:
            log(f"🩺 Analisi file: {name}")
            result = analyze_pdfs(
                model,
                fpath,
                use_ocr=use_ocr,
                ocr_lang=args.ocr_lang,
                ocr_zoom=args.ocr_zoom,
                ocr_psm=args.ocr_psm,
                dump_text=args.dump_text,
                raw_text_dir=raw_text_dir,
                vision_only=args.vision_only,
                vision_fallback=not args.vision_only,
            )

            patient_info = result.get("paziente") or {}
            fallback_name = os.path.splitext(name)[0]
            patient_id = compute_patient_id_for_result(patient_info, fallback_name)
            if args.auto_authorize and not is_patient_authorized(patient_id):
                authorize_patient(patient_id, {
                    'nome': patient_info.get('nome'),
                    'codice_fiscale': patient_info.get('codice_fiscale'),
                    'data_nascita': patient_info.get('data_nascita'),
                })
                log(f"[INFO] Paziente autorizzato automaticamente: {patient_id}")

            # filtri per categoria (se richiesta)
            if args.category:
                if result.get("categoria", "").lower() != args.category.lower():
                    log(f"⏭️  Escluso per categoria: {result.get('categoria')}")
                    n_skip += 1
                    continue

            # filtri per data: se presenti date_rilevanti nel JSON
            def in_range(dates: List[str]) -> bool:
                if not (args.date_from or args.date_to):
                    return True
                ok = False
                for ds in dates:
                    iso_hit = extract_iso_date(ds or "")
                    if iso_hit:
                        dt = iso_hit[0]
                    elif looks_like_date((ds or "").split(" - ", 1)[0]):
                        dt = normalize_date_token((ds or "").split(" - ", 1)[0])
                    else:
                        continue
                    if args.date_from and dt < args.date_from:
                        continue
                    if args.date_to and dt > args.date_to:
                        continue
                    ok = True
                return ok if (args.date_from or args.date_to) else True

            if not in_range(result.get("date_rilevanti", [])):
                log(f"⏭️  Escluso per intervallo date.")
                n_skip += 1
                continue

            forced_id = args.patient_id or patient_id
            meta = authorized_index.get(forced_id)
            if meta:
                result.setdefault("paziente", {})
                for key in ("nome", "codice_fiscale", "data_nascita", "email"):
                    value = meta.get(key)
                    if value and not result["paziente"].get(key):
                        result["paziente"][key] = value

            safe_write_json(out_json, result)
            update_patient_profile(
                result,
                out_json,
                forced_patient_id=forced_id,
                forced_patient_meta=meta,
            )
            n_ok += 1

        except Exception as e:
            log(f"❌ Errore su {name}: {e}")

    log(f"✅ Analisi completata. Totale file analizzati: {n_ok}. Saltati: {n_skip}.")
    log(f"📁 Risultati salvati in: {RESULTS_DIR}")
    log("Suggerimento: per domande dirette usa --ask \"<domanda>\"")


if __name__ == "__main__":
    main()
