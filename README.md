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

## Limpieza automática

La sección **Limpieza automática** permite completar cargar → analizar → configurar reglas → previsualizar → aplicar los casos seguros → revisar excepciones → descargar. Reutiliza la versión de trabajo, `clean_text`, la comparación textual, las revisiones y el `commit` atómico existentes. Los módulos manuales siguen disponibles y sus cambios se acumulan con esta limpieza en el CSV principal.

### Configuración por archivo

- **Asociar campos:** seleccionar las columnas de nombre, correo y teléfono, y marcar los identificadores del cliente. Se sugieren encabezados conocidos como `full_name`, `nombre completo`, `email`, `correo`, `phone`, `document` o `customer_id`. Las asociaciones ambiguas quedan sin seleccionar y muestran un aviso.
- **Columnas de texto:** activar o desactivar recorte de extremos, reducción de espacios repetidos y reemplazos explícitos variante → canónico. La configuración inicial incorpora las equivalencias ya aprobadas en el análisis. No se elige un canónico por fuzzy matching sin una regla configurada.
- **Umbrales:** 97 % de parecido de nombre para fusión automática por defecto, configurable entre 90 y 100; 85 % para presentar candidatos de revisión, configurable entre 60 y el umbral automático. Son medidas de parecido textual, no probabilidades de identidad.
- **Columnas técnicas opcionales:** un ID interno distinto bloquea la fusión por defecto, igual que cualquier otro campo no vacío contradictorio. Solo puede ignorarse explícitamente si el usuario sabe que no identifica al cliente. No se pueden ignorar columnas asociadas a nombre, contacto o identificadores. En columnas ignoradas se conserva el valor de la primera fila y no se completan campos desde otras filas.

Si falta nombre o no se ha asociado correo ni teléfono, se omite la fusión de clientes y el resultado explica el motivo. La normalización configurada y la eliminación de duplicados exactos siguen funcionando. Un nombre vacío o no textual tampoco cumple la regla automática para ese registro.

### Reglas de eliminación y combinación

1. Se eliminan filas exactamente iguales, conservando la primera según el orden original.
2. Se ejecuta la normalización y se aplican únicamente los reemplazos de cada columna. Los valores canónicos también pasan por la normalización configurada. Las cadenas de reemplazos explícitos se resuelven hasta su destino final; los ciclos y canónicos contradictorios se rechazan antes de modificar el trabajo.
3. Se buscan nuevamente duplicados exactos después de estandarizar.
4. Para fusionar clientes debe existir nombre suficientemente parecido **y** correo o teléfono exacto no vacío. Dos vacíos nunca constituyen evidencia. La comparación de contacto quita espacios exteriores; no elimina signos del teléfono, no normaliza dominios, no ignora mayúsculas del correo y no infiere países.
5. Cualquier contradicción no vacía en identificadores, contactos u otros campos no ignorados bloquea la combinación. El nombre puede variar dentro del umbral establecido; se conserva el nombre de la primera fila.
6. Cada componente de contactos debe cumplir la regla **entre todos sus pares originales**, antes de completar campos. A comparte correo con B y B comparte teléfono con C no autoriza fusionar A, B y C si A y C carecen de evidencia directa.
7. En un caso seguro se conserva la primera fila y se completan exclusivamente sus campos vacíos con datos compatibles del resto. Se elimina cada fila absorbida una sola vez. Una pasada final comprueba exactos tras completar campos.

Los conflictos de un grupo bloquean toda su fusión automática: no se completan unos campos para luego descubrir un conflicto en otro miembro. La operación se prepara en una copia y se publica únicamente si todas las validaciones y métricas terminan correctamente. El original permanece intacto.

### Excepciones agrupadas

Después de aplicar aparecen grupos de candidatos, no cientos de pares repetidos. Los vínculos de nombre o contacto pueden conectar varios registros para **presentarlos juntos**, pero esa conexión no declara que sean una sola entidad y nunca autoriza una fusión automática. Cada registro aparece en un único grupo pendiente.

La vista muestra todos los campos, motivos y columnas contradictorias. Se puede:

- Elegir **Son diferentes: conservar todos**. La decisión se registra y se respeta en ejecuciones posteriores mientras esos registros conserven los mismos valores.
- Elegir una fila que debe conservarse, marcar únicamente las filas que se desea eliminar y confirmar esa eliminación. Los registros no seleccionados permanecen; no se copian ni sobrescriben campos en esta eliminación manual.

Después de una decisión se recalculan los grupos sobre las filas actuales, sin ejecutar transformaciones ni nuevas fusiones. Si se elimina el puente de una cadena de candidatos, los restantes pueden dejar de constituir un grupo. Los planes anteriores quedan invalidados. Si se cambia el trabajo desde otro módulo, las excepciones anteriores se muestran como históricas y deben generarse nuevamente.

