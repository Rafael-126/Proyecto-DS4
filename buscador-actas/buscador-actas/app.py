"""Aplicación Flask: buscador sobre el índice almacenado (nunca hace scraping)."""
import time

from flask import Flask, render_template, request

import search
from db import get_conn

app = Flask(__name__)


@app.route("/")
def index():
    q = request.args.get("q")
    conn = get_conn()
    try:
        docs = conn.execute(
            "SELECT COUNT(*) FROM documentos WHERE estado_indexacion = 'indexado'"
        ).fetchone()[0]
        ctx = {"q": q or "", "docs_indexados": docs, "umbral": round(search.UMBRAL * 100),
               "consultado": q is not None, "vacia": False, "resultados": [],
               "sin_indice": docs == 0, "segundos": 0}
        if q is not None:
            if not q.strip():
                ctx["vacia"] = True
            elif docs:
                t0 = time.perf_counter()
                ctx["resultados"] = search.buscar(conn, q)
                ctx["segundos"] = round(time.perf_counter() - t0, 2)
    finally:
        conn.close()
    return render_template("index.html", **ctx)


if __name__ == "__main__":
    app.run(debug=True)
