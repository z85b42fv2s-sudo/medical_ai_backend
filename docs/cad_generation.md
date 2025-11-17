# CAD: come funziona l'endpoint `/cad/generate`

Questo backend espone l'endpoint `POST /cad/generate` per trasformare un'immagine raster (foto o disegno) in un file DXF scaricabile. Di seguito una panoramica operativa dell'intero flusso e di come personalizzarlo.

## Flusso end-to-end
1. **Upload**: il client invia un file immagine (PNG/JPEG) come `UploadFile` al percorso `/cad/generate` insieme ai parametri di tuning facoltativi.
2. **Validazioni iniziali**: l'API verifica che il file non sia vuoto e normalizza il nome del layer DXF (default `OUTLINE`).
3. **Pipeline di estrazione** (`backend/cad_generator.py`):
   - L'immagine viene caricata in scala di grigi con OpenCV.
   - Si applica un blur gaussiano, quindi l'algoritmo Canny per estrarre i contorni.
   - Ogni contorno viene semplificato con `approxPolyDP` per ottenere polilinee più pulite.
4. **Scrittura DXF**: le polilinee ottenute vengono aggiunte al modello DXF in un layer dedicato e salvate in un file temporaneo.
5. **Risposta**: l'API restituisce il DXF come `FileResponse`, impostando header con il numero di polilinee trovate e il layer usato. Il file temporaneo viene eliminato in background dopo il download.

## Parametri disponibili
- `layer` (query, stringa): nome del layer DXF in cui inserire le polilinee. Default: `OUTLINE`.
- `canny_threshold1` (query, int): primo threshold per Canny (0–1000). Default: `50`.
- `canny_threshold2` (query, int): secondo threshold per Canny (0–2000). Default: `150`.
- `approx_epsilon` (query, float): tolleranza di semplificazione contorni in pixel (0.1–50). Default: `2.0`.

## Esempio di chiamata con `curl`
```bash
curl -X POST "http://localhost:8000/cad/generate?layer=OUTLINE&canny_threshold1=50&canny_threshold2=150&approx_epsilon=2.0" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@./esempio_planimetria.png" \
  -o output.dxf
```
Il DXF scaricato conterrà un layer `OUTLINE` popolato con le polilinee chiuse derivate dai contorni presenti nell'immagine.

## Dove avviene cosa
- **API FastAPI**: `backend/main.py`, funzione `generate_cad_from_raster` (riga ~1186) gestisce upload, parametri e risposta.
- **Logica CAD**: `backend/cad_generator.py` contiene le funzioni di parsing dell'immagine, estrazione contorni e scrittura DXF.
- **Dipendenze**: elencate in `backend/requirements.txt` (`opencv-python-headless`, `numpy`, `ezdxf`).

## Errori comuni
- "File vuoto" o "Immagine non valida": l'immagine non è leggibile da OpenCV o è vuota.
- "Nessun contorno rilevato nell'immagine": i parametri Canny sono troppo conservativi oppure l'immagine è troppo uniforme; prova ad abbassare i threshold o ad aumentare il contrasto.

## Note progettuali
- Le polilinee sono chiuse e scritte come `LWPolyline` per compatibilità con AutoCAD e la maggior parte dei viewer DXF.
- Il file DXF è generato in un file temporaneo e cancellato automaticamente dopo l'invio della risposta.
- Il layer viene creato se non esiste già nel documento DXF.

## Come provarlo in locale
1. **Prepara l'ambiente**:
   - Copia `backend/env.example` in `backend/.env` e compila almeno le variabili Supabase (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`) così da poter creare una sessione di test.
   - Crea e attiva un virtualenv, poi installa le dipendenze: `python -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt`.
2. **Avvia l'API**: dalla root del repo esegui `uvicorn backend.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000`.
3. **Ottieni un token di sessione** (serve l'accesso a Supabase):
   ```bash
   python - <<'PY'
   from backend.patient_profiles import authorize_patient, create_session

   patient_id = "cad-test"
   authorize_patient(patient_id, {"email": "cad-test@example.com"})
   session = create_session(patient_id)
   print(session["token"])
   PY
   ```
4. **Esegui la chiamata di prova** con un'immagine qualsiasi (PNG/JPEG) e il token ottenuto:
   ```bash
   curl -X POST "http://localhost:8000/cad/generate?layer=OUTLINE&canny_threshold1=50&canny_threshold2=150&approx_epsilon=2.0" \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@./esempio_planimetria.png" \
     -o output.dxf -D -
   ```
   Nell'output degli header dovresti vedere `X-Polylines-Count` e `X-Layer-Name`; il file `output.dxf` conterrà le polilinee vettorializzate.
