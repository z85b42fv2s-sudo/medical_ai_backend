# -*- coding: utf-8 -*-
"""
download_pdfs.py (versione API + standalone)
--------------------------------------------
- Input unico: URL o percorso di una cartella locale.
- Se cartella: copia TUTTI i PDF trovati (anche nelle sottocartelle) in ./downloaded_pdfs
- Se URL: naviga la pagina, apre link e bottoni (anche con onclick), entra nelle sottopagine
  e scarica i PDF, fino a profonditÃ  = 2.
- Supporta autenticazione SPID manuale (mantiene aperta la finestra fino a login completato).

Esegui da terminale:
(.venv) python download_pdfs.py
Oppure tramite FastAPI con: download_pdfs(source)
"""

import glob
import os
import re
import time
import shutil
import urllib.parse
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


def normalize_base_name(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    name = name.strip()
    # Rimuovi suffissi come " (1)" o " (2)"
    match = re.match(r"^(.*)\s+\((\d+)\)$", name)
    if match:
        name = match.group(1)
    # Rimuovi suffissi tipo "--1-" o "--2--"
    name = re.sub(r"--\d+-*$", "", name)
    # Rimuovi eventuali doppioni con __1, _1 ecc.
    name = re.sub(r"[_\-]+(\d+)$", "", name)
    return f"{name}{ext}".lower()


def remove_duplicate_pdfs(directory: str) -> int:
    removed = 0
    seen: dict[tuple[str, int], str] = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.pdf"))):
        base = normalize_base_name(os.path.basename(path))
        size = os.path.getsize(path)
        key = (base, size)
        if key in seen:
            scrivi_log(f"[WARN] Duplicato rilevato (nome e dimensione). Rimuovo: {path}")
            try:
                os.remove(path)
                removed += 1
            except Exception as exc:
                scrivi_log(f"[WARN] Impossibile rimuovere duplicato '{path}': {exc}")
        else:
            seen[key] = path
    return removed

# === Scansione cartelle ===
def scan_local_folder(folder: str, out_dir: str) -> dict:
    scrivi_log(f"[SCAN] Avvio scansione cartella: {folder}")
    stats = {"main": 0, "sub": 0}

    if not os.path.isdir(folder):
        scrivi_log(f"[ERRORE] Cartella non trovata -> {folder}")
        return stats

    os.makedirs(out_dir, exist_ok=True)
    for root, _, files in os.walk(folder):
        for fn in files:
            if not fn.lower().endswith('.pdf'):
                continue
            src = os.path.join(root, fn)
            dest = os.path.join(out_dir, fn)

            if os.path.exists(dest) and os.path.getsize(dest) == os.path.getsize(src):
                scrivi_log(f"[INFO] Duplicato ignorato (stesso nome e dimensione): {dest}")
                continue

            base, ext = os.path.splitext(fn)
            suffix = 1
            candidate = dest
            while os.path.exists(candidate):
                if os.path.getsize(candidate) == os.path.getsize(src):
                    scrivi_log(f"[INFO] Duplicato ignorato: {candidate}")
                    candidate = None
                    break
                candidate = os.path.join(out_dir, f"{base} ({suffix}){ext}")
                suffix += 1

            if candidate is None:
                continue

            try:
                shutil.copy2(src, candidate)
                if os.path.abspath(root) == os.path.abspath(folder):
                    stats['main'] += 1
                else:
                    stats['sub'] += 1
                scrivi_log(f"[OK] Copiato: {candidate}")
            except Exception as e:
                scrivi_log(f"[WARN] Errore copiando '{src}': {e}")

    removed = remove_duplicate_pdfs(out_dir)
    if removed:
        scrivi_log(f"[INFO] Duplicati rimossi post scansione: {removed}")
    scrivi_log(f"[FINE] Scansione completata: {stats['main'] + stats['sub']} PDF totali.")
    return stats


# === Selenium WebDriver ===
def build_chrome_driver():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-popup-blocking")
    options.add_experimental_option("detach", True)  # ðŸ”’ mantiene la finestra aperta

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
    scrivi_log(f"ðŸ”Ž ({where}) Trovati {len(elems)} link/bottoni PDF.")
    for idx, el in enumerate(elems, start=1):
        try:
            href = el.get_attribute("href")
            if href and href.lower().endswith(".pdf"):
                driver.execute_script("window.open(arguments[0],'_blank');", href)
                scrivi_log(f"ðŸ“Ž ({where}) Link PDF diretto aperto: {href}")
            else:
                click_js(driver, el)
                scrivi_log(f"ðŸ–±ï¸ ({where}) Click bottone PDF (JS forzato) idx={idx}")
            stats[where] += 1
            time.sleep(2)
        except Exception as e:
            scrivi_log(f"âš ï¸ ({where}) Errore su elemento PDF idx={idx}: {e}")

# === Apre righe tipo â€œPrescrizione / Refertoâ€ ===
def open_rows_and_download_inside(driver, wait, depth, max_depth, stats):
    rows = driver.find_elements(
        By.XPATH,
        "//a[contains(.,'Prescrizione') or contains(.,'Referto') or contains(.,'Erogazione')]"
    )
    scrivi_log(f"ðŸ“ (depth {depth}) Trovate {len(rows)} righe cliccabili.")
    for ridx, row in enumerate(rows, start=1):
        try:
            txt = (row.text or '').strip()
            click_js(driver, row)
            scrivi_log(f"âž¡ï¸ Apertura documento [{ridx}]: {txt}")
            time.sleep(1.5)
            collect_and_download_pdfs_in_page(driver, wait, depth, stats, "sub")
            if depth + 1 <= max_depth:
                sublinks = driver.find_elements(
                    By.XPATH,
                    "//a[contains(.,'Dettaglio') or contains(.,'Apri') or contains(.,'Documento')]"
                )
                for sidx, s in enumerate(sublinks, start=1):
                    click_js(driver, s)
                    scrivi_log(f"â†ªï¸ Sottolink [{sidx}] aperto.")
                    time.sleep(1)
                    collect_and_download_pdfs_in_page(driver, wait, depth + 1, stats, "sub")
                    driver.back()
                    time.sleep(1)
            driver.back()
            time.sleep(1)
        except Exception as e:
            scrivi_log(f"âš ï¸ Errore aprendo documento [{ridx}]: {e}")

# === Scansione pagina ===
def scan_page(driver, wait, url, max_depth=2, open_url=True):
    stats = {"main": 0, "sub": 0}
    if open_url:
        scrivi_log(f"[INFO] Apertura pagina: {url}")
        driver.get(url)
        time.sleep(2)
    else:
        scrivi_log(f"[INFO] Ripresa scansione (pagina gia aperta): {url}")
    collect_and_download_pdfs_in_page(driver, wait, 0, stats, "main")
    open_rows_and_download_inside(driver, wait, 0, max_depth, stats)
    return stats
# === Funzione API (per backend) ===
def download_pdfs(source: str | None = None) -> dict:
    scrivi_log("=" * 100)
    scrivi_log("ðŸš€ Avvio PDF Manager via API")

    source = urllib.parse.unquote(source or "").strip()
    if not source:
        scrivi_log("âŒ Nessuna sorgente fornita.")
        return {"main": 0, "sub": 0}

    start_time = time.time()
    stats = {"main": 0, "sub": 0}

    if is_url(source):
        scrivi_log(f"ðŸŒ Rilevato URL: {source}")
        driver, wait = build_chrome_driver()
        driver.get(source)
        scrivi_log("ðŸ” Effettua il login SPID nella finestra di Chrome.")
        input("ðŸ‘‰ Premi INVIO nel terminale quando hai completato il login...")
        stats = scan_page(driver, wait, source, max_depth=2)
        try:
            driver.quit()
            scrivi_log("ðŸ›‘ Browser chiuso.")
        except:
            pass
    else:
        folder = os.path.abspath(source)
        scrivi_log(f"ðŸ“ Rilevata cartella: {folder}")
        stats = scan_local_folder(folder, DOWNLOAD_DIR)

    removed = remove_duplicate_pdfs(DOWNLOAD_DIR)
    if removed:
        scrivi_log(f'[INFO] Duplicati complessivi rimossi: {removed}')


    elapsed = time.time() - start_time
    scrivi_log(f"â±ï¸ Durata: {elapsed:.1f} secondi")
    scrivi_log(f"ðŸ“Š Totale PDF scaricati: {stats['main'] + stats['sub']}")
    scrivi_log(f"ðŸ“‚ Salvati in: {DOWNLOAD_DIR}")
    scrivi_log("=" * 100)
    return stats

# === MAIN standalone ===
if __name__ == "__main__":
    scrivi_log("=" * 100)
    scrivi_log("ðŸš€ Avvio PDF Manager â€” modalitÃ  manuale")
    user_input = input("ðŸ‘‰ Inserisci un URL o percorso cartella: ").strip()
    download_pdfs(user_input)

