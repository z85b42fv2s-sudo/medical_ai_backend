# -*- coding: utf-8 -*-
"""
main.py — Backend per Medical AI
Gestisce:
- Download dei PDF (via download_pdfs.py)
- Analisi PDF con AI (via analyze_pdf_ai.py)
- Q&A sui risultati analizzati
- API per frontend
"""

import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

# === Import dei moduli locali (NON TOCCARE I FILE!) ===
from download_pdfs import scan_local_folder, is_url, scan_page, build_chrome_driver
from analyze_pdf_ai import analyze_pdfs, qa_on_results
from typing import List
import glob
import time


# === Inizializzazione FastAPI ===
app = FastAPI(title="Medical AI Backend", version="1.0")

# === CORS: permette al frontend di comunicare ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # per test locali, puoi limitare poi a ["http://127.0.0.1:5500"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Endpoint di test ===
@app.get("/")
def root():
    return {"message": "✅ Backend Medical AI attivo e funzionante!"}


# === ENDPOINT: Download PDF ===
@app.get("/download")
def download_route(source: str = Query(..., description="Percorso locale o URL da cui scaricare PDF")):
    """
    Gestisce il download locale o da URL/SPID dei PDF.
    """
    try:
        start = time.time()
        result = None

        if not source:
            return {"status": "error", "message": "Nessun percorso o URL fornito"}

        if is_url(source):
            # --- Download da URL ---
            driver, wait = build_chrome_driver()
            driver.get(source)
            print("🔐 Esegui login SPID nella finestra del browser se richiesto...")
            input("Premi INVIO nel terminale dopo aver completato il login ed essere nella pagina corretta...")
            result = scan_page(driver, wait, source, max_depth=2)
            driver.quit()
        else:
            # --- Download da cartella locale ---
            folder = os.path.abspath(source)
            out_dir = os.path.join(os.getcwd(), "downloaded_pdfs")
            result = scan_local_folder(folder, out_dir)

        elapsed = time.time() - start
        return {"status": "ok", "result": result, "elapsed_sec": round(elapsed, 1)}

    except Exception as e:
        return {"status": "error", "message": str(e)}



# === ENDPOINT: Analizza PDF ===
@app.get("/analyze")
def analyze_route(
    folder: str = Query("downloaded_pdfs", description="Cartella con i PDF da analizzare"),
):
    """
    Analizza tutti i PDF nella cartella indicata usando analyze_pdf_ai.py
    """
    try:
        folder = os.path.abspath(folder)
        if not os.path.exists(folder):
            return {"status": "error", "message": f"Cartella non trovata: {folder}"}

        files = [f for f in glob.glob(os.path.join(folder, "*.pdf"))]
        if not files:
            return {"status": "error", "message": f"Nessun PDF trovato in {folder}"}

        analyzed = []
        for fpath in files:
            result = analyze_pdfs("gpt-5", fpath)
            analyzed.append(result)

        return {"status": "ok", "count": len(analyzed), "results": analyzed}

    except Exception as e:
        return {"status": "error", "message": str(e)}



# === ENDPOINT: Domande all'AI (Q&A) ===
@app.get("/ask-ai")
def ask_ai(question: str = Query(..., description="Domanda clinica da porre all’AI")):
    """
    Q&A basato sui JSON generati dalle analisi dei PDF.
    """
    try:
        answer = qa_on_results("gpt-5", question)
        return {"status": "success", "question": question, "answer": answer}
    except Exception as e:
        return {"status": "error", "message": str(e)}



# === ENDPOINT: Lista PDF scaricati ===
@app.get("/downloaded-pdfs-list")
def downloaded_pdfs_list():
    """
    Restituisce la lista dei PDF presenti in ./downloaded_pdfs
    per permettere al frontend di mostrarli e contarli.
    """
    base_dir = os.getcwd()
    download_dir = os.path.join(base_dir, "downloaded_pdfs")

    if not os.path.exists(download_dir):
        return {"files": [], "count": 0, "folder": download_dir}

    # Prende solo estensioni .pdf / .PDF
    files: List[str] = []
    for ext in ("*.pdf", "*.PDF"):
        files.extend([
            os.path.basename(p)
            for p in glob.glob(os.path.join(download_dir, ext))
        ])

    files = sorted(set(files))
    return {"files": files, "count": len(files), "folder": download_dir}



# === AVVIO MANUALE ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
