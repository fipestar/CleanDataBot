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

La sección **Limpieza automática** permite completar cargar → analizar → **Limpiar automáticamente todas las columnas** → descargar. La previsualización es opcional. La revisión por grupos está oculta por el momento y los candidatos dudosos se conservan sin fusionar. Reutiliza la versión de trabajo, `clean_text`, la comparación textual, las revisiones y el `commit` atómico existentes. Los módulos manuales siguen disponibles y sus cambios se acumulan con esta limpieza en el CSV principal.

### Configuración por archivo

- **Asociar campos:** seleccionar las columnas de nombre, correo y teléfono, y marcar los identificadores del cliente. Se sugieren encabezados conocidos como `full_name`, `nombre completo`, `email`, `correo`, `phone`, `document` o `customer_id`. Las asociaciones ambiguas quedan sin seleccionar y muestran un aviso.
- **Todas las columnas compatibles:** se recortan extremos y se reducen espacios repetidos en todas las columnas de texto; los números no se convierten a texto. Los reemplazos explícitos variante → canónico siguen limitados a su columna. La configuración inicial incorpora las equivalencias ya aprobadas en el análisis. No se elige un canónico por fuzzy matching sin una regla configurada.
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

### Motor de excepciones (vista oculta actualmente)

La interfaz actual no muestra grupos pendientes ni exige resolverlos para descargar. Las herramientas manuales están plegadas en una sección opcional. El motor conserva los controles y las rutas de revisión para poder recuperarlos posteriormente; ocultar la vista no autoriza nuevas eliminaciones.

Después de aplicar aparecen grupos de candidatos, no cientos de pares repetidos. Los vínculos de nombre o contacto pueden conectar varios registros para **presentarlos juntos**, pero esa conexión no declara que sean una sola entidad y nunca autoriza una fusión automática. Cada registro aparece en un único grupo pendiente.

El contrato de revisión conservado en el backend admite:

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
5. Los contactos distintos, vacíos o documentos contradictorios de Andrea, Carlos y Laura bloquean su eliminación automática. Esas filas se conservan y no aparecen grupos pendientes en pantalla.
6. Ejecutar otra vez: no habrá cambios adicionales con la misma configuración. Descargar el CSV acumulado y compararlo con el original de nueve registros. El informe enlazado conserva también la evidencia histórica de la versión anterior con revisión visible.

Las cantidades del ejemplo son resultados de esa ejecución, no constantes de interfaz. Evidencia y detalles: [docs/automatic-cleanup.md](docs/automatic-cleanup.md).

### Límites específicos

La regla es deliberadamente conservadora: un correo o teléfono compartido puede pertenecer a distintas personas y cualquier conflicto requiere revisión. No valida identidad, titularidad de contactos, direcciones ni documentos. Las asociaciones por encabezado son sugerencias editables, no inferencias semánticas. Se mantienen los límites de 2.000 filas y 10 MB, memoria de un único worker y exportación CSV. La inferencia de tipos de pandas al cargar sigue vigente; conviene revisar columnas como teléfonos e identificadores cuando el archivo usa formatos especiales o ceros iniciales. No se promete que los grupos de revisión correspondan a una entidad real.


## Limpieza global y formatos de fecha — actualización del 18 de noviembre

La acción principal **Limpiar automáticamente todas las columnas** prepara y aplica todos los cambios seguros de una sola vez sobre el trabajo vigente. Conserva el original, la trazabilidad y el CSV acumulado. No requiere aprobar grupos de candidatos. La previsualización y las herramientas manuales siguen disponibles como opciones secundarias.

Se aplica el recorte y la reducción de espacios a todas las columnas de texto, aunque no figuraran en una configuración guardada previamente. Los canónicos continúan siendo los configurados o aprobados; no se inventan equivalencias por similitud ni se fuerzan fusiones por nombre. Los valores numéricos e identificadores conservan su tipo y contenido.

