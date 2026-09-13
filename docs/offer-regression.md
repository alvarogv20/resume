# Regresión con ofertas guardadas

El corpus `tests/fixtures/offers/` incorpora sin modificaciones las nueve capturas
HTML aportadas en `ofertas-test` (13 de septiembre de 2026): Airbus Aerodynamics,
Airbus Aircraft Performance, GE Vernova, Nordex, Destinus, GMV, Strativ, Indra y
Envision. El manifiesto fija URL, ID, idioma y SHA256. Son capturas, no consultas
a anuncios actuales. Para actualizar una captura hay que revisar también su hash.

## Comprobación rápida, sin LLM

```sh
python -m unittest discover -s tests -v
python -m automation.benchmark
```

CI ejecuta automáticamente las pruebas del corpus: integridad, metadatos,
conversión HTML a texto y funcionamiento del ejecutor ante errores. Esto no
demuestra que el modelo pueda generar los nueve CV.

## Aceptación con generación real

Con las dependencias de `requirements.txt`, proveedor autenticado, Tectonic y
contactos privados configurados como en el flujo habitual:

```sh
python -m automation.benchmark --generate
python -m automation.benchmark --generate --contacts .private/contact.json --provider codex
```

También admite `--config`, `--model` y `--tectonic`. Usa el perfil y los validadores
reales, sin respuestas simuladas; convierte las capturas con el extractor de
producción y pasa texto local al pipeline, evitando depender de LinkedIn. Cada
oferta se genera en el idioma del HTML. Consume solicitudes del proveedor; los
presupuestos de configuración se aplican por oferta, no al lote completo.
Cada proceso tiene además un límite de 40 minutos.

El objetivo es **9/9 generaciones aprobadas**, incluyendo ofertas con poco encaje:
un gap honesto no debe confundirse con un error de generación. Cada caso exige los
siete entregables, PDF legible de una o dos páginas con contactos, validación de
layout y respaldo factual resuelto. No hay umbral mínimo de encaje ni `expected failure`.
Las advertencias editoriales y los gaps documentados son resultados válidos.
Las incidencias materiales pendientes o los fallos de generación cuentan como fallos.

Cada ejecución usa slugs nuevos. Los resultados públicos quedan en `roles/bench-*`,
los PDF en `build/bench-*`, y los textos, logs e informe agregado en
`.private/benchmarks/bench-*/results.json`. No publica ni crea PR. Continúa tras
un fallo y devuelve código 1 si cualquiera falla; 0 solo si todos pasan.
El informe se actualiza tras cada caso y contiene estado, duración y, para los
aprobados, páginas y solicitudes LLM. Los logs privados permiten diagnosticar
los casos fallidos. Una nueva ejecución no reutiliza resultados anteriores.

La revisión visual sigue pendiente incluso con 9/9. La auditoría del modelo no
sustituye una referencia humana de requisitos, gaps y fidelidad; estas capturas
todavía no incluyen ese etiquetado. El corpus permite medir generación de extremo
a extremo, pero no certifica por sí solo todos los criterios semánticos del informe.

## Arquitectura revisada

Consulte [los cambios de septiembre de 2026](review-changes.md) para estados,
reparaciones agrupadas, reanudación selectiva y tratamiento de advertencias.
El criterio del benchmark consulta el estado final `ready` y las incidencias
factuales pendientes. Una auditoría histórica negativa resuelta mediante evidencia
literal no equivale a un error pendiente; su feedback se conserva íntegro.
