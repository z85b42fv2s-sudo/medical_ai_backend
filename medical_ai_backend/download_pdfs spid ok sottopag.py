import os
import re
import time
import shutil
from datetime import datetime
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False

# === CONFIG ===
BASE_DIR = os.getcwd()
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloaded_pdfs")
LOG_FILE = os.path.join(BASE_DIR, "log_download.txt")
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def scrivi_log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {msg}\n")


# === SALVATAGGIO COOKIE ===
def save_cookies(driver, file_path):
    import pickle
    with open(file_path, "wb") as f:
        pickle.dump(driver.get_cookies(), f)
    scrivi_log("🍪 Cookie salvati.")


def load_cookies(driver, url, file_path):
    import pickle
    try:
        driver.get(url)
        with open(file_path, "rb") as f:
            cookies = pickle.load(f)
        for cookie in cookies:
            driver.add_cookie(cookie)
        scrivi_log("🍪 Cookie caricati.")
        return True
    except Exception as e:
        scrivi_log(f"⚠️ Errore caricando cookie: {e}")
        return False


# === SCANSIONE CARTELLA LOCALE ===
def scan_local_folder(folder, out_dir):
    scrivi_log(f"📂 Scansione cartella: {folder}")
    if not os.path.isdir(folder):
        scrivi_log(f"❌ Cartella non trovata: {folder}")
        return 0, 0

    count_main, count_sub = 0, 0
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
                shutil.copy2(src, dest)
                scrivi_log(f"✅ Copiato: {dest}")
                if root == folder:
                    count_main += 1
                else:
                    count_sub += 1
    scrivi_log(f"🏁 Trovati {count_main} PDF nella cartella principale e {count_sub} nelle sottocartelle.")
    return count_main, count_sub


# === DRIVER SELENIUM ===
def create_driver():
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option("prefs", {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True
    })
    opts.add_experimental_option("detach", True)

    if WEBDRIVER_MANAGER_AVAILABLE:
        scrivi_log("ℹ️ webdriver-manager disponibile: userò ChromeDriverManager.")
        service = Service(ChromeDriverManager().install())
    else:
        service = Service(os.path.join(BASE_DIR, "chromedriver.exe"))

    try:
        driver = webdriver.Chrome(service=service, options=opts)
        wait = WebDriverWait(driver, 20)
        return driver, wait
    except Exception as e:
        scrivi_log(f"❌ Errore creando il driver: {e}")
        raise


# === SCANSIONE PAGINE ===
def scan_page(driver, wait, url, profondita=0, max_prof=2, count=None):
    if count is None:
        count = {"main": 0, "sub": 0}
    if profondita > max_prof:
        scrivi_log(f"🔚 Limite profondità raggiunto ({profondita}).")
        return count

    scrivi_log(f"🌐 Apertura pagina: {url}")
    try:
        driver.get(url)
        time.sleep(3)
    except Exception as e:
        scrivi_log(f"⚠️ Errore caricando {url}: {e}")
        return count

    elementi_pdf = driver.find_elements(By.XPATH, "//a[contains(@href, '.pdf')] | //button[contains(., 'Scarica')]")
    scrivi_log(f"🔎 Trovati {len(elementi_pdf)} file/bottoni PDF nella pagina.")
    for elem in elementi_pdf:
        try:
            href = elem.get_attribute("href")
            if href and href.lower().endswith(".pdf"):
                scrivi_log(f"📎 Link diretto PDF: {href}")
                driver.execute_script("window.open(arguments[0]);", href)
                if profondita == 0:
                    count["main"] += 1
                else:
                    count["sub"] += 1
                time.sleep(2)
            else:
                elem.click()
                scrivi_log("📄 Click su bottone di download PDF.")
                if profondita == 0:
                    count["main"] += 1
                else:
                    count["sub"] += 1
                time.sleep(2)
        except Exception as e:
            scrivi_log(f"⚠️ Errore cliccando elemento PDF: {e}")

    sottopagine = driver.find_elements(By.XPATH, "//a[contains(., 'Cartella') or contains(., 'Dettaglio') or contains(., 'Apri')]")
    scrivi_log(f"📁 Trovate {len(sottopagine)} sottopagine/cartelle cliccabili.")
    for s in sottopagine:
        try:
            href = s.get_attribute("href")
            if href:
                scrivi_log(f"➡️ Entrata in sottopagina: {href}")
                scan_page(driver, wait, href, profondita + 1, max_prof, count)
                driver.back()
                time.sleep(2)
        except Exception as e:
            scrivi_log(f"⚠️ Errore aprendo sottopagina: {e}")

    return count


# === MAIN ===
if __name__ == "__main__":
    scrivi_log("=" * 100)
    scrivi_log("🚀 Avvio script PDF Manager – input automatico (URL o cartella)")

    path = input("👉 Inserisci un URL o il percorso di una cartella: ").strip()

    if os.path.isdir(path):
        count_main, count_sub = scan_local_folder(path, DOWNLOAD_DIR)
        scrivi_log(f"✅ Completato in modalità cartella: {count_main + count_sub} file totali.")
        raise SystemExit(0)

    elif re.match(r"^https?://", path):
        driver, wait = create_driver()

        parsed = urlparse(path)
        domain_base = f"{parsed.scheme}://{parsed.netloc}/"
        scrivi_log(f"🌍 Dominio base: {domain_base}")

        # Carica cookie se disponibili
        if os.path.exists(COOKIES_FILE):
            scrivi_log("🔑 Tentativo di login automatico con cookie salvati...")
            driver.get(domain_base)
            time.sleep(2)
            loaded = load_cookies(driver, domain_base, COOKIES_FILE)
            if loaded:
                driver.get(path)
                time.sleep(3)
                scrivi_log("✅ Cookie caricati e sottopagina aperta.")
            else:
                scrivi_log("⚠️ Cookie non validi. Login manuale richiesto.")
        else:
            scrivi_log("🔒 Nessun cookie trovato. Esegui login SPID manualmente, poi premi INVIO...")
            driver.get(path)
            input("🔹 Premi INVIO dopo aver completato il login SPID... ")
            save_cookies(driver, COOKIES_FILE)

        risultati = scan_page(driver, wait, path)
        scrivi_log(f"📊 Totale PDF trovati: {risultati['main']} nella pagina principale e {risultati['sub']} nelle sottopagine.")
        scrivi_log(f"📂 File salvati in: {DOWNLOAD_DIR}")

    else:
        scrivi_log("❌ Input non riconosciuto. Inserisci un URL o una cartella valida.")

    scrivi_log("🛑 Fine script.")

