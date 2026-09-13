# Cambios derivados de la revisión de septiembre de 2026

El pipeline conserva la fuente factual en `profile/profile.yaml`. Los cambios de
esta revisión no amplían la experiencia ni certifican que se cumplan todas las ofertas.

## Estados y entregables

`--analysis-only` permite obtener análisis sin contactos ni Tectonic. Los contactos
configurados siguen excluidos del contexto del modelo. Se guardan `job.json`,
`draft.json`, `adaptation.json`, `match.md`, `decisions.md` y `status.json` en el
checkpoint privado a medida que están disponibles. El manifiesto registra estado y
duración por etapa. Un fallo posterior conserva los resultados anteriores.

- `ready`: CV respaldado y análisis sin discrepancias materiales pendientes.
- `requires_review`: feedback de auditoría inválido o extracción todavía pendiente.
- `render_failed`: exportación fallida; consultar análisis y diagnósticos privados.

El CLI devuelve 0 para `ready`, 2 para revisión pendiente y 1 ante una excepción.
Solo `ready` produce resultados finales en `roles/` y `build/`; un PDF de revisión
queda en el checkpoint privado. Ninguna de estas operaciones publica cambios.

## Auditoría y corrección

Se conservan los nombres principales del esquema de auditoría. Las incidencias de
extracción ahora requieren severidad (material/editorial), motivo y cita fuente. El código
clasifica el feedback en `cv_factual_issues`, `match_warnings`,
`extraction_warnings` y `audit_errors`. Una afirmación cuestionada necesita una
ruta real, fragmento exacto, motivo y evidencias válidas para ser reparable. Una
objeción genérica no demuestra falsedad y produce revisión pendiente.

Un gap o una corrección del encaje se registra sin bloquear el CV. Se elimina el
veto basado en palabras negativas dentro de una justificación. `not_applicable`
exige condición explícita, evidencia y justificación; el auditor comprueba su
significado. La ausencia de prueba de aplicabilidad sigue siendo `unconfirmed`.

Una reparación agrupa los campos afectados en una llamada, valida cada campo y
finalmente el conjunto. Si persisten objeciones tras una reauditoría, los campos
se sustituyen por hechos literales del perfil o su traducción de presentación.
La auditoría original se conserva, aunque sea negativa: el estado final registra
la resolución y no falsea el veredicto anterior. Si no hay fallback seguro, la
operación falla y conserva el borrador; no se entrega como CV final.

Las correcciones de extracción regeneran únicamente oferta y cruce. El texto del
CV aceptado no se vuelve a redactar. Hay una reauditoría acotada y, si quedan
problemas materiales, el resultado permanece privado para revisión.

Ruta normal: tres llamadas. Reparación factual: normalmente cinco (las tres
iniciales, una corrección agrupada y una verificación). Una corrección de extracción
puede añadir una llamada adicional si coincide con reparación factual. Los errores
de formato permiten una corrección y los reintentos de transporte conservan el
presupuesto global por CV. No se promete un número fijo para todos los casos.

## Evidencia, idioma y PDF

Generación y reparación comparten el ámbito de evidencia: los bullets solo citan
su empleo; competencias pueden usar hechos de experiencia. La normalización numérica
acepta `10`, `10.0` y `10,0`; no prueba por sí sola la atribución semántica, que se audita.

`automation/localization.py` contiene traducciones españolas de presentación y
fallbacks vinculadas al texto fuente exacto. Una modificación del perfil requiere
actualizar las traducciones correspondientes. No existe fallback automático al inglés.
Las traducciones se han redactado durante esta implementación y requieren la misma
revisión editorial que el resto del CV.

Titular, resumen, bullets y conjunto de competencias tienen reparación local de
longitud. Tectonic conserva el PDF y log privados, mide desbordamientos e intenta
una pasada de compactación sin reducir la fuente. Desbordamientos de hasta 1 pt
quedan como advertencias; mayores, glifos ausentes o exceso de páginas bloquean
la exportación final. `cv.layout.json` identifica magnitud y líneas. Se requiere
revisión visual incluso cuando las verificaciones automáticas pasan.

Los emails de terceros pueden permanecer en citas privadas. Se omiten antes de
escribir archivos públicos. Los contactos configurados nunca se permiten en esos
archivos ni en llamadas LLM.

## Reanudar

```sh
python -m automation.run --url URL --slug SLUG --job-text oferta.txt --resume --restart-from audit
```

`extract`, `adapt`, `audit` y `export` invalidan su caché y dependencias conservando
las etapas anteriores. Los artefactos derivados se archivan en `history/` y los
contadores de solicitudes no se reinician. La identidad sigue exigiendo el mismo
perfil, código, prompts, fuente e idioma: un cambio de implementación necesita otro
slug. Reanudar sin invalidar reutiliza respuestas, incluso negativas.

## Alcance de la comprobación

El informe legible muestra requisito, evidencia textual, encaje/limitación, textos
del CV vinculados por IDs y pendientes. Esa relación por evidencia no afirma que
cada frase haya sido editada exclusivamente por un requisito. Las decisiones del
modelo explican los cambios; no son un registro humano independiente de calidad.

El benchmark de nueve ofertas usa modelo y compilador reales cuando se autoriza y
se ejecuta `python -m automation.benchmark --generate`. Registra fallos, solicitudes,
tokens disponibles y duración. No confundir tests unitarios con nueve CV generados.
No hay anotaciones humanas completas de requisitos/gaps ni una tasa estadística de
éxito estimable a partir de una sola ejecución. El parámetro max_output_tokens sigue
sin ser un límite efectivo para el proveedor Codex CLI; max_requests y max_seconds
son los límites operativos aplicables.

Una ruta de bullet mal numerada puede corregirse si su fragmento exacto aparece
una sola vez dentro del mismo empleo y sus evidencias son válidas para ese campo.
No se reasignan hallazgos entre empleos ni se resuelven coincidencias ambiguas.


Las referencias inexistentes en el cruce se retiran antes de validarlo. Una
coincidencia positiva afectada pasa a transferible (si queda evidencia conocida) o
no confirmada (si no queda ninguna). Se registra la corrección y no se inventan IDs
para los textos de `unconfirmed`. Las afirmaciones del CV conservan su validación
estricta de evidencias.

Los errores de Codex guardan la salida del proveedor exclusivamente en
`.private/provider-diagnostics/`. La excepción distingue acceso al directorio de
usuario, autenticación, cuota, límite temporal de peticiones y transporte. Solo
los errores transitorios consumen los reintentos acotados configurados.


Los esquemas enviados al proveedor enumeran los IDs reales de empleos, hechos,
requisitos y campos del CV. Además, una normalización local conserva el orden de
los empleos reales, elimina bloques ajenos (por ejemplo una competencia devuelta
como empleo) y restaura empleos omitidos con hechos literales de ese mismo empleo.
Los validadores de atribución se aplican después y la auditoría revisa el resultado.


La pasada local identifica también campos con evidencias fuera de ámbito,
afirmaciones numéricas no respaldadas o un tipo editorial inválido (por ejemplo un
titular que solo cita IDs de empleos sin coincidir con un título). Los repara en
el mismo lote que los campos largos; después vuelve a validar y audita. No se
regenera el CV entero por esas incidencias.
