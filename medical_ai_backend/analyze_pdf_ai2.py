# -*- coding: utf-8 -*-
"""
Analisi clinica dei PDF + Q&A sui risultati
- Estrae testo dai PDF (PyMuPDF/fitz)
- Genera JSON strutturati per ogni documento in analysis_results/
- Modalità Q&A per interrogare i JSON già prodotti
Requisiti:
  pip install pymupdf python-dotenv openai==1.* tqdm
Ambiente:
  Variabile OPENAI_API_KEY impostata (o .env con OPENAI_API_KEY=...)
"""

import os
import re
import json
import time
import glob
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

import fitz  # PyMuPDF
from dotenv import load_dotenv
from tqdm import tqdm
from openai import OpenAI

# =========================
# Config di base
# =========================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY mancante. Impostalo nell'ambiente o nel file .env")

client = OpenAI(api_key=OPENAI_API_KEY)

DEFAULT_MODEL = "gpt-5"
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

def load_all_results() -> List[Dict[str, Any]]:
    items = []
    for fp in glob.glob(os.path.join(RESULTS_DIR, "*.json")):
        if os.path.basename(fp) == os.path.basename(QUERY_HISTORY):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                items.append(json.load(f))
        except Exception:
            continue
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

def looks_like_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

# =========================
# Estrazione testo dai PDF
# =========================
def extract_text_pdf(path: str, max_chars: int = 150000) -> str:
    text = []
    with fitz.open(path) as doc:
        for page in doc:
            text.append(page.get_text())
    joined = "\n".join(text).strip()
    return joined[:max_chars]

def split_chunks(text: str, max_len: int = 7000) -> List[str]:
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
# AI PROMPTS
# =========================
ANALYSIS_SYSTEM = (
    "Sei un assistente medico che estrae informazioni cliniche strutturate da documenti PDF. "
    "Restituisci sempre un JSON rigoroso e ben formato."
)

ANALYSIS_USER_TMPL = """Analizza il seguente testo clinico. Restituisci SOLO un JSON valido con questa struttura:

{{
  "categoria": "<una tra cardiologia, ortopedia, oncologia, dermatologia, gastroenterologia, neurologia, ginecologia, nefrologia, pneumologia, ematologia, endocrinologia, infettivologia, urologia, o 'altro'>",
  "riassunto": "<massimo 6-8 frasi, preciso e clinico>",
  "diagnosi_principali": ["..."],
  "farmaci_prescritti": ["<nome, dosaggio, posologia>"],
  "esami_principali": ["<nome esame: valore (unità)>"],
  "date_rilevanti": ["YYYY-MM-DD - descrizione"],
  "medico_ente": "<se presente>",
  "note_rilevanti": ["..."]
}}

Testo (chunk {i}/{n}) del documento {doc_name}:

{chunk_text}
"""

QUERY_SYSTEM = (
    "Sei un assistente che risponde a domande sui dati clinici estratti dai PDF. "
    "Usa solo le informazioni presenti nei record forniti."
)

QUERY_USER_TMPL = """Hai una lista di record clinici in JSON (uno per documento). Rispondi alla domanda in modo accurato.

DOMANDA: {question}

RECORD_CLINICI (JSON):
{records_json}

Formato di risposta:
- Testo chiaro e conciso
- Se utile, una tabella con dati (es. data, categoria, diagnosi, farmaco, medico)
"""

# =========================
# Funzioni AI
# =========================
def call_ai_json(model: str, system: str, user: str, max_out: int = 1200) -> Dict[str, Any]:
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        max_output_tokens=max_out,
    )
    txt = resp.output_text
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    raise RuntimeError("AI: impossibile decodificare JSON.")

def call_ai_text(model: str, system: str, user: str, max_out: int = 1200) -> str:
    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_output_tokens=max_out,
    )
    return resp.output_text.strip()

