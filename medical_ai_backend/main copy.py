
import os
import json
import time
from collections import deque
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse

import pdfplumber
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing. Create a .env file (see .env.example).")

CRAWL_DEPTH = int(os.getenv("CRAWL_DEPTH", "2"))
MAX_PDF = int(os.getenv("MAX_PDF", "30"))

PDF_FOLDER = os.path.abspath(os.getenv("PDF_FOLDER", "pdfs"))
os.makedirs(PDF_FOLDER, exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI(title="Medical AI PDF Crawler & Analyzer", version="1.0.0")

# Allow local dev and simple frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeResult(BaseModel):
    file: str
    source_url: str
    analysis: Dict[str, Any]

class AnalyzeResponse(BaseModel):
    start_url: str
    total_pdf: int
    results: List[AnalyzeResult]
import pdfplumber

def extract_text(pdf_bytes, tmp_path: str = "tmp.pdf") -> str:
    """Extract text from a PDF byte stream using pdfplumber."""
    with open(tmp_path, "wb") as f:
        f.write(pdf_bytes)

    text = ""
    try:
        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                contenuto = page.extract_text()
                if contenuto:
                    text += contenuto + "\n"
    except Exception as e:
        print(f"Errore durante l'estrazione del testo: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    # Limita la lunghezza del testo (come nel codice originale)
    return text[:15000]



def crawl_for_pdfs(start_url: str, depth: int, max_pdf: int) -> List[Dict[str, str]]:
    """
    Breadth-first crawl starting at start_url, collecting PDF links up to 'depth' levels.
    Returns list of dicts: {"pdf_url": ..., "found_on": ...}
    """
    visited = set()
    found = []
    q = deque([(start_url, 0)])
    origin_host = urlparse(start_url).netloc

    while q and len(found) < max_pdf:
        url, lvl = q.popleft()
        if url in visited or lvl > depth:
            continue
        visited.add(url)

        try:
            resp = requests.get(url, timeout=15)
            if not resp.ok:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            continue

        # Collect PDFs
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full = urljoin(url, href)
            if href.lower().endswith(".pdf"):
                found.append({"pdf_url": full, "found_on": url})
                if len(found) >= max_pdf:
                    break

        # Enqueue internal links
        if lvl < depth:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                nxt = urljoin(url, href)
                # Only crawl within the same host
                if urlparse(nxt).netloc == origin_host and nxt not in visited:
                    q.append((nxt, lvl + 1))

    # Deduplicate by pdf_url while preserving first found_on
    seen = set()
    dedup = []
    for item in found:
        if item["pdf_url"] not in seen:
            seen.add(item["pdf_url"])
            dedup.append(item)
    return dedup

AI_PROMPT_TEMPLATE = """Sei un assistente medico. Leggi il seguente referto/Documento e restituisci SOLO un JSON valido con questo schema:
{
  "categoria": "specialità medica principale (es. Cardiologia, Ortopedia, Radiologia, Gastroenterologia, Neurologia, Dermatologia, Endocrinologia, Pneumologia, Nefrologia, Oncologia)",
  "parte_corpo": "organo o area (es. Cuore, Ginocchio, Colonna, Polmoni, Cervello, Fegato)",
  "riassunto": "sintesi clinica in max 3 frasi, chiara e non confidenziale"
}

Testo del documento:
{doc_text}
"""

def analyze_with_ai(text: str) -> Dict[str, Any]:
    prompt = AI_PROMPT_TEMPLATE.format(doc_text=text)
    try:
        res = client.chat.completions.create(
            model="gpt-5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = res.choices[0].message.content.strip()
        # Try to parse JSON; if fails, return raw content
        try:
            return json.loads(content)
        except Exception:
            return {"raw": content}
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
def health():
    return {"ok": True, "model": "gpt-5", "pdf_folder": PDF_FOLDER}

@app.get("/analyze_url", response_model=AnalyzeResponse)
def analyze_url(url: str = Query(..., description="Pagina di partenza da cui cercare PDFs"),
                depth: Optional[int] = Query(None, description="Profondità di crawl (default da .env)"),
                max_pdf: Optional[int] = Query(None, description="Numero massimo di PDF (default da .env)")):
    depth = int(depth if depth is not None else CRAWL_DEPTH)
    max_pdf = int(max_pdf if max_pdf is not None else MAX_PDF)

    pdf_links = crawl_for_pdfs(url, depth=depth, max_pdf=max_pdf)
    results: List[AnalyzeResult] = []

    for item in pdf_links:
        pdf_url = item["pdf_url"]
        source_page = item["found_on"]
        try:
            r = requests.get(pdf_url, timeout=30)
            if not r.ok or not r.content:
                continue

            # Save PDF locally
            fname = os.path.basename(urlparse(pdf_url).path) or f"doc_{int(time.time()*1000)}.pdf"
            fpath = os.path.join(PDF_FOLDER, fname)
            with open(fpath, "wb") as f:
                f.write(r.content)

            # Extract text and analyze
            text = extract_text(r.content)
            analysis = analyze_with_ai(text)

            results.append(AnalyzeResult(
                file=fname,
                source_url=pdf_url,
                analysis=analysis
            ))
        except Exception as e:
            results.append(AnalyzeResult(
                file="",
                source_url=pdf_url,
                analysis={"error": f"failed to process: {e}"}
            ))

    return AnalyzeResponse(
        start_url=url,
        total_pdf=len(results),
        results=results
    )
