# CleanDataBot — calidad de datos con aprobación humana

Prototipo académico con React + TypeScript + Vite y FastAPI + pandas + RapidFuzz. Permite cargar CSV/Excel, analizar problemas y acumular correcciones en una versión de trabajo antes de descargar un único CSV.

## Ejecutar en desarrollo

Requiere Python 3.10 o superior y Node.js compatible con la versión instalada de Vite. Los archivos `run_backend.bat` y `run_frontend.bat` siguen disponibles.

```powershell
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

En otra terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Abrir la dirección indicada por Vite, normalmente `http://localhost:5173`. Para ejecutar sin las dependencias de pruebas se puede instalar `backend/requirements.txt`.

El frontend usa `VITE_API_URL` o `http://localhost:8000`. El backend permite configurar `CORS_ORIGINS` como lista separada por comas; elimina espacios y entradas vacías. Sin esa variable conserva `http://localhost:5173` y `http://127.0.0.1:5173`.

## Flujo integrado

1. **Cargar y analizar.** Elegir un archivo o el ejemplo existente de 50 registros (`frontend/public/clientes_demo.csv`). Se conservan dos copias independientes: original y trabajo.
2. **Consultar problemas.** Perfil por columna, tipos inferidos, vacíos, completitud y valores distintos. **Ver valores vacíos** filtra todo el dataset de trabajo, incluidos registros posteriores a la vista previa de 50 filas.
3. **Limpiar texto.** Seleccionar columnas, previsualizar recorte de extremos, reducción de espacios repetidos y mayúsculas/minúsculas. Aprobar celdas individuales o todas las propuestas y pulsar **Aplicar cambios aprobados**.
4. **Corregir variantes por grupos.** Buscar grupos en una columna, revisar cantidades, elegir un valor canónico existente o escribirlo manualmente. Excluir variantes cuando corresponda y comprobar la cantidad real de celdas que cambiarán antes de **Aprobar y aplicar grupo**.
5. **Resolver duplicados.** Comparar todos los campos y sus diferencias. Elegir conservar una fila o conservar ambas como registros diferentes. **Confirmar decisión** prepara la decisión; **Aplicar decisiones confirmadas** modifica el trabajo. Las decisiones incompatibles se rechazan y se pueden deshacer antes de aplicarlas.
6. **Revisar el resultado actualizado.** Todos los módulos consultan el trabajo vigente. Cada aplicación actualiza indicadores, perfiles, vista previa y filtros.
7. **Descargar dataset corregido.** La acción principal descarga el estado acumulado en CSV UTF-8 con BOM. Descargar no aprueba ni aplica operaciones; repetirlo devuelve el mismo contenido mientras no se apliquen cambios nuevos.

La estandarización individual por coincidencia difusa se conserva: buscar similitudes, aprobar o rechazar cada propuesta y aplicar solo las aprobadas. Este módulo cambia valores y nunca elimina filas.

## Grupos y alcance de las equivalencias

La normalización compara mayúsculas/minúsculas, tildes y espacios. Conserva las variantes originales en la previsualización. Un grupo equivalente por normalización se distingue de una **propuesta aproximada**, que muestra el parecido textual de cada variante con el ancla. Ese porcentaje no es una probabilidad de identidad.

En grupos aproximados, las variantes aproximadas empiezan excluidas: el usuario debe incluirlas expresamente. Las equivalentes por normalización aparecen seleccionadas, pero requieren la aprobación del grupo. Elegir el canónico no aprueba por sí solo la operación.

El ancla propuesta es la variante más frecuente de su clase normalizada; los empates conservan el orden de aparición. Los grupos aproximados son estrellas de comparaciones directas con esa ancla: A≈B y B≈C nunca implican agrupar automáticamente A con C. Cada clase normalizada pertenece como máximo a una estrella aproximada por búsqueda, para evitar respuestas cuadráticas con variantes muy parecidas. Las equivalencias normalizadas también se muestran por separado. Una nueva búsqueda puede producir propuestas distintas después de aplicar cambios.

Las reglas aprobadas están limitadas a **esa columna y esas variantes exactas**. Todas sus apariciones seleccionadas cambian en el trabajo actual; las que ya coinciden con el canónico y las excluidas permanecen iguales. El número de filas no cambia. Por ejemplo, 20 `Bogotá`, 12 `BOGOTA` y 8 `bogota`, con canónico `Bogotá`, producen **20 celdas modificadas**, conservando las 40 filas.

Las equivalencias aprobadas se pueden consultar durante el análisis activo. Son un registro de las operaciones aprobadas, no reglas automáticas para futuros archivos. Se pierden al reiniciar; persistirlas y reutilizarlas entre sesiones queda pendiente.

