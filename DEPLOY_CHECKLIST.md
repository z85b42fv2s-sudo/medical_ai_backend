# ✅ Checklist Deploy Railway

## Pre-Deploy

- [x] CORS configurato per Railway
- [x] Backend URL configurabile nel frontend
- [x] Modello OpenAI corretto (gpt-4o-mini invece di gpt-5)
- [x] Procfile creato
- [x] railway.json creato
- [x] File env.example creato
- [x] README_DEPLOY.md creato

## Setup Railway

### 1. Variabili d'Ambiente da Configurare

Vai su Railway Dashboard → Variables e aggiungi:

**OBBLIGATORIE:**
- [ ] `OPENAI_API_KEY` - La tua API key OpenAI
- [ ] `SUPABASE_URL` - URL del progetto Supabase
- [ ] `SUPABASE_SERVICE_KEY` - Service role key di Supabase
- [ ] `SUPABASE_BUCKET` - Nome bucket (default: `patient-documents`)

**OPZIONALI (ma consigliate):**
- [ ] `OPENAI_DEFAULT_MODEL` - Modello OpenAI (default: `gpt-4o-mini`)
- [ ] `SMTP_HOST` - Per le email
- [ ] `SMTP_PORT` - Porta SMTP (default: 587)
- [ ] `SMTP_USERNAME` - Username SMTP
- [ ] `SMTP_PASSWORD` - Password SMTP
- [ ] `SMTP_FROM` - Email mittente
- [ ] `CORS_ORIGINS` - Domini frontend (se diverso da Railway)

### 2. Supabase Setup

- [ ] Crea bucket `patient-documents` in Supabase Storage
- [ ] Configura le policy di accesso del bucket
- [ ] Verifica che `SUPABASE_SERVICE_KEY` abbia i permessi necessari

### 3. Deploy

- [ ] Connetti repository GitHub a Railway
- [ ] Railway rileverà automaticamente la configurazione
- [ ] Attendi il completamento del build
- [ ] Copia l'URL del backend (es: `https://xxx.railway.app`)

### 4. Frontend

- [ ] Apri `frontend/config.js`
- [ ] Imposta: `window.__BACKEND_URL__ = "https://tuo-backend.railway.app"`
- [ ] Deploya il frontend (Railway, Vercel, Netlify, ecc.)

### 5. Test

- [ ] Visita `https://tuo-backend.railway.app/` → dovrebbe rispondere `{"message": "Backend Medical AI attivo"}`
- [ ] Testa login dal frontend
- [ ] Verifica che i documenti vengano caricati correttamente
- [ ] Controlla i log in Railway per eventuali errori

## File Modificati

- ✅ `backend/main.py` - CORS e modello OpenAI
- ✅ `frontend/app.js` - URL backend configurabile
- ✅ `frontend/index.html` - Aggiunto config.js
- ✅ `frontend/config.js` - **NUOVO** - Configurazione frontend
- ✅ `backend/Procfile` - **NUOVO** - Comando avvio Railway
- ✅ `railway.json` - **NUOVO** - Configurazione Railway
- ✅ `backend/env.example` - **NUOVO** - Template variabili
- ✅ `README_DEPLOY.md` - **NUOVO** - Guida completa

## Comandi Utili

```bash
# Test locale del backend
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Verifica variabili d'ambiente
railway variables

# Visualizza log
railway logs
```

## Supporto

Se qualcosa non funziona:
1. Controlla i log in Railway Dashboard
2. Verifica che tutte le variabili d'ambiente siano impostate
3. Assicurati che il bucket Supabase esista
4. Controlla che il frontend punti all'URL corretto del backend

Buon deploy! 🚀

