# Guida al Deploy su Railway

Questa guida ti aiuterà a mettere online il backend Medical AI su Railway.

## 📋 Prerequisiti

1. Account Railway (gratuito su [railway.app](https://railway.app))
2. Account OpenAI con API key
3. Progetto Supabase configurato
4. (Opzionale) Account SMTP per le email

## 🚀 Passi per il Deploy

### 1. Preparazione del Repository

Assicurati che tutti i file siano committati:
```bash
git add .
git commit -m "Preparazione per deploy Railway"
git push
```

### 2. Creare un Nuovo Progetto su Railway

1. Vai su [railway.app](https://railway.app) e accedi
2. Clicca su "New Project"
3. Seleziona "Deploy from GitHub repo" e scegli il tuo repository
4. Railway rileverà automaticamente il progetto Python

### 3. Configurare le Variabili d'Ambiente

Nella dashboard Railway, vai su "Variables" e aggiungi tutte le variabili necessarie:

#### **Variabili Obbligatorie:**

```bash
OPENAI_API_KEY=sk-...                    # La tua OpenAI API key
SUPABASE_URL=https://xxx.supabase.co     # URL del tuo progetto Supabase
SUPABASE_SERVICE_KEY=eyJ...              # Service role key di Supabase
SUPABASE_BUCKET=patient-documents        # Nome del bucket (crealo prima in Supabase)
```

#### **Variabili Opzionali:**

```bash
OPENAI_DEFAULT_MODEL=gpt-4o-mini         # Modello OpenAI (default: gpt-4o-mini)
CORS_ORIGINS=https://tuodominio.com      # Domini frontend (se diverso da Railway)
SMTP_HOST=smtp.gmail.com                 # Per le email
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@gmail.com
```

**Nota:** Railway imposta automaticamente `PORT`, non sovrascriverlo.

### 4. Configurare Supabase Storage

1. Vai nel tuo progetto Supabase
2. Vai su "Storage" → "Buckets"
3. Crea un nuovo bucket chiamato `patient-documents` (o il nome che hai scelto)
4. Imposta le policy di accesso secondo le tue esigenze di sicurezza

### 5. Deploy Automatico

Railway rileverà automaticamente:
- Il `Procfile` nella cartella `backend/`
- Il file `railway.json` nella root
- Le dipendenze da `backend/requirements.txt`

Il deploy partirà automaticamente. Puoi monitorare i log nella dashboard Railway.

### 6. Ottenere l'URL del Backend

Dopo il deploy, Railway ti fornirà un URL tipo:
```
https://your-backend-name.railway.app
```

Copia questo URL.

### 7. Configurare il Frontend

1. Apri `frontend/config.js`
2. Imposta l'URL del backend:

```javascript
window.__BACKEND_URL__ = "https://your-backend-name.railway.app";
```

3. Deploya il frontend (puoi usare Railway, Vercel, Netlify, o qualsiasi altro hosting statico)

### 8. Configurare CORS (se necessario)

Se il frontend è su un dominio diverso da Railway, aggiungi la variabile d'ambiente:

```bash
CORS_ORIGINS=https://tuodominio.com,https://www.tuodominio.com
```

## 🔍 Verifica del Deploy

1. Visita `https://your-backend-name.railway.app/` - dovresti vedere:
   ```json
   {"message": "Backend Medical AI attivo"}
   ```

2. Controlla i log in Railway per eventuali errori

3. Testa un endpoint:
   ```bash
   curl https://your-backend-name.railway.app/patients
   ```

## ⚠️ Note Importanti

### Chrome Driver per Download Automatico

La funzionalità di download automatico da FSE richiede Chrome/Chromium. Su Railway potresti dover:

1. Aggiungere buildpack per Chrome:
   - Railway usa Nixpacks che dovrebbe gestirlo automaticamente
   - Se non funziona, considera di disabilitare questa feature o usare un servizio esterno

2. Variabili d'ambiente per Chrome:
   ```bash
   CHROME_BIN=/usr/bin/chromium-browser
   DISPLAY=:99
   ```

### Storage Locale

I file PDF vengono salvati localmente in `downloaded_pdfs/` e `analysis_results/`. Su Railway questi vengono persi al riavvio. Assicurati che:
- I documenti importanti siano caricati su Supabase Storage
- I risultati delle analisi siano sincronizzati con Supabase

### Limitazioni Railway Free Tier

- 500 ore/mese gratuite
- 5$ di credito mensile
- Considera di aggiornare se hai molto traffico

## 🐛 Troubleshooting

### Errore: "Supabase configuration missing"
- Verifica che `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` siano impostati correttamente

### Errore: "OPENAI_API_KEY mancante"
- Controlla che la variabile sia impostata in Railway (case-sensitive)

### CORS errors nel frontend
- Verifica che `CORS_ORIGINS` includa l'URL del tuo frontend
- Controlla che il regex in `CORS_ORIGIN_REGEX` sia corretto

### Port already in use
- Non impostare `PORT` manualmente, Railway lo gestisce automaticamente

## 📚 Risorse Utili

- [Documentazione Railway](https://docs.railway.app)
- [Railway Discord](https://discord.gg/railway)
- [Supabase Storage Docs](https://supabase.com/docs/guides/storage)

## ✅ Checklist Pre-Deploy

- [ ] Variabili d'ambiente configurate in Railway
- [ ] Bucket Supabase creato e configurato
- [ ] `frontend/config.js` aggiornato con URL backend
- [ ] Test locale del backend funzionante
- [ ] Frontend configurato per produzione
- [ ] CORS configurato correttamente

Buon deploy! 🚀

