# Medical AI Backend

FastAPI backend that manages the full pipeline for medical PDFs:
- downloads documents from local folders or authenticated portals,
- extracts text (OCR first, native text if available),
- classifies content with GPT-5 and saves structured JSON in `analysis_results/`,
- builds patient profiles under `downloaded_pdfs/patients/` with strict authorization controls,
- exposes REST endpoints for downloads, analyses, Q&A, patient registries, invites and access requests.

## Prerequisites
- Python 3.10 or newer
- Valid OpenAI API key (`OPENAI_API_KEY` in environment or `.env`)
- Tesseract OCR (optional but recommended for scanned PDFs). On Windows set `TESSERACT_CMD` with the full path to `tesseract.exe`.

## Setup
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # oppure: cp .env.example .env
# Aggiorna .env con OPENAI_API_KEY (e TESSERACT_CMD se non presente nel PATH)
# (Opzionale) configura SMTP_HOST/PORT/USERNAME/PASSWORD/SMTP_FROM per inviare le credenziali via email
```

## Running the API
```bash
uvicorn main:app --reload
```
Interactive docs: http://127.0.0.1:8000/docs

Key folders created at runtime:
- `downloaded_pdfs/` - raw downloads (shared staging area)
- `analysis_results/` - AI outputs (`*.json`) and optional `_raw_text/` OCR dumps
- `downloaded_pdfs/patients/` - per patient profiles, copied PDFs, registries (`_authorized.json`, `_pending.json`, `_invites.json`, `_access_requests.json`)

## CLI helper (`analyze_pdf_ai.py`)
This script powers the `/analyze` endpoint and can be used manually:
```bash
# Analizza tutti i PDF nella cartella indicata
python analyze_pdf_ai.py --dir downloaded_pdfs --auto-authorize

# Q&A sui risultati già elaborati
python analyze_pdf_ai.py --ask "Quali farmaci sono stati prescritti nel 2025?"

# Gestione pazienti da CLI
python analyze_pdf_ai.py --list-pending-patients
python analyze_pdf_ai.py --authorize-patient <patient_id>
python analyze_pdf_ai.py --sync-patients   # rigenera le schede dai JSON esistenti
```
Main flags:
- `--auto-authorize` autorizza automaticamente i nuovi pazienti trovati durante l'analisi.
- `--authorize-patient <id>` (ripetibile) sposta un paziente da `_pending` a `_authorized` usando i metadati raccolti.
- `--list-pending-patients` elenca chi necessita di approvazione.
- `--sync-patients` ricostruisce i profili JSON/TXT partendo dai risultati presenti in `analysis_results/`.

## REST endpoints (principali)
- `POST /auth/register` – associa email/password a un paziente già autorizzato.
- `POST /auth/login` / `POST /auth/logout` / `GET /auth/me` – gestione sessioni Bearer per portale paziente.
- `GET /patients/{patient_id}` e `GET /patients/{patient_id}/documents` – profilo e documenti indicizzati (richiedono token valido).
- `POST /patients/{patient_id}/documents/upload` – carica PDF direttamente nella cartella personale.
- `POST /patients/{patient_id}/analyze` – esegue l'analisi dei PDF del profilo (OCR attivo di default).
- `POST /patients/{patient_id}/ask` e `GET /patients/{patient_id}/analysis-results` – Q&A e consultazione risultati limitati al paziente.
- `POST /patients/{patient_id}/invite` / `GET /patients/{patient_id}/invites` – gestione inviti e link di condivisione.
- `POST /access/request`, `GET /access/requests`, `POST /access/requests/{request_id}/status` – workflow di richiesta/autorizzazione per i medici; `POST /access/claim` consuma un token d'invito.
- Endpoint amministrativi ancora disponibili: `GET /patients`, `GET /patients/pending`, `POST /patients/{patient_id}/authorize`, `GET /analysis-results`, `GET /query-history`, `GET /download`, `GET /downloaded-pdfs-list`.

## Authorization flow
1. Durante l'analisi ogni documento viene assegnato a un `patient_id` (codice fiscale se presente altrimenti slug di nome+data di nascita o fallback dal file).
2. Se il paziente non è autorizzato, i metadati finiscono in `_pending.json` e il profilo non viene creato. Il log CLI suggerisce il comando per autorizzarlo.
3. Dopo l'autorizzazione (`--authorize-patient` o endpoint API) l'analisi successiva popola automaticamente la cartella del paziente con:
   - `profile.json` (strutturato), `profile.txt` (riassunto testuale), PDF originali deduplicati, aggregati per specialità (elenco completo in `medical_taxonomy.py`).
4. Inviti e richieste d'accesso permettono a un paziente di condividere temporaneamente i propri documenti con un medico mantenendo il controllo.

## OCR and Tesseract
- OCR è attivo di default sia da CLI sia da API (`ocr=true`). Serve `pytesseract` e un'installazione di Tesseract.
- Su Windows imposta `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` nel `.env` o nel sistema.
- I testi estratti per debug possono essere salvati con `dump_text=true` (`analysis_results/_raw_text/`).

## Next steps
- Integrare il frontend per consentire al paziente di autenticarsi, gestire inviti e interrogare l'AI sui propri documenti.
- Aggiungere audit logging, cifratura e storage esterno prima di mettere in produzione dati reali.