**Fechas:** la normalización está activada por defecto. Se detectan columnas con encabezados de fecha (`fecha`, `fecha_ingreso`, `date`, `birth_date`, etc.), tipos de fecha reales de Excel y columnas cuyo contenido completo cumple un formato de fecha estricto. Se excluyen columnas asociadas a nombre/contactos/identificadores, columnas técnicas ignoradas y encabezados de códigos, teléfonos, documentos y cuentas.

- Fechas válidas con año de cuatro dígitos: salida ISO `AAAA-MM-DD`; admite separadores `/`, `-` y `.`.
- Año al inicio es inequívoco: `2026/11/18` → `2026-11-18`.
- En orden **Automático**, `18/11/2026` y `11/18/2026` son interpretables y se convierten. `03/04/2026` se conserva porque puede representar dos días diferentes. `03/03/2026` sí es inequívoca.
- En **Opciones de fechas, asociaciones y valores canónicos** puede elegirse **Día / mes / año** o **Mes / día / año**. Con la primera opción, `03/04/2026` pasa a `2026-04-03`; con la segunda, a `2026-03-04`.
- Los valores inválidos, años de dos dígitos, texto libre y números de serie Excel sin tipo de fecha se conservan y se informa la omisión. No se infieren siglos ni se corrigen días imposibles.
- Las horas, fracciones de segundo y zonas horarias se conservan en ISO 8601. No se cambia de zona ni se recorta un datetime a solo fecha. `18/11/2026 14:30:15` → `2026-11-18T14:30:15`.
- El resumen muestra **Fechas normalizadas** y **Fechas conservadas sin interpretar**, con detalles de fila, columna y motivo. Cada conversión figura como regla `normalize_date` en la auditoría. Repetir con el mismo orden no vuelve a modificar fechas ya normalizadas.

El ejemplo **Ejemplo con fechas** carga `frontend/public/fechas_demo.csv`: permite comprobar formatos mixtos, una fecha ambigua, una inválida, hora con zona y un código con apariencia de fecha que debe conservarse. Tras limpiar en modo automático, elegir día/mes y volver a limpiar resuelve únicamente la fecha ambigua; la inválida sigue intacta.

El contrato de configuración añade `all_columns` (predeterminado `true`), `normalize_dates` (predeterminado `true`) y `date_order` (`auto`, `dmy` o `mdy`). Los contadores incorporan `dates_normalized` y `dates_skipped`; el informe contiene `date_issues`. La interfaz siempre solicita limpieza global. La API permite `all_columns=false` para integraciones que necesiten reglas explícitas por columna.

Verificación: ejecutar `python -m unittest discover -v` desde backend y `npm run build` desde frontend. `backend/test_dates.py` cubre formatos, ambigüedad, fechas inválidas, horas y zonas, fechas de Excel, identificadores, limpieza global, repetición, originales intactos y contrato HTTP.

Verificación de esta actualización: **71 pruebas aprobadas** (`unittest`, 0,806 s en la última ejecución) y build TypeScript/Vite correcto. En el navegador se comprobó el botón directo, cero elementos «Grupos pendientes», cuatro fechas normalizadas en modo automático y la conversión de la fecha ambigua al elegir día/mes. Se abrió el CSV descargado y se verificaron hora/zona, fecha inválida preservada y código sin convertir. La consola del navegador no registró errores ni avisos durante el recorrido. [Captura del resultado](docs/global-cleanup-dates.jpg).

## Normalización automática de países

