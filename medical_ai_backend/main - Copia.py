import os
from download_pdfs import scarica_pdfs_da_sito
from analyze_pdf_fake_ai import estrai_testo, analizza_fake_ai

def main():
    url_iniziale = input("🌍 Inserisci l’URL della pagina principale: ").strip()
    cartella_dest = "pdf_downloads"

    # Step 1 - Scarica i PDF da tutte le pagine e sottopagine
    scarica_pdfs_da_sito(url_iniziale, cartella_dest, profondita=2)

    # Step 2 - Analizza ogni PDF trovato
    print("\n🔍 Analisi dei PDF scaricati...\n")

    for nome in os.listdir(cartella_dest):
        if nome.lower().endswith(".pdf"):
            pdf_path = os.path.join(cartella_dest, nome)
            print(f"📄 Analizzando: {nome}")
            testo = estrai_testo(pdf_path)
            risultato = analizza_fake_ai(testo)

            # Stampa e salva i risultati
            print(f"--- RISULTATO ---\n{risultato}\n{'-'*50}")

            # Salvataggio in file .txt
            output_path = os.path.join("analisi_risultati", nome.replace(".pdf", ".txt"))
            os.makedirs("analisi_risultati", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(risultato)

    print("\n✅ Tutti i PDF sono stati scaricati e analizzati!")

if __name__ == "__main__":
    main()