## Consistencia, filas estables y errores

El índice interno se asigna al cargar y no se renumera tras eliminar filas. La interfaz muestra **Registro original** para que una fila siga siendo identificable. Es metadato, no una columna del dataset; la exportación usa `index=False`.

Cada cambio real incrementa `revision`. Las propuestas de limpieza, grupos, coincidencias y duplicados guardan la revisión sobre la que se generaron. Aplicar sobre otra revisión, reenviar una aprobación consumida o usar una propuesta reemplazada devuelve HTTP **409**, con `detail.code = stale_proposal`. El frontend actualiza el estado y descarta las propuestas anteriores. Las decisiones incompatibles de duplicados también devuelven 409, pero conservan la revisión y las decisiones válidas para que el usuario pueda corregirlas.

Las operaciones se validan completas y se preparan en una copia. El cálculo del resumen también debe terminar antes de publicar el trabajo nuevo. Un bloqueo por análisis serializa aprobaciones concurrentes: dos aplicaciones de una misma propuesta no se ejecutan dos veces. Los formularios muestran procesamiento, deshabilitan controles y tienen una protección síncrona contra envíos duplicados.

Una operación sin cambios reales no incrementa la revisión ni los contadores. Confirmar decisiones de duplicados no modifica datos hasta aplicarlas. Los pares pendientes no ordenan eliminar registros; una eliminación explícita en otro par sí puede afectar uno de esos registros. **Conservar ambos** protege las dos filas dentro de la revisión vigente. Cambiar datos invalida esa revisión; la próxima búsqueda requiere decisiones nuevas. No existe deshacer global después de aplicar: se puede volver a cargar el original para iniciar otro análisis.

## Definición de los indicadores

- **Registros originales:** filas leídas al cargar.
- **Registros actuales:** filas que permanecen en el trabajo.
- **Celdas modificadas:** diferencias actuales frente al original, en las filas que aún existen. Cada celda cuenta una vez aunque haya sido transformada varias veces; si vuelve a su valor original deja de contar. Las celdas de filas eliminadas no se incluyen.
- **Filas eliminadas:** originales menos actuales. Se cuentan aparte; varias decisiones sobre la misma eliminación no la duplican.
- **Valores vacíos:** nulos y cadenas vacías o con solo espacios.
- **Completitud:** `100 × celdas no vacías / celdas actuales`; por columna usa sus filas actuales. En un conjunto sin celdas se define como 100 %.
- **Duplicados exactos:** filas repetidas después de la primera aparición, calculadas sobre los valores actuales de todas las columnas.
- **Valores únicos:** valores distintos no vacíos de cada columna. El tipo es inferido, no una validación semántica del contenido.

El aviso de cada aplicación informa celdas modificadas y filas eliminadas **en esa operación**. El resumen cuenta el estado neto. Eliminar una fila completa puede reducir la completitud al cambiar el denominador; los porcentajes no se fuerzan a mejorar.

## Contrato HTTP

Todas las rutas siguientes están bajo `/api/analyses/{analysis_id}` salvo la carga:

| Acción | Método y ruta | Contrato principal |
|---|---|---|
| Cargar | `POST /api/analyze` | Multipart `file`; devuelve resumen con `revision=0` |
| Estado actual | `GET /api/analyses/{analysis_id}` | Resumen, perfiles, números estables y equivalencias |
| Vacíos | `GET .../empty-rows?column=...` | `revision`, `rows`, `row_numbers`, `total` |
| Previsualizar texto | `POST .../text-cleanup/preview` | `columns`, `trim`, `collapse_spaces`, `letter_case` |
| Aplicar texto | `POST .../text-cleanup/apply` | `preview_id`, `revision`, `approved_change_ids` |
| Similitudes individuales | `POST .../matches` | `column`, `threshold`; devuelve `proposal_id`, `revision`, `matches` |
| Aplicar similitudes | `POST .../matches/apply` | `proposal_id`, `revision`, `approved_match_ids` |
| Buscar grupos | `POST .../groups/search` | `column`, `threshold`; devuelve grupos, cantidades y relaciones |
| Aplicar grupo | `POST .../groups/apply` | `proposal_id`, `revision`, `group_id`, `variants`, `canonical` |
| Buscar duplicados | `POST .../duplicates/search` | `column` opcional, `threshold`; devuelve `review_id` y `revision` |
| Confirmar/deshacer | `POST .../duplicates/decision` | `review_id`, `revision`, `pair_id`, `action` |
| Aplicar duplicados | `POST .../duplicates/apply` | `review_id`, `revision`; aplica solo decisiones confirmadas |
| Descargar | `GET .../export` | CSV del trabajo; cabecera `X-Dataset-Revision`; sin efectos secundarios |

