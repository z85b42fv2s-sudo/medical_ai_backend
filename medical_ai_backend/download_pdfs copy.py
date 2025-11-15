import os
import time
import shutil
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# === CONFIGURAZIONE ===
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloaded_pdfs")
LOG_FILE = os.path.join(os.getcwd(), "log_download.txt")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def scrivi_log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")

# === SCANSIONE CARTELLA LOCALE (INCLUSE SOTTOCARTELLE) ===
def scan_local_folder(folder, out_dir):
    scrivi_log(f"📁 Scansione cartella: {folder}")
    if not os.path.isdir(folder):
        scrivi_log(f"❌ Cartella non trovata: {folder}")
        return

    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for root, _, files in os.walk(folder):
        for fn in files:
            if fn.lower().endswith(".pdf"):
                src = os.path.join(root, fn)
                dest = os.path.join(out_dir, fn)
                base, ext = os.path.splitext(fn)
                i = 1
                while os.path.exists(dest):
                    dest = os.path.join(out_dir, f"{base} ({i}){ext}")
                    i += 1
                try:
                    shutil.copy2(src, dest)
                    count += 1
                    scrivi_log(f"✅ Copiato: {dest}")
                except Exception as e:
                    scrivi_log(f"⚠️ Errore copiando {src}: {e}")

    scrivi_log(f"🏁 Scansione completata. {count} file PDF trovati e copiati in {out_dir}.")

# === CONFIGURAZIONE SELENIUM ===
def avvia_driver():
    options = Options()
    options.add_argument("--start-maximized")
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True
    }
    options.add_experimental_option("prefs", prefs)
    service = Service(os.path.join(os.getcwd(), "chromedriver.exe"))
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver, WebDriverWait(driver, 20)

# === SCANSIONE PAGINA WEB (FINO A 2 LIVELLI) ===
def scan_page(driver, wait, url, profondita=0, max_prof=2):
    if profondita > max_prof:
        scrivi_log(f"🔚 Raggiunto limite profondità ({profondita}).")
        return

    try:
        driver.get(url)
        time.sleep(3)
        scrivi_log(f"🌐 Apertura pagina: {url}")
    except Exception as e:
        scrivi_log(f"⚠️ Errore caricando {url}: {e}")
        return

    # Trova link o bottoni PDF
    elementi_pdf = driver.find_elements(
        By.XPATH,
        "//a[contains(@href, '.pdf')] | //button[contains(., 'Scarica')] | //a[contains(., 'Scarica')]"
    )
    scrivi_log(f"🔎 Trovati {len(elementi_pdf)} elementi PDF/bottoni nella pagina.")
    for idx, elem in enumerate(elementi_pdf, start=1):
        try:
            href = elem.get_attribute("href")
            if href and href.lower().endswith(".pdf"):
                scrivi_log(f"[{idx}] 📎 Link diretto PDF: {href}")
                driver.execute_script("window.open(arguments[0]);", href)
                time.sleep(2)
            else:
                elem.click()
                scrivi_log(f"[{idx}] 📄 Bottone PDF cliccato.")
                time.sleep(3)
        except Exception as e:
            scrivi_log(f"[{idx}] ⚠️ Errore cliccando elemento PDF: {e}")

    # Trova sottopagine (livello 1 e 2)
    sottopagine = driver.find_elements(
        By.XPATH,
        "//a[contains(., 'Dettaglio')] | //a[contains(., 'Apri')] | //a[contains(., 'Visualizza')] | //a[contains(., 'Prescrizione')] | //a[contains(., 'Cartella')]"
    )
    scrivi_log(f"📂 Trovate {len(sottopagine)} sottopagine cliccabili.")

    for s in sottopagine:
        try:
            href = s.get_attribute("href")
            if href:
                scrivi_log(f"➡️ Apertura sottopagina: {href}")
                scan_page(driver, wait, href, profondita + 1, max_prof)
                driver.back()
                time.sleep(2)
            else:
                s.click()
                scrivi_log("🖱️ Apertura sottopagina senza href (clic manuale).")
                time.sleep(2)
        except Exception as e:
            scrivi_log(f"⚠️ Errore aprendo sottopagina: {e}")

# === MAIN ===
try:
    scrivi_log("=" * 100)
    scrivi_log("🚀 Avvio script PDF Manager – modalità automatica (URL o cartella)")

    path = input("👉 Inserisci un URL o una cartella da analizzare: ").strip()

    if os.path.exists(path):
        scrivi_log(f"📁 Rilevata cartella locale: {path}")
        scan_local_folder(path, DOWNLOAD_DIR)
        scrivi_log("✅ Completato in modalità CARTELLA.")
    elif re.match(r"^https?://", path):
        scrivi_log(f"🌐 Rilevato URL: {path}")
        driver, wait = avvia_driver()
        scan_page(driver, wait, path, profondita=0, max_prof=2)
        scrivi_log(f"✅ Download completato da {path}")
        scrivi_log(f"📂 File salvati in: {DOWNLOAD_DIR}")
    else:
        scrivi_log("❌ Input non valido. Inserisci un URL o una cartella esistente.")

except WebDriverException as e:
    scrivi_log(f"💥 ERRORE SELENIUM: {e}")

finally:
    try:
        driver.quit()
        scrivi_log("🛑 Browser chiuso. Fine script.")
    except:
        pass