Está activada por defecto dentro de **Limpiar automáticamente todas las columnas**. No consulta una API de países durante el procesamiento ni envía registros de clientes al exterior: usa el catálogo local ISO 3166-1 de [pycountry](https://github.com/pycountry/pycountry), sus traducciones al español y una lista explícita de abreviaturas conocidas.

Se detectan encabezados como `country`, `country_name`, `country_code`, `país`, `pais_residencia`, `billing_country` o `shipping_country`. En **Opciones de fechas, asociaciones y valores canónicos → Países** se pueden seleccionar otras columnas, desactivar la regla o elegir la salida:

- **Nombre en español** (predeterminado): `US`, `usa`, `u.s.` y `United States` → `Estados Unidos`.
- **Nombre en inglés:** esas variantes → `United States`.
- **ISO de dos letras:** → `US`; `UK` y `United Kingdom` → `GB`.
- **ISO de tres letras:** → `USA`, `GBR`, etc.

Se reconocen nombres actuales del catálogo en español e inglés, códigos ISO alpha-2/alpha-3, códigos numéricos ISO de tres dígitos cuando se reciben como texto y alias controlados como `UK`, `EE.UU.` o `U.S.A.`. Las mayúsculas, tildes, puntos y espacios se normalizan para la búsqueda. No se aplica esta conversión a nombres, ciudades ni otras columnas por el simple hecho de que su contenido coincida con un código de país.

No se utiliza búsqueda difusa ni búsqueda de subdivisiones. Un error como `Germnay`, un valor regional como `Latam`, nombres incompletos como `Corea` o ambiguos como `Congo` se conservan y se explican en **Países conservados sin reconocer**. Para Congo hay que indicar explícitamente la república correspondiente o sus códigos `CG`/`CD`. Las subdivisiones como `England` no se convierten silenciosamente en un país distinto. Se pueden añadir equivalencias justificadas mediante las reglas por columna existentes. Los valores numéricos reales no se reinterpretan como códigos; tampoco se rellenan países vacíos.

La regla se ejecuta después de los reemplazos explícitos y antes de la comprobación de duplicados tras estandarizar. Puede resolver diferencias de país entre registros, pero la eliminación de clientes sigue necesitando las reglas conservadoras de contacto/nombre/identificadores existentes. Las columnas asociadas a identidad, contactos o datos técnicos no pueden seleccionarse para conversión de país. Una columna seleccionada como país queda excluida de la detección automática de fechas.

El resultado incluye los contadores reales `countries_normalized` (celdas cambiadas) y `countries_skipped` (valores no vacíos no reconocidos o ambiguos), los detalles `country_issues` y eventos `normalize_country` con antes/después, columna, registro original, código ISO reconocido, formato de salida y fuente del catálogo. Los vacíos no cuentan como errores. Repetir sobre valores ya normalizados no vuelve a modificar las celdas.

El contrato de `AutoCleanupRequest` añade:

```json
{
  "normalize_countries": true,
  "country_format": "es",
  "country_columns": null
}
```

`country_format` acepta `es`, `en`, `iso2` o `iso3`; `country_columns=null` detecta columnas por encabezado y `[]` no selecciona ninguna. El endpoint de configuración devuelve la selección sugerida para que React la muestre y permita editarla.

Instalar o actualizar dependencias desde `backend` con `./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`. El catálogo se actualiza al actualizar la dependencia, no mediante llamadas de red en cada limpieza. Es una referencia de códigos y nombres; no verifica nacionalidad, residencia, soberanía ni la identidad de una persona. Las denominaciones siguen la versión instalada del catálogo salvo alias y nombres desambiguados documentados en `country_normalization.py`.

### Verificación con el CSV suministrado

Se leyó `dirty-customers_corregido.csv` sin modificarlo y se ejecutó la limpieza real sobre una copia de trabajo. Sus 999 filas contenían 14 representaciones de país y quedaron 999 filas, 999 celdas de país normalizadas y cero países sin reconocer:

| País canónico | Filas |
|---|---:|
| Estados Unidos | 294 |
| Reino Unido | 206 |
| Alemania | 202 |
| Brasil | 154 |
| Francia | 143 |

La segunda ejecución produjo cero celdas modificadas y cero filas eliminadas. Se comprobó la igualdad del DataFrame original y de los bytes del CSV fuente antes/después. El CSV del usuario no se incorpora al repositorio ni a las pruebas; las pruebas reproducen solamente sus variantes de país.

Verificación de esta entrega: **84 pruebas aprobadas**, incluyendo las 71 existentes y 13 nuevas de países; build TypeScript/Vite correcto. Las nuevas pruebas comprueban nombres, alias, códigos y traducciones, todas las salidas canónicas del catálogo como entradas idempotentes, ambigüedad, columnas explícitas, originales intactos, repetición, combinación con fechas/duplicados y contrato HTTP. Ejecutar `python -m unittest discover -v` desde backend y `npm run build` desde frontend.