# =========================
# Analisi PDF
# =========================
def analyze_pdfs(model: str, fpath: str) -> Dict[str, Any]:
    name = os.path.basename(fpath)
    text = extract_text_pdf(fpath)
    chunks = split_chunks(text)
    results = []

    for i, chunk in enumerate(chunks, 1):
        prompt = ANALYSIS_USER_TMPL.format(i=i, n=len(chunks), doc_name=name, chunk_text=chunk)
        try:
            out = call_ai_json(model, ANALYSIS_SYSTEM, prompt, max_out=1000)
            results.append(out)
        except Exception as e:
            results.append({
                "categoria": "altro",
                "riassunto": "",
                "diagnosi_principali": [],
                "farmaci_prescritti": [],
                "esami_principali": [],
                "date_rilevanti": [],
                "medico_ente": "",
                "note_rilevanti": [f"Errore AI su chunk {i}: {e}"],
            })

    merged = {
        "file": name,
        "path": fpath,
        "categoria": "altro",
        "riassunto": "",
        "diagnosi_principali": [],
        "farmaci_prescritti": [],
        "esami_principali": [],
        "date_rilevanti": [],
        "medico_ente": "",
        "note_rilevanti": [],
    }

    def extend_list(key: str):
        for r in results:
            if isinstance(r.get(key), list):
                for x in r[key]:
                    if x and x not in merged[key]:
                        merged[key].append(x)

    cats = [r.get("categoria", "altro") for r in results]
    if cats:
        best = max(set(cats), key=cats.count)
        merged["categoria"] = best or "altro"

    summaries = [r.get("riassunto", "") for r in results]
    merged["riassunto"] = max(summaries, key=len, default="").strip()

    for k in ["diagnosi_principali", "farmaci_prescritti", "esami_principali", "date_rilevanti", "note_rilevanti"]:
        extend_list(k)

    for r in results:
        me = r.get("medico_ente", "")
        if me:
            merged["medico_ente"] = me
            break

    norm_dates = []
    for d in merged["date_rilevanti"]:
        parts = d.split(" - ", 1)
        if parts and looks_like_date(parts[0]):
            norm_dates.append(d)
        else:
            m = re.search(r"\d{4}-\d{2}-\d{2}", d)
            if m:
                rest = d.replace(m.group(0), "").strip(" -:")
                norm_dates.append(f"{m.group(0)} - {rest or 'evento'}")
    merged["date_rilevanti"] = list(dict.fromkeys(norm_dates))

    return merged

# =========================
# Q&A sui risultati
# =========================
def qa_on_results(model: str, question: str) -> str:
    records = load_all_results()
    # Normalizza: assicura che ogni record sia un dict singolo
flat_records = []
for r in records:
    if isinstance(r, list):
        flat_records.extend(r)
    elif isinstance(r, dict):
        flat_records.append(r)
records = flat_records

    if not records:
        return "Non ci sono risultati analizzati in 'analysis_results/'. Esegui prima l'analisi dei PDF."

    compact = []
    for r in records:
        compact.append({
            "file": r.get("file"),
            "categoria": r.get("categoria"),
            "riassunto": r.get("riassunto"),
            "diagnosi_principali": r.get("diagnosi_principali", []),
            "farmaci_prescritti": r.get("farmaci_prescritti", []),
            "esami_principali": r.get("esami_principali", []),
            "date_rilevanti": r.get("date_rilevanti", []),
            "medico_ente": r.get("medico_ente", ""),
            "note_rilevanti": r.get("note_rilevanti", []),
        })

    blob = json.dumps(compact, ensure_ascii=False)
    parts = [blob[i:i + 180000] for i in range(0, len(blob), 180000)]

    answers = []
    for i, part in enumerate(parts, 1):
        user = QUERY_USER_TMPL.format(question=question, records_json=part)
        ans = call_ai_text(model, QUERY_SYSTEM, user, max_out=1200)
        answers.append(f"[Blocco {i}/{len(parts)}]\n{ans}")

    final_answer = "\n\n".join(answers)
    add_query_history(question, final_answer)
    return final_answer

# =========================
# Main CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Analisi PDF clinici + Q&A")
    parser.add_argument("--dir", default="downloaded_pdfs", help="Cartella PDF da analizzare")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modello (default: gpt-5)")
    parser.add_argument("--ask", default=None, help="Domanda diretta sui risultati già analizzati (Q&A)")
    args = parser.parse_args()

    model = args.model

    if args.ask:
        log("🧠 Modalità Q&A attiva")
        ans = qa_on_results(model, args.ask)
        print("\n" + "=" * 80 + "\nRISPOSTA:\n" + ans + "\n" + "=" * 80)
        return

    in_dir = os.path.abspath(args.dir)
    if not os.path.isdir(in_dir):
        raise RuntimeError(f"Cartella non trovata: {in_dir}")

    fpaths = sorted(set(glob.glob(os.path.join(in_dir, "*.pdf"))))
    if not fpaths:
        log(f"Nessun PDF trovato in: {in_dir}")
        return

    log(f"Trovati {len(fpaths)} PDF da analizzare in: {in_dir}")

    for fpath in tqdm(fpaths, desc="Analizzando", unit="pdf"):
        try:
            log(f"🩺 Analisi file: {os.path.basename(fpath)}")
            result = analyze_pdfs(model, fpath)
            out_json = os.path.join(RESULTS_DIR, os.path.splitext(os.path.basename(fpath))[0] + ".json")
            safe_write_json(out_json, result)
        except Exception as e:
            log(f"❌ Errore su {fpath}: {e}")

    log("✅ Analisi completata.")

if __name__ == "__main__":
    main()
