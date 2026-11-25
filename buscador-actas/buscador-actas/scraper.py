"""Scraper: recorre las URLs registradas y descarga los PDFs que aún no existen."""
import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
from collections import deque
from urllib.parse import unquote, urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from db import BASE_DIR, DOWNLOADS_DIR, get_conn

CONFIG_PATH = BASE_DIR / "config" / "urls.json"
CONFIG_DEFAULT = {
    "urls": ["https://fi-ing.unison.mx/"],
    "max_profundidad": 3,        # niveles de enlaces desde la URL inicial
    "pausa_segundos": 1.0,       # pausa entre solicitudes al sitio
    "max_paginas_por_url": 150,  # tope de páginas HTML por URL inicial
    "palabras_clave": ["acta"],  # solo se siguen páginas cuyo enlace/URL las contenga ([] = todas)
}
HEADERS = {"User-Agent": "BuscadorActas/1.0 (proyecto escolar, Universidad de Sonora)"}
EXT_IGNORADAS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".rar",
                 ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp3", ".mp4")

log = logging.getLogger("scraper")


# ---------------------------------------------------------------- configuración
def cargar_config():
    if not CONFIG_PATH.exists():
        guardar_config(CONFIG_DEFAULT)
        return dict(CONFIG_DEFAULT)
    try:
        datos = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"config/urls.json no es un JSON válido: {e}")
    return {**CONFIG_DEFAULT, **datos}


def guardar_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")


