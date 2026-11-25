"""Normalización y búsqueda aproximada con similitud de Levenshtein."""
import unicodedata

import Levenshtein

UMBRAL = 0.75          # puntuación mínima para considerar una coincidencia
CONTEXTO_PALABRAS = 15  # palabras de contexto antes y después de la coincidencia
MAX_RESULTADOS = 50


def normalizar(texto):
    """Minúsculas, sin acentos y con espacios colapsados."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(texto.lower().split())


def mejor_ventana(consulta, texto, umbral=UMBRAL):
    """Devuelve (puntuación, inicio, fin) de la mejor ventana de palabras.

    `consulta` y `texto` ya están normalizados. inicio/fin son índices de
    palabras dentro del texto. Si la consulta aparece tal cual, puntuación 1.0.
    """
    n = len(consulta.split())
    pos = texto.find(consulta)
    if pos != -1:
        inicio = texto.count(" ", 0, pos)
        return 1.0, inicio, inicio + n

    palabras = texto.split()
    mejor = (0.0, 0, 0)
    lc = len(consulta)
    for tam in sorted({max(1, n - 1), n, n + 1}):
        for i in range(len(palabras) - tam + 1):
            ventana = " ".join(palabras[i:i + tam])
            lv = len(ventana)
            # Cota superior de ratio(): evita calcular ventanas que no pueden ganar
            if 2 * min(lc, lv) / (lc + lv) < max(mejor[0], umbral):
                continue
            r = Levenshtein.ratio(consulta, ventana)
            if r > mejor[0]:
                mejor = (r, i, i + tam)
    return mejor


def _contexto(texto_original, inicio, fin):
    palabras = texto_original.split()
    a = max(0, inicio - CONTEXTO_PALABRAS)
    b = min(len(palabras), fin + CONTEXTO_PALABRAS)
    antes = " ".join(palabras[a:inicio])
    coincide = " ".join(palabras[inicio:fin])
    despues = " ".join(palabras[fin:b])
    return (("… " if a > 0 else "") + antes, coincide,
            despues + (" …" if b < len(palabras) else ""))


def buscar(conn, consulta, umbral=UMBRAL, limite=MAX_RESULTADOS):
    """Busca en el índice almacenado. Devuelve una lista ordenada de dicts."""
    consulta_n = normalizar(consulta)
    if not consulta_n:
        return []

    candidatos = []
    filas = conn.execute(
        """SELECT f.pagina, f.texto_original, f.texto_normalizado,
                  d.nombre, d.url
           FROM fragmentos f JOIN documentos d ON d.id = f.documento_id
           WHERE d.estado_indexacion = 'indexado'"""
    )
    for fila in filas:
        puntuacion, i, j = mejor_ventana(consulta_n, fila["texto_normalizado"], umbral)
        if puntuacion >= umbral:
            candidatos.append((puntuacion, len(fila["texto_normalizado"]), fila, i, j))

    # Mayor puntuación primero; a igualdad, el fragmento más corto
    candidatos.sort(key=lambda c: (-c[0], c[1]))

    resultados = []
    for puntuacion, _, fila, i, j in candidatos[:limite]:
        antes, coincide, despues = _contexto(fila["texto_original"], i, j)
        resultados.append({
            "nombre": fila["nombre"],
            "pagina": fila["pagina"],
            "url": fila["url"],
            "antes": antes,
            "coincidencia": coincide,
            "despues": despues,
            "puntuacion": puntuacion,
            "porcentaje": round(puntuacion * 100),
        })
    return resultados
