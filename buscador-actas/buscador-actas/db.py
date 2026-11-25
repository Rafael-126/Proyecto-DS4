"""Conexión y esquema de la base de datos SQLite."""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "actas.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"

# estado_indexacion: pendiente | indexado | sin_texto | error
SCHEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    ruta_local TEXT NOT NULL,
    hash_contenido TEXT,
    fecha_descarga TEXT NOT NULL DEFAULT (datetime('now')),
    estado_indexacion TEXT NOT NULL DEFAULT 'pendiente'
);
CREATE TABLE IF NOT EXISTS fragmentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    documento_id INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    pagina INTEGER NOT NULL,
    texto_original TEXT NOT NULL,
    texto_normalizado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fragmentos_doc ON fragmentos(documento_id);
"""


def get_conn():
    """Abre la base (la crea si no existe) y garantiza el esquema."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
