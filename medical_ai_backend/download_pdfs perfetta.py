# -*- coding: utf-8 -*-
"""
download_pdfs.py
----------------
- Input unico: URL o percorso di una cartella locale.
- Se cartella: copia TUTTI i PDF trovati (anche nelle sottocartelle) in ./downloaded_pdfs
- Se URL: naviga la pagina, apre link e bottoni (anche con onclick), entra nelle sottopagine
  e scarica i PDF, fino a profondità = 2.
- Supporta autenticazione SPID manuale (mantiene aperta la finestra fino a login completato).

Esegui:
(.venv) python download_pdfs.py
"""

import os
import re
import time
import shutil
from datetime import datetime
from urllib.parse import urlparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

try:
    from webdriver_manager.chrome import ChromeDriverManager
    HAVE_WDM = True
except Exception:
    HAVE_WDM = False

BASE_DIR = os.getcwd()
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloaded_pdfs")
LOG_FILE = os.path.join(BASE_DIR, "log_download.txt")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# === Utility ===
def scrivi_log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def is_url(s: str) -> bool:
    try:
        p = urlparse(s.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

# === Scansione cartelle ===
def scan_local_folder(folder: str, out_dir: str) -> dict:
    scrivi_log(f"📂 Avvio scansione cartella: {folder}")
    stats = {"main": 0, "sub": 0}

    if not os.path.isdir(folder):
        scrivi_log(f"❌ Errore: cartella non trovata -> {folder}")
        return stats

    os.makedirs(out_dir, exist_ok=True)
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
                    if os.path.abspath(root) == os.path.abspath(folder):
                        stats["main"] += 1
                    else:
                        stats["sub"] += 1
                    scrivi_log(f"✅ Copiato: {dest}")
                except Exception as e:
                    scrivi_log(f"⚠️ Errore copiando '{src}': {e}")
    scrivi_log(f"🏁 Scansione completata: {stats['main'] + stats['sub']} PDF totali.")
    return stats

# === Selenium WebDriver ===
def build_chrome_driver():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-popup-blocking")
    options.add_experimental_option("detach", True)  # 🔒 mantiene la finestra aperta

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    chromedriver_path = os.path.join(BASE_DIR, "chromedriver.exe")
    if os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
    elif HAVE_WDM:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
    else:
        service = Service()

    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(90)
    return driver, WebDriverWait(driver, 30)

# === Supporto per click JS ===
def click_js(driver, el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.5)
    driver.execute_script("arguments[0].click();", el)

# === Scarica PDF nella pagina ===
def collect_and_download_pdfs_in_page(driver, wait, depth, stats, where):
    elems = driver.find_elements(
        By.XPATH,
        "//a[contains(translate(@href,'PDF','pdf'),'.pdf')] | //button[contains(.,'Scarica')] | //button[contains(.,'Visualizza')]"
    )
    scrivi_log(f"🔎 ({where}) Trovati {len(elems)} link/bottoni PDF.")
    for idx, el in enumerate(elems, start=1):
        try:
            href = el.get_attribute("href")
            if href and href.lower().endswith(".pdf"):
                driver.execute_script("window.open(arguments[0],'_blank');", href)
                scrivi_log(f"📎 ({where}) Link PDF diretto aperto: {href}")
            else:
                click_js(driver, el)
                scrivi_log(f"🖱️ ({where}) Click bottone PDF (JS forzato) idx={idx}")
            stats[where] += 1
            time.sleep(2)
        except Exception as e:
            scrivi_log(f"⚠️ ({where}) Errore su elemento PDF idx={idx}: {e}")

# === Apre righe tipo “Prescrizione / Referto” ===
def open_rows_and_download_inside(driver, wait, depth, max_depth, stats):
    rows = driver.find_elements(
        By.XPATH,
        "//a[contains(.,'Prescrizione') or contains(.,'Referto') or contains(.,'Erogazione')]"
    )
    scrivi_log(f"📁 (depth {depth}) Trovate {len(rows)} righe cliccabili.")
    for ridx, row in enumerate(rows, start=1):
        try:
            txt = (row.text or "").strip()
            click_js(driver, row)
            scrivi_log(f"➡️ Apertura documento [{ridx}]: {txt}")
            time.sleep(1.5)
            collect_and_download_pdfs_in_page(driver, wait, depth, stats, "sub")
            if depth + 1 <= max_depth:
                sublinks = driver.find_elements(
                    By.XPATH,
                    "//a[contains(.,'Dettaglio') or contains(.,'Apri') or contains(.,'Documento')]"
                )
                for sidx, s in enumerate(sublinks, start=1):
                    click_js(driver, s)
                    scrivi_log(f"↪️ Sottolink [{sidx}] aperto.")
                    time.sleep(1)
                    collect_and_download_pdfs_in_page(driver, wait, depth + 1, stats, "sub")
                    driver.back()
                    time.sleep(1)
            driver.back()
            time.sleep(1)
        except Exception as e:
            scrivi_log(f"⚠️ Errore aprendo documento [{ridx}]: {e}")

# === Scansione pagina ===
def scan_page(driver, wait, url, max_depth=2):
    stats = {"main": 0, "sub": 0}
    scrivi_log(f"🌐 Apertura pagina principale: {url}")
    driver.get(url)
    time.sleep(2)
    collect_and_download_pdfs_in_page(driver, wait, 0, stats, "main")
    open_rows_and_download_inside(driver, wait, 0, max_depth, stats)
    return stats

# === MAIN ===
if __name__ == "__main__":
    scrivi_log("=" * 100)
    scrivi_log("🚀 Avvio PDF Manager — input automatico (URL o cartella)")
    user_input = input("👉 Inserisci un URL o il percorso di una cartella: ").strip()
    start_time = time.time()

    if is_url(user_input):
        scrivi_log(f"🌍 Rilevato URL: {user_input}")
        driver, wait = build_chrome_driver()
        driver.get(user_input)
        scrivi_log("🔐 Esegui il login SPID nella finestra del browser.")
        input("👉 Premi INVIO qui dopo aver completato il login ed essere entrato nel fascicolo...")

        stats = scan_page(driver, wait, user_input, max_depth=2)
        scrivi_log(f"✅ Download completato da {user_input}")
        scrivi_log(f"📊 Totale PDF — Pagina principale: {stats['main']} | Sottopagine: {stats['sub']} | Totale: {stats['main'] + stats['sub']}")
        scrivi_log(f"📂 File salvati in: {DOWNLOAD_DIR}")

        try:
            driver.quit()
            scrivi_log("🛑 Browser chiuso. Fine script.")
        except:
            pass

    else:
        folder = os.path.abspath(user_input)
        scrivi_log(f"📁 Rilevata cartella: {folder}")
        stats = scan_local_folder(folder, DOWNLOAD_DIR)
        scrivi_log(f"📊 Totale PDF — Cartella principale: {stats['main']} | Sottocartelle: {stats['sub']} | Totale: {stats['main'] + stats['sub']}")

    elapsed = time.time() - start_time
    scrivi_log(f"⏱️ Durata: {elapsed:.1f} secondi")
    scrivi_log("=" * 100)