# ---------------------------------------------------------------- utilidades
def sin_acentos(texto):
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def host(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def es_pdf(url):
    return urlparse(url).path.lower().endswith(".pdf")


def es_relevante(href, texto, claves):
    if not claves:
        return True
    muestra = sin_acentos(f"{unquote(href)} {texto}").lower()
    return any(sin_acentos(c).lower() in muestra for c in claves)


def slug(texto, maximo=60):
    texto = sin_acentos(texto).lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")
    return texto[:maximo] or "documento"


def nombre_desde_url(url):
    nombre = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return re.sub(r"\.pdf$", "", nombre, flags=re.I) or url


# ---------------------------------------------------------------- recorrido
def obtener_html(session, url):
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("No se pudo abrir %s: %s", url, e)
        return None
    if "html" not in r.headers.get("Content-Type", "").lower():
        return None
    return r.content


def recorrer(session, inicio, cfg, stats):
    """Recorre en anchura desde `inicio`. Devuelve {url_pdf: texto_del_enlace}."""
    pdfs = {}
    visitadas = set()
    cola = deque([(urldefrag(inicio)[0], 0)])
    while cola and len(visitadas) < cfg["max_paginas_por_url"]:
        url, profundidad = cola.popleft()
        if url in visitadas:
            continue
        visitadas.add(url)
        log.info("[prof %d] %s", profundidad, url)
        html = obtener_html(session, url)
        time.sleep(cfg["pausa_segundos"])
        if html is None:
            continue
        stats["paginas"] += 1
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urldefrag(urljoin(url, a["href"].strip()))[0]
            if urlparse(href).scheme not in ("http", "https"):
                continue
            texto = " ".join(a.get_text().split()) or (a.get("title") or "").strip()
            if es_pdf(href):
                if href not in pdfs or (not pdfs[href] and texto):
                    pdfs[href] = texto
            elif (profundidad < cfg["max_profundidad"]
                  and host(href) == host(inicio)
                  and not urlparse(href).path.lower().endswith(EXT_IGNORADAS)
                  and href not in visitadas
                  and es_relevante(href, texto, cfg["palabras_clave"])):
                cola.append((href, profundidad + 1))
    return pdfs


# ---------------------------------------------------------------- descarga
def descargar(conn, session, url, texto, cfg, stats):
    fila = conn.execute("SELECT * FROM documentos WHERE url = ?", (url,)).fetchone()
    if fila and (BASE_DIR / fila["ruta_local"]).is_file():
        stats["existentes"] += 1
        return

    nombre = texto or nombre_desde_url(url)
    try:
        r = session.get(url, timeout=60)
        r.raise_for_status()
        contenido = r.content
        if b"%PDF" not in contenido[:1024]:
            raise ValueError("el archivo no parece un PDF")
    except (requests.RequestException, ValueError) as e:
        log.warning("Descarga fallida %s: %s", url, e)
        stats["fallidos"] += 1
        stats["fallos"].append(url)
        time.sleep(cfg["pausa_segundos"])
        return

    # <hash-corto-de-URL>_<nombre>.pdf: documentos distintos nunca chocan
    archivo = f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{slug(nombre)}.pdf"
    (DOWNLOADS_DIR / archivo).write_bytes(contenido)
    ruta = f"downloads/{archivo}"
    hash_contenido = hashlib.sha256(contenido).hexdigest()

    if fila:  # registro existía pero el archivo faltaba: se re-descargó
        conn.execute("DELETE FROM fragmentos WHERE documento_id = ?", (fila["id"],))
        conn.execute(
            "UPDATE documentos SET nombre=?, ruta_local=?, hash_contenido=?, "
            "fecha_descarga=datetime('now'), estado_indexacion='pendiente' WHERE id=?",
            (nombre, ruta, hash_contenido, fila["id"]))
    else:
        conn.execute(
            "INSERT INTO documentos (url, nombre, ruta_local, hash_contenido) "
            "VALUES (?, ?, ?, ?)", (url, nombre, ruta, hash_contenido))
    conn.commit()
    stats["descargados"] += 1
    log.info("Descargado: %s", nombre)
    time.sleep(cfg["pausa_segundos"])


def ejecutar():
    cfg = cargar_config()
    conn = get_conn()
    stats = {"paginas": 0, "encontrados": 0, "descargados": 0,
             "existentes": 0, "fallidos": 0, "fallos": []}
    procesados = set()
    with requests.Session() as session:
        session.headers.update(HEADERS)
        for inicio in cfg["urls"]:
            log.info("=== Escaneando %s ===", inicio)
            try:
                pdfs = recorrer(session, inicio, cfg, stats)
            except Exception as e:  # un fallo en una URL no detiene las demás
                log.error("Error al recorrer %s: %s", inicio, e)
                continue
            for url, texto in pdfs.items():
                if url in procesados:
                    continue
                procesados.add(url)
                stats["encontrados"] += 1
                try:
                    descargar(conn, session, url, texto, cfg, stats)
                except Exception as e:
                    log.error("Error inesperado con %s: %s", url, e)
                    stats["fallidos"] += 1
                    stats["fallos"].append(url)
    conn.close()

    print("\n=== Resumen del scraping ===")
    print(f"Páginas visitadas: {stats['paginas']}")
    print(f"PDFs encontrados:  {stats['encontrados']}")
    print(f"Descargados:       {stats['descargados']}")
    print(f"Ya existentes:     {stats['existentes']}")
    print(f"Fallidos:          {stats['fallidos']}")
    for u in stats["fallos"]:
        print(f"  - {u}")


# ---------------------------------------------------------------- CLI
def agregar_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        sys.exit("URL inválida: debe empezar con http:// o https://")
    cfg = cargar_config()
    if url in cfg["urls"]:
        print("Esa URL ya estaba registrada.")
        return
    cfg["urls"].append(url)
    guardar_config(cfg)
    print(f"URL agregada: {url}")


def listar_urls():
    for i, u in enumerate(cargar_config()["urls"], start=1):
        print(f"{i}. {u}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Descarga actas en PDF.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="recorre las URLs registradas y descarga PDFs nuevos")
    p_add = sub.add_parser("add-url", help="registra una nueva URL para escanear")
    p_add.add_argument("url")
    sub.add_parser("list-urls", help="muestra las URLs registradas")
    args = ap.parse_args()
    if args.cmd == "run":
        ejecutar()
    elif args.cmd == "add-url":
        agregar_url(args.url)
    else:
        listar_urls()
