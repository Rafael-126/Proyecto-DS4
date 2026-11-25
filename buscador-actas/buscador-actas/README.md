# Buscador de Actas

Sistema en Python que recopila actas en PDF publicadas en sitios web, indexa su contenido y permite consultarlo desde un buscador web hecho con Flask. La búsqueda tolera pequeños errores de escritura gracias a la similitud de Levenshtein.

Proyecto final · Universidad de Sonora · Ingeniería en Sistemas

## Integrantes

| Nombre completo | Usuario de GitHub | Módulos principales |
|---|---|---|
| Rafael Justiniani Uriarte | @Rafael-126 | completar |
| Miguel Angel Arvayo Gracia | @MIKE06-GR | completar |
| Mario Alexis Garcia Rodriguez | @MarioAl3xis | completar |

## Descripción

Flujo del sistema: **registro de URLs → descarga de PDFs → indexación → búsqueda y resultados**

- **Scraping** (`scraper.py`): parte de las URLs registradas en `config/urls.json` (por defecto, la página de actas de la Facultad Interdisciplinaria de Ingeniería), sigue los enlaces necesarios hasta encontrar PDFs y los descarga.
- **Indexación** (`indexer.py`): extrae el texto de cada PDF, lo divide en fragmentos y lo guarda en SQLite junto con su nombre original y su URL.
- **Búsqueda** (`app.py` + `search.py`): la aplicación Flask compara la consulta contra el índice almacenado y muestra los resultados ordenados por similitud. Las búsquedas nunca ejecutan el scraping.

## Estructura del repositorio

```
buscador-actas/
├── app.py            # Aplicación Flask
├── scraper.py        # Recorrido de enlaces y descarga de PDFs
├── indexer.py        # Extracción de texto e indexación
├── search.py         # Normalización y similitud (Levenshtein)
├── db.py             # Conexión y esquema SQLite
├── config/
│   └── urls.json     # URLs registradas y parámetros del recorrido
├── downloads/        # PDFs descargados (se crea sola)
├── data/
│   └── actas.db      # Base de datos SQLite (se crea sola)
├── templates/        # Plantillas HTML (Bootstrap)
├── requirements.txt
└── README.md
```

## Instalación

Requisitos: Python 3.10 o superior.

```bash
git clone <URL-DEL-REPOSITORIO>
cd buscador-actas

python -m venv venv
# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
```

## Uso

### 1. Descargar actas
```bash
python scraper.py run
```
Recorre todas las URLs registradas, descarga los PDFs nuevos y muestra un resumen (descargados, ya existentes, fallidos).

### 2. Indexar
```bash
python indexer.py
```
Extrae el texto de los PDFs que aún no están indexados. Al final reporta los PDFs de los que no se pudo extraer texto. Con `--reindexar` se vuelven a procesar todos.

### 3. Buscar
```bash
python app.py
```
Abre http://127.0.0.1:5000 en el navegador, escribe la consulta y presiona **Buscar**.

### Actualizar (nuevas actas publicadas)
Basta con repetir los pasos 1 y 2. Solo se descargan e indexan los documentos nuevos.
```bash
python scraper.py run
python indexer.py
```

### Agregar nuevas URLs
Sin modificar el código:
```bash
python scraper.py add-url "https://ejemplo.com/pagina-de-actas"
python scraper.py list-urls
python scraper.py run
python indexer.py
```
Las URLs quedan guardadas en `config/urls.json` y se reutilizan en ejecuciones posteriores.

## Almacenamiento y control de archivos

- **PDFs:** se guardan en `downloads/`.
- **Base de datos** (`data/actas.db`, SQLite), con dos tablas:
  - `documentos`: URL original (única), texto del enlace (nombre del acta), ruta local, hash del contenido, fecha de descarga y estado de indexación (`pendiente`, `indexado`, `sin_texto`, `error`).
  - `fragmentos`: documento, número de página, texto original y texto normalizado.
- **Sin duplicados:** la URL del PDF es clave única. Antes de descargar se consulta la tabla y se verifica que el archivo exista en disco; si el registro existe pero el archivo falta, se vuelve a descargar y a indexar.
- **Nombres repetidos:** los archivos se guardan como `<hash-corto-de-URL>_<nombre>.pdf`, de modo que dos documentos distintos con el mismo nombre no se sobrescriben.
- **Indexación incremental:** solo se procesan los documentos marcados como `pendiente`.
- **PDFs sin texto** (por ejemplo, escaneados): se marcan con estado `sin_texto` y se listan al terminar la indexación.

## Control del recorrido

Parámetros en `config/urls.json`:

- **Profundidad máxima de enlaces:** 3 (`max_profundidad`).
- **Máximo de páginas por URL inicial:** 150 (`max_paginas_por_url`).
- **Pausa entre solicitudes:** 1 segundo (`pausa_segundos`).
- **Palabras clave:** solo se siguen páginas cuya URL o texto de enlace contenga alguna (por defecto `"acta"`, sin importar acentos ni mayúsculas). Con `[]` se siguen todas las páginas del dominio.
- Conjunto de URLs visitadas para evitar ciclos.
- Solo se siguen enlaces dentro del dominio de la URL inicial; los PDFs enlazados se descargan aunque estén en otro dominio.
- Errores de conexión, enlaces rotos y descargas fallidas se registran y el proceso continúa.

## Criterio de similitud y ordenamiento

- **Normalización:** tanto la consulta como los fragmentos se pasan a minúsculas, sin acentos y con espacios colapsados.
- **Comparación:** cada fragmento normalizado se recorre con una ventana deslizante de N palabras, donde N es el número de palabras de la consulta (con variantes de ±1). Cada ventana se compara con la consulta usando `Levenshtein.ratio()`, que devuelve un valor entre 0 y 1.
- **Relevancia:** la puntuación de un fragmento es la mejor ratio obtenida entre sus ventanas. Si la consulta aparece tal cual dentro del texto, la puntuación es 1.0.
- **Umbral:** se descartan los fragmentos con puntuación menor a 0.75 (`UMBRAL` en `search.py`).
- **Orden:** de mayor a menor puntuación. A igualdad, primero el fragmento más corto.
- **Presentación:** se muestra el texto original alrededor de la mejor ventana (15 palabras de contexto por lado), con la coincidencia resaltada y la puntuación en porcentaje.
- **Casos especiales:** la consulta vacía muestra un mensaje pidiendo escribir algo, y si no hay coincidencias sobre el umbral se informa claramente.

## Resultados mostrados

Para cada coincidencia:

- Nombre original del acta (texto del enlace de origen).
- Fragmento con contexto y número de página.
- Enlace a la URL original del PDF.
- Indicador de similitud (porcentaje).

## Limitaciones conocidas

- Los PDFs escaneados (solo imagen) no se pueden indexar sin OCR.
- La búsqueda compara contra todos los fragmentos, así que con un índice muy grande puede volverse lenta.
- No se interpretan sinónimos: solo se toleran variaciones de escritura.
- La comparación es contigua: una consulta de varias palabras solo coincide si las palabras aparecen juntas y en ese orden (con tolerancia de ±1 palabra).
- El scraper depende de que los PDFs estén enlazados con `<a href="...pdf">` en HTML; no ejecuta JavaScript.
- [agregar las que se descubran durante las pruebas]

## Extras implementados

- Interfaz con Bootstrap 5, diseño adaptable a móviles, resultados con la coincidencia resaltada y mensajes claros.

## Dependencias

Ver `requirements.txt`: Flask, requests, beautifulsoup4, pypdf, Levenshtein.
