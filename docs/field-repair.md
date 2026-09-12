# Reparaci√≥n de campos rechazados

El auditor devuelve `unsupported_claims` como objetos con `path`, `fragment`,
`reason` y `valid_evidence_ids`. Las rutas siguen siendo `summary`, `headline`,
`bullet:ROLE_ID:N` y `skill:N`. Los √≠ndices empiezan en cero.

Cada campo dispone de dos intentos generativos en total. La petici√≥n incluye el
texto anterior, las evidencias permitidas, el rechazo exacto, el idioma y los
l√≠mites vigentes. Se pide eliminar √∫nicamente la afirmaci√≥n problem√°tica.
Cada resultado debe superar la validaci√≥n local antes de volver a la auditor√≠a
sem√°ntica del borrador. Los errores de validaci√≥n se explican en el siguiente
intento. Los presupuestos y fallos de transporte siguen deteniendo la ejecuci√≥n.

Tras agotar los intentos, el resumen combina 2‚Äì3 hechos literales profesionales,
priorizando experiencia y despu√©s competencias; el titular usa un t√≠tulo
profesional del maestro, sin empresa ni fechas. Las vi√±etas usan un hecho literal
del puesto correspondiente y las competencias una entrada literal de skills.
No se cortan hechos para ajustar longitud: se selecciona una combinaci√≥n que
quepa o se detiene la generaci√≥n. Estos fallbacks conservan el idioma del maestro.

Los fallbacks tambi√©n se validan y auditan. Si el auditor sigue rechazando el
borrador tras las tres rondas de reparaci√≥n, no se publica ning√∫n resultado.
La validaci√≥n local impide usar √∫nicamente evidencia educativa, ling√º√≠stica o
administrativa en resumen/titular, y detecta entradas literales de esos tipos
incluso con citas profesionales a√±adidas. El auditor comprueba tambi√©n sus
par√°frasis y que el contenido cumpla la funci√≥n del campo.

Pruebas: `python -m unittest discover -s tests -v`.

## Excesos de longitud antes de la auditorÌa

La generaciÛn apunta a 8ñ12 palabras en titular y 45ñ55 en resumen; los m·ximos
siguen siendo 14 y 65. Si un campo los supera, se regenera ˙nicamente ese campo
con su texto, evidencias, conteo exacto y objetivo de 12 o 55 palabras. Se valida
cada respuesta de forma independiente para poder reparar ambos campos a la vez.
Se aceptan respuestas v·lidas dentro del m·ximo duro aunque excedan el objetivo.

Hay dos intentos de longitud por campo compartidos entre los borradores de una
ejecuciÛn, separados de los intentos de reparaciÛn sem·ntica. DespuÈs se usa el
fallback validado del campo. Se aplica al borrador inicial, su reintento por
validaciÛn y la regeneraciÛn tras corregir la extracciÛn. El borrador completo
se valida y audita antes de compilar, tambiÈn cuando se utiliza un fallback.
Los presupuestos globales de peticiones y tiempo siguen vigentes; no se aumentan
autom·ticamente. Sin un fallback v·lido o al agotar el presupuesto, se detiene.
