# Verificación del flujo acumulado — 11 de noviembre de 2026

## Recorrido y evidencia

Historia verificada: cargar el CSV desde React → analizar con FastAPI → revisar/aplicar limpieza → aprobar variantes de una columna → confirmar/aplicar eliminación de un duplicado → consultar métricas y filtros recalculados → descargar el estado de trabajo acumulado.

| Frontera | Evidencia observada |
|---|---|
| Interfaz | Navegador local en `http://127.0.0.1:5173`; selección de ejemplo, previsualización y aprobación visibles |
| Cliente → API | Pruebas `TestClient` de multipart, GET del estado/filtros, propuestas, decisiones, aplicaciones y CSV; mismas rutas y cargas usadas por React |
| API → trabajo | Pruebas de original intacto, revisión incremental, errores atómicos, eliminación con índice estable y aprobaciones concurrentes |
| Respuesta → interfaz | Tras aplicar: 8 registros originales, 7 actuales, 8 celdas modificadas y 1 fila eliminada; completitud 97,14 % |
| Filtro actualizado | `correo` muestra exclusivamente el registro original 4, con nombre `Pedro` ya limpio |
| Descarga | `grupos_demo_corregido.csv` abierto y verificado: 7 filas, `Ana María`, seis ciudades `Bogotá`, sin columna de índice |
| Consola del navegador | Consulta de niveles error/warn sin entradas durante el recorrido |
| Original | Pruebas de comparación profunda de `original_frame` y de los bytes de ambos CSV fuente |

La exclusión se comprobó en la interfaz: desmarcar `BOGOTA` redujo los cambios previstos de 4 a 2; se volvió a incluir para completar el recorrido. Se inspeccionó la descarga creada por el navegador, además de comprobar los bytes del CSV por HTTP. [Captura del resumen](working-dataset.png).

Los servidores se iniciaron solo en desarrollo. No se creó despliegue ni se modificaron servicios externos.

## Comandos y resultados