Las aplicaciones devuelven `{analysis, changed_values, deleted_rows}`. Se retiraron las exportaciones por módulo y el antiguo `POST .../export` que aplicaba correcciones durante la descarga. Los clientes deben usar las rutas `apply` y la descarga `GET`.

## Verificación

```powershell
cd backend
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -m unittest discover -v
./.venv/Scripts/python.exe benchmark.py --output benchmark_after.json --repeats 3
```

```powershell
cd frontend
npm ci
npm run build
```

Las pruebas existentes se conservaron y adaptaron al contrato de aplicación. La suite cubre original intacto, recorrido acumulado, exclusión de variantes, límites por columna, canónico manual, ausencia de agrupación transitiva, identificadores tras eliminaciones, exportación repetida, aprobaciones concurrentes, propuestas obsoletas, incompatibilidades y atomicidad. `TestClient` verifica el contrato HTTP usado por React, incluida carga multipart, filtros y CSV final.

Resultados reales, entorno, mediciones antes/después y alcance de la comprobación están en [docs/verification.md](docs/verification.md). El caso pequeño `frontend/public/grupos_demo.csv` se añadió para una demostración determinista; el ejemplo de 50 registros existente se conserva sin cambios.

## Prueba manual y guion de video

1. Mostrar **Ejemplo de 50 registros**, revisar indicadores, perfil y el filtro de vacíos. Explicar que estos datos proceden del trabajo vigente.
2. Cambiar al **Ejemplo de grupos** (8 filas) para que el efecto sea fácil de contar.
3. En limpieza, conservar solo `nombre`, activar recortar extremos y reducir espacios, previsualizar, aprobar todos y aplicar: **5 celdas modificadas** en esa operación.
4. Buscar grupos por `ciudad`. Elegir `Bogotá`; mostrar 3 apariciones de `Bogotá`, 2 de `BOGOTA` y 2 de `bogota`. Excluir temporalmente `BOGOTA`: el contador baja de 4 a 2. Volver a incluirla y aplicar: **4 cambios**, sin eliminar filas.
5. Buscar **Solo duplicados exactos**. Comparar registros originales **1 y 7**, elegir conservar 1, confirmar y aplicar: **1 fila eliminada**. Antes de aplicar también se puede mostrar **Conservar ambos** o **Deshacer decisión**.
6. Mostrar el resumen: **8 originales, 7 actuales, 8 celdas modificadas netas, 1 eliminada y 0 duplicados exactos**. La completitud pasa de 97,5 % a 97,14 % porque se eliminó una fila completa. El filtro de `correo` sigue mostrando el registro original 4.
7. Descargar un único CSV y abrirlo: `Ana María` está limpio, hay seis ciudades `Bogotá`, el duplicado ya no aparece y no hay columna interna adicional. Descargar nuevamente no cambia el resultado.
8. Abrir el CSV fuente para mostrar que conserva ocho filas y sus variantes originales. Explicar que las equivalencias duran solo durante el análisis activo.

Guion breve: “Cargamos y vemos problemas reales. Revisamos el antes y después antes de aplicar. Una aprobación corrige varias apariciones de ciudad y respeta las variantes excluidas. Resolver duplicados es una decisión independiente. El resumen se recalcula sobre el trabajo actual. Esta descarga reúne todas las correcciones y conserva el archivo original”.

## Límites vigentes

- Máximo 10 MB y 2.000 filas; entrada CSV/Excel y salida CSV.
- Estado temporal en memoria, un solo proceso/worker. Reiniciar el backend pierde análisis, decisiones y equivalencias. No hay base de datos ni historial persistente.
- La revisión de registros propone duplicados exactos y la mejor coincidencia anterior por registro, no todas las combinaciones posibles.
- La estandarización individual omite filas duplicadas exactas; la corrección por grupos sí alcanza todas las apariciones aprobadas. La similitud sigue siendo textual y requiere revisión humana.
- El algoritmo de grupos evita cadenas transitivas; no implementa clustering semántico. Buscar nuevamente después de aplicar puede proponer otros grupos.
- Las mediciones publicadas describen únicamente los tamaños y características probados. Muchos valores distintos pueden incrementar el costo de las comparaciones.
- Sin autenticación, despliegue nuevo, modelos de IA adicionales, PDF, Word ni procesamiento de cartas. Esta entrega se verifica en desarrollo; el despliegue se gestiona posteriormente.
