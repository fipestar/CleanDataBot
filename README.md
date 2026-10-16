# CleanDataBot — prototipo funcional para clase

Este prototipo demuestra un solo flujo del MVP: cargar CSV/Excel, perfilar los datos, revisar posibles coincidencias con *fuzzy matching*, aprobar o rechazar sugerencias y descargar una copia corregida.

## Tecnologías

- Frontend: React + TypeScript + Vite.
- Backend: FastAPI + Python.
- Análisis: pandas + RapidFuzz.
- Formatos de entrada: CSV y Excel (`.xlsx` / `.xls`).
- Salida de la demo: CSV.

## Ejecutar en Windows

Requiere Python 3.10 o superior y Node.js instalado.

1. Abre `run_backend.bat` en una terminal. La primera ejecución instala las dependencias y levanta la API en `http://localhost:8000`.
2. Abre otra terminal y ejecuta `run_frontend.bat`. Vite mostrará la dirección local; normalmente `http://localhost:5173`.
3. En la pantalla, pulsa **Usar dataset de ejemplo** para iniciar la demostración rápidamente, o carga un archivo propio.

También puedes ejecutar los comandos manualmente:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

En otra terminal:

```bash
cd frontend
npm install
npm run dev
```

## Guion breve para presentar

1. Cargar el dataset de ejemplo.
2. Explicar el resumen: número de registros, columnas, nulos y duplicados exactos.
   Revisar el **Perfil de columnas**: tipo de dato inferido, valores vacíos, porcentaje de completitud y cantidad de valores únicos no vacíos. Los nulos y las celdas con solo espacios cuentan como vacíos.
   Pulsar **Ver valores vacíos** en una columna para mostrar todos sus registros afectados, incluso los que estén después de los primeros 50. **Quitar filtro** restaura la vista previa.
3. Buscar coincidencias por la columna `nombre`.
4. Aprobar una sugerencia y rechazar otra.
5. Descargar la copia corregida y explicar que el original no se modifica.

## Alcance intencional de esta demo

- Los análisis se guardan temporalmente en memoria y se pierden al reiniciar el backend.
- No hay inicio de sesión, base de datos ni historial persistente en este fragmento.
- El sistema compara una columna de texto por búsqueda y propone reemplazar el valor de una fila por el valor de otra fila similar.
- El umbral de similitud es configurable. Un puntaje alto no prueba por sí mismo que dos registros pertenezcan a la misma persona; la decisión queda en manos del usuario.
- No se fusionan filas ni se ejecutan correcciones sin aprobación.
- La revisión de duplicados permite omitir registros de una copia únicamente mediante decisiones confirmadas.
- La copia corregida se exporta como CSV para facilitar la demostración.

Esta demo sirve para validar el flujo principal del MVP; todavía no representa el producto completo ni reemplaza la persistencia prevista con MySQL.

## Verificación del perfil y filtro

Desde `backend`, ejecutar `python -m unittest test_profiles -v`. Las pruebas cubren estadísticas, celdas con espacios, columnas vacías o completas y registros afectados fuera de la vista previa.

## Limpieza de texto con aprobación

En **Limpieza de texto**, seleccionar una o varias columnas y activar el recorte de espacios en los extremos, la reducción de espacios repetidos o la conversión a mayúsculas/minúsculas. Se ejecutan en ese orden; cada opción puede usarse por separado.

**Previsualizar cambios** muestra todos los valores que cambiarán, con su registro, columna, valor original y propuesto. Las comillas permiten distinguir espacios en los extremos. Los nulos y los valores que no son texto se conservan. Cambiar opciones invalida la previsualización.

**Aprobar y descargar copia limpia** aplica exactamente la propuesta revisada y descarga un CSV nuevo con sufijo `_limpio`. Esta copia contiene la limpieza de texto seleccionada; las sugerencias de similitud cuentan con su propia exportación. El dataset cargado permanece intacto.

Desde `backend`, ejecutar `python -m unittest test_profiles test_text_cleanup -v` para verificar ambas funciones.

## Comparar duplicados y registros similares

En **Comparación de registros**, elegir una columna de texto y el umbral, o **Solo duplicados exactos**. La búsqueda incluye duplicados exactos y la mejor coincidencia anterior de cada registro. Cada par muestra todos los campos y resalta las diferencias con color y una etiqueta.

Elegir **Conservar registro…** o **Son registros diferentes: conservar ambos** y pulsar **Confirmar decisión**. La selección por sí sola no cambia la exportación. **Deshacer decisión** revierte la confirmación. Las decisiones que intenten eliminar un registro que otra decisión exige conservar se rechazan sin modificar las confirmaciones anteriores.

**Exportar decisiones confirmadas** descarga una copia `_revisado.csv`: omite únicamente los registros cuya eliminación fue confirmada. Sin confirmaciones, conserva todo el dataset. Los pares pendientes conservan ambos registros, salvo que otra decisión confirmada elimine uno de ellos. Marcar un par como diferente protege ambos registros. El original permanece intacto.

Cambiar los criterios o volver a buscar inicia una revisión nueva. Esta exportación aplica las decisiones sobre registros completos; la limpieza de texto y la estandarización de valores mantienen sus exportaciones separadas.

Ejecutar las comprobaciones desde `backend`: `python -m unittest test_profiles test_text_cleanup test_duplicates -v`.