### Resumen y trazabilidad

Todos los contadores proceden del procesamiento real:

- **Celdas normalizadas:** celdas cuyo texto cambió por espacios en la ejecución.
- **Variantes estandarizadas:** celdas reemplazadas por un canónico configurado.
- **Duplicados eliminados:** exactos eliminados más filas absorbidas por una fusión segura de clientes.
- **Campos vacíos completados:** asignaciones realizadas al registro conservado.
- **Grupos pendientes:** grupos actuales aún sin resolver. Se actualizan al decidir sobre excepciones.

Los pasos se cuentan en el momento de ejecutarse: una celda puede normalizarse y luego estandarizarse, y una fila transformada puede resultar duplicada y eliminarse. Estos contadores no se suman al indicador neto de celdas del dataset. Las eliminaciones manuales de excepciones permanecen separadas de las automáticas y se reflejan en el resumen general.

El registro del análisis conserva cada regla, registro original, columna, antes/después, registro conservado o donante y, para fusiones, contactos coincidentes, parecido de nombre, umbral y columnas técnicas ignoradas. Las decisiones manuales también quedan registradas. Los contadores de la última ejecución no acumulan operaciones repetidas; el registro previo no se pierde al volver a limpiar.

Repetir con la misma configuración produce cero modificaciones adicionales en un trabajo ya limpio. La descarga principal es la misma acción `GET .../export` de todo el trabajo: no vuelve a ejecutar reglas ni agrega columnas internas. Las reglas, planes y trazas se conservan solo en la sesión en memoria.

### API y comprobación

Bajo `/api/analyses/{analysis_id}`:

| Acción | Método y ruta | Cuerpo / resultado |
|---|---|---|
| Sugerir configuración | `GET .../auto-cleanup/config` | `config` y avisos de asociaciones ambiguas |
| Preparar ejecución | `POST .../auto-cleanup/preview` | `revision`, `column_rules`, `fields`, umbrales, `merge_clients`, `ignored_columns`; devuelve `plan_id`, contadores, eventos y grupos |
| Aplicar plan seguro | `POST .../auto-cleanup/apply` | `plan_id`, `revision`; devuelve `{analysis, changed_values, deleted_rows}` |
| Resolver excepción | `POST .../auto-cleanup/review` | `run_id`, `group_id`, `revision`, `action`; para `remove_selected`, `keep_row` y `remove_rows` |

`analysis` incluye `automatic_report` y `automatic_audit`. Un plan reemplazado, aplicado o de otra revisión devuelve 409 con `stale_proposal`. Una asociación inválida, ciclo o decisión que eliminaría el registro conservado se rechaza sin aplicar cambios parciales.

Desde `backend`, ejecutar `./.venv/Scripts/python.exe -m unittest discover -v`; desde `frontend`, ejecutar `npm run build`. Las pruebas de `backend/test_auto_cleanup.py` cubren duplicados reales, nombres parecidos de personas distintas, vacíos, identificadores y otros campos contradictorios, cadenas transitivas, original intacto, repetición, reglas inválidas, estabilidad de filas y el contrato HTTP completo.

### Demostración reproducible

1. Abrir **Ejemplo de limpieza automática** (`clientes_automatico_demo.csv`, datos ficticios).
2. Comprobar las asociaciones `full_name`, `email`, `phone` y el identificador `document`.
3. En reglas de `city`, agregar `BOGOTA` → `Bogotá`. Mantener recorte y reducción de espacios.
4. Previsualizar y aplicar. En este archivo el resultado observado fue: una celda normalizada, una estandarizada, un exacto eliminado, un cliente absorbido y un teléfono completado; quedaron siete filas y tres grupos pendientes.
5. Revisar Andrea, Carlos y Laura: contactos distintos, contactos vacíos o documentos contradictorios impiden su eliminación automática. Marcarlos como diferentes conserva todos.
6. Previsualizar otra vez: en este recorrido no hubo cambios adicionales y se respetaron las tres decisiones. Descargar el CSV acumulado y compararlo con el archivo original de nueve registros.

Las cantidades del ejemplo son resultados de esa ejecución, no constantes de interfaz. Evidencia y detalles: [docs/automatic-cleanup.md](docs/automatic-cleanup.md).

### Límites específicos

La regla es deliberadamente conservadora: un correo o teléfono compartido puede pertenecer a distintas personas y cualquier conflicto requiere revisión. No valida identidad, titularidad de contactos, direcciones ni documentos. Las asociaciones por encabezado son sugerencias editables, no inferencias semánticas. Se mantienen los límites de 2.000 filas y 10 MB, memoria de un único worker y exportación CSV. La inferencia de tipos de pandas al cargar sigue vigente; conviene revisar columnas como teléfonos e identificadores cuando el archivo usa formatos especiales o ceros iniciales. No se promete que los grupos de revisión correspondan a una entidad real.
