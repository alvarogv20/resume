# Reparación de campos rechazados

El auditor devuelve `unsupported_claims` como objetos con `path`, `fragment`,
`reason` y `valid_evidence_ids`. Las rutas siguen siendo `summary`, `headline`,
`bullet:ROLE_ID:N` y `skill:N`. Los índices empiezan en cero.

Cada campo dispone de dos intentos generativos en total. La petición incluye el
texto anterior, las evidencias permitidas, el rechazo exacto, el idioma y los
límites vigentes. Se pide eliminar únicamente la afirmación problemática.
Cada resultado debe superar la validación local antes de volver a la auditoría
semántica del borrador. Los errores de validación se explican en el siguiente
intento. Los presupuestos y fallos de transporte siguen deteniendo la ejecución.

Tras agotar los intentos, el resumen combina 2–3 hechos literales profesionales,
priorizando experiencia y después competencias; el titular usa un título
profesional del maestro, sin empresa ni fechas. Las viñetas usan un hecho literal
del puesto correspondiente y las competencias una entrada literal de skills.
No se cortan hechos para ajustar longitud: se selecciona una combinación que
quepa o se detiene la generación. Estos fallbacks conservan el idioma del maestro.

Los fallbacks también se validan y auditan. Si el auditor sigue rechazando el
borrador tras las tres rondas de reparación, no se publica ningún resultado.
La validación local impide usar únicamente evidencia educativa, lingüística o
administrativa en resumen/titular, y detecta entradas literales de esos tipos
incluso con citas profesionales añadidas. El auditor comprueba también sus
paráfrasis y que el contenido cumpla la función del campo.

Pruebas: `python -m unittest discover -s tests -v`.
