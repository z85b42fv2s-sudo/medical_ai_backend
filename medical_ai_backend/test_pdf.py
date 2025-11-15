import fitz  # PyMuPDF

def estrai_testo(pdf_path):
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            contenuto = page.get_text()
            if contenuto:
                text += contenuto + "\n"
    return text

if __name__ == "__main__":
    path = "prova.pdf"
    try:
        testo = estrai_testo(path)
        print("✅ Testo estratto con successo!\n")
        print(testo[:1500])  # mostra le prime 1500 battute
    except Exception as e:
        print(f"❌ Errore durante l'estrazione: {e}")
