"""Extrae el texto de los PDFs pendientes y lo guarda en SQLite."""
import argparse
import logging

from pypdf import PdfReader

from db import BASE_DIR, get_conn
from search import normalizar

logging.getLogger("pypdf").setLevel(logging.ERROR)
log = logging.getLogger("indexer")

PALABRAS_POR_FRAGMENTO = 150
TRASLAPE = 25
MIN_CARACTERES = 30  # menos que esto en todo el PDF => se considera sin texto


def fragmentar(texto):
    """Divide el texto de una página en fragmentos de ~150 palabras con traslape."""
    palabras = texto.split()
    if not palabras:
        return []
    if len(palabras) <= PALABRAS_POR_FRAGMENTO:
        return [" ".join(palabras)]
    paso = PALABRAS_POR_FRAGMENTO - TRASLAPE
    trozos = []
    for ini in range(0, len(palabras), paso):
        trozos.append(" ".join(palabras[ini:ini + PALABRAS_POR_FRAGMENTO]))
        if ini + PALABRAS_POR_FRAGMENTO >= len(palabras):
            break
    return trozos


def normalizar_alineado(fragmento):
    """Normaliza palabra por palabra para que ambos textos tengan igual número de palabras."""
    return " ".join(normalizar(p) or "_" for p in fragmento.split())


def extraer_paginas(ruta):
    lector = PdfReader(ruta)
    if lector.is_encrypted:
        lector.decrypt("")
    paginas = []
    for num, pagina in enumerate(lector.pages, start=1):
        try:
            paginas.append((num, pagina.extract_text() or ""))
        except Exception as e:  # una página dañada no detiene el documento
            log.warning("  página %d ilegible: %s", num, e)
    return paginas


def indexar(reindexar=False):
    conn = get_conn()
    if reindexar:
        conn.execute("UPDATE documentos SET estado_indexacion = 'pendiente'")
        conn.commit()
    pendientes = conn.execute(
        "SELECT * FROM documentos WHERE estado_indexacion = 'pendiente'"
    ).fetchall()
    log.info("Documentos por indexar: %d", len(pendientes))

    indexados, sin_texto, errores = 0, [], []
    for doc in pendientes:
        ruta = BASE_DIR / doc["ruta_local"]
        log.info("Indexando: %s", doc["nombre"])
        try:
            if not ruta.is_file():
                raise FileNotFoundError(f"no existe {ruta}")
            paginas = extraer_paginas(ruta)
            filas = []
            for num, texto in paginas:
                for frag in fragmentar(texto):
                    filas.append((doc["id"], num, frag, normalizar_alineado(frag)))
            total = sum(len(f[2]) for f in filas)

            conn.execute("DELETE FROM fragmentos WHERE documento_id = ?", (doc["id"],))
            if total < MIN_CARACTERES:
                estado = "sin_texto"
                sin_texto.append(doc["nombre"])
            else:
                conn.executemany(
                    "INSERT INTO fragmentos (documento_id, pagina, texto_original, "
                    "texto_normalizado) VALUES (?, ?, ?, ?)", filas)
                estado = "indexado"
                indexados += 1
            conn.execute("UPDATE documentos SET estado_indexacion = ? WHERE id = ?",
                         (estado, doc["id"]))
        except Exception as e:
            log.error("  error: %s", e)
            errores.append(f"{doc['nombre']} ({e})")
            conn.execute("UPDATE documentos SET estado_indexacion = 'error' WHERE id = ?",
                         (doc["id"],))
        conn.commit()

    print("\n=== Resumen de indexación ===")
    print(f"Indexados:  {indexados}")
    print(f"Sin texto:  {len(sin_texto)}")
    print(f"Con error:  {len(errores)}")
    if sin_texto:
        print("\nPDFs sin texto extraíble (¿escaneados? haría falta OCR):")
        for n in sin_texto:
            print(f"  - {n}")
    if errores:
        print("\nPDFs con error:")
        for e in errores:
            print(f"  - {e}")
    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Indexa los PDFs descargados.")
    ap.add_argument("--reindexar", action="store_true",
                    help="vuelve a indexar todos los documentos")
    indexar(ap.parse_args().reindexar)