Desde `backend`:

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m unittest discover -v
./.venv/Scripts/python.exe benchmark.py --output benchmark_after.json --repeats 3
```

Desde `frontend`:

```powershell
npm run build
```

La suite conserva las 17 pruebas anteriores adaptadas al contrato nuevo y añade pruebas del recorrido acumulado y HTTP. El build ejecuta `tsc -b && vite build`. La versión instalada de Starlette emite un aviso de deprecación sobre su integración de `TestClient` con httpx; las comprobaciones HTTP se ejecutan y se evalúan normalmente.

Resultados finales de la ejecución se indican al final de este documento.

## Mediciones reales

Entorno registrado por el proceso de medición:

- Windows 11: `Windows-11-10.0.26300-SP0`.
- Identificador de procesador reportado por Python: `Intel64 Family 6 Model 154 Stepping 4, GenuineIntel`.
- Python 3.14.7, pandas 2.3.3, FastAPI 0.141.1 y RapidFuzz 3.14.6.
- Estado inicial del repositorio: `b1a1ad1`; medición anterior realizada antes de modificar la búsqueda.
- Tres ejecuciones consecutivas por tamaño, sin calentamiento descartado. Se publica la mediana; las muestras completas quedan en JSON. El equipo no estuvo bajo aislamiento de carga, por lo que son mediciones locales orientativas.

Datos sintéticos reproducibles de `backend/benchmark.py`: 50, 500 y 2.000 filas; seis columnas (`id`, `nombre`, `ciudad`, `correo`, `telefono`, `nota`); ocho cadenas distintas de ciudad, con variantes de tildes, espacios y mayúsculas; nombres repetidos entre 100 bases; correo identificable por índice; teléfono vacío cada siete filas. Cada fila de índice múltiplo de 17, salvo la primera, copia la anterior, creando duplicados exactos. Las búsquedas usan `ciudad` con umbral 85.

Se mide con `time.perf_counter` el manejador real de carga/análisis, incluida lectura y parseo del CSV en memoria, y cada manejador de búsqueda. Se excluyen inicio del intérprete, red/HTTP, representación del navegador, descarga y lectura de Excel. Los valores no son tiempos de respuesta completos del navegador.

Medianas observadas, en milisegundos:

| Filas | Análisis antes | Análisis actual | Similitudes antes | Similitudes actuales | Grupos actuales | Duplicados actuales |
|---:|---:|---:|---:|---:|---:|---:|
| 50 | 6,76 | 6,61 | 2,90 | 0,58 | 0,17 | 0,59 |
| 500 | 11,81 | 8,17 | 243,53 | 2,91 | 0,19 | 5,24 |
| 2.000 | 21,43 | 17,83 | 8.843,75 | 11,33 | 0,36 | 19,91 |

Se conservaron 40, 410 y 1.645 sugerencias individuales respectivamente en estas mediciones. Los grupos fueron dos en cada tamaño. La revisión de registros produjo 47, 497 y 1.997 pares: incluye todas las filas candidatas, sin recortarlas para aparentar rapidez.

### Causa y ajuste

La búsqueda anterior recorría pares de filas y repetía `normalize_for_match` para las mismas ciudades. En 2.000 filas, aunque existían solo ocho cadenas distintas, la mediana de búsqueda fue de 8,84 segundos. Las muestras originales variaron entre 3,94 y 9,00 segundos; se conserva esa variación en los datos publicados.

La búsqueda nueva normaliza cada valor distinto una vez y calcula cada par de cadenas distintas una vez. Cuando aparece una referencia nueva, actualiza las mejores propuestas para apariciones futuras de valores anteriores; conserva el desempate por referencia más antigua. Una prueba contrasta el resultado con una búsqueda exhaustiva sobre 80 filas deterministas. No se limita la cantidad de propuestas individuales.

En duplicados se reutilizan valores normalizados y referencias por cadena. En grupos se comparan clases normalizadas y se evitan cadenas transitivas. Cada clase pertenece a una sola estrella aproximada; esto acota el tamaño de la respuesta de grupos. Las variantes equivalentes por normalización permanecen disponibles por separado.

La mejora medida corresponde a datos con repetición. No se extrapola a archivos mayores de 2.000 filas ni a datasets con todas las cadenas distintas. Una prueba funcional adicional usa 500 ciudades distintas para verificar que todas las variantes de cada grupo se parecen directamente al ancla y que el tamaño total de propuestas no crece como todos los pares. Esa prueba no se presenta como un benchmark de ese tipo de datos.

### Datos y reproducción

- [Muestras anteriores](../backend/benchmark_before.json).
- [Muestras actuales](../backend/benchmark_after.json).
- [Generador y medición](../backend/benchmark.py).

El archivo `benchmark_before.json` se obtuvo ejecutando la búsqueda original en esta sesión, antes de implementar los cambios; `benchmark_after.json` puede regenerarse con el comando publicado. Regenerarlo sobre el equipo de otra persona producirá tiempos distintos.

## Revisión de React

Se aplicó la guía `react-best-practices`: módulos separados para limpieza, duplicados y estandarización; tipos compartidos del contrato; estado de trabajo en un único componente padre; claves por revisión para descartar propuestas; cancelación al desmontar; errores HTTP manejados; formularios deshabilitados durante operaciones y guardia síncrona para envíos duplicados. Los controles tienen etiquetas y las diferencias se identifican con texto además de color.

El despliegue y una persistencia compartida entre workers quedan fuera de esta entrega. Las pruebas manuales y el guion de video están en el README.

## Resultado final

- `python -m unittest discover -v`: **35 pruebas aprobadas**, 0 fallos, 0 errores; duración reportada por unittest: **0,453 s** (sin contar inicio del intérprete).
- `npm run build`: **correcto**, comprobación TypeScript y build de Vite 8.3.0; 21 módulos transformados, fase Vite reportada: **322 ms**.
- CSV pequeño por HTTP y navegador: **8 → 7 filas**, 8 celdas modificadas netas, original intacto.
- CSV existente de 50 filas: recorrido completo por HTTP con limpieza, grupo de ciudad y eliminación confirmada de sus cinco duplicados exactos; CSV final de **45 filas**, 0 duplicados exactos y original intacto.
- `git diff --check`: sin errores de espacios en blanco.
