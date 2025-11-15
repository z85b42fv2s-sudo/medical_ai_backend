import fitz  # PyMuPDF

def estrai_testo(pdf_path):
    """Estrae il testo da un file PDF"""
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            contenuto = page.get_text()
            if contenuto:
                text += contenuto + "\n"
    return text[:15000]  # limite di sicurezza

def analizza_fake_ai(testo):
    """Simula un'analisi AI: riassunto + classificazione"""
    parole = len(testo.split())
    return (
        f"🧠 Analisi simulata completata!\n"
        f"- Lunghezza testo: {parole} parole\n"
        f"- Possibile tipologia di documento: {'Referto medico' if 'diagnosi' in testo.lower() else 'Documento generico'}\n"
        f"- Riassunto fittizio: Testo contenente {parole} parole con termini clinici rilevati."
    )
