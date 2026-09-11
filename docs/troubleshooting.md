# Recuperación y comprobaciones

## Reanudar después de un fallo

Repite los mismos argumentos añadiendo `--resume`, o `-Resume` en PowerShell. El slug
debe ser explícito. Cada respuesta cacheada vuelve a pasar las validaciones; un error
de compilación permite volver a compilar sin repetir las llamadas completadas.

```powershell
./tailor.ps1 "URL_OFERTA" -Slug empresa-puesto -Resume
```

No cambies perfil, código, plantilla, prompts, idioma, proveedor/modelo ni fuente al
reanudar: si cambian, utiliza un slug nuevo. Se puede ajustar el presupuesto, timeout,
reintentos, ruta de Tectonic, contactos o límite de páginas. La oferta descargada se
conserva privadamente y no se vuelve a descargar en una reanudación; para actualizar
una oferta utiliza un slug nuevo. Si usaste `--job-text`, conserva ese archivo.

## Problemas frecuentes

| Mensaje / situación | Qué hacer |
|---|---|
| Falta Codex o Tectonic | Instalar o configurar CODEX_BIN / TECTONIC_BIN. |
| Falta la clave API | Configurar la variable indicada por api_key_env en el proceso que ejecuta Python. |
| Codex falla | Comprobar `codex login status`, acceso al modelo y ejecutable. No se cambia de proveedor. |
| HTTP 401 / 403 | Revisar credencial/permisos; no se reintenta automáticamente. |
| HTTP 408 / 429 / 500 / 502 / 503 / 504 | Reintentos limitados con espera creciente o Retry-After numérico de hasta 60 s. |
| Esquema rechazado por una API compatible | Comprobar soporte; seleccionar json_object explícitamente si procede. |
| Presupuesto agotado | Aumentar conscientemente max_requests y reanudar. El contador se conserva entre invocaciones. |
| Fuente bloqueada o demasiado ruidosa | Guardar sólo el texto de la oferta y usar --job-text con slug nuevo. |
| Auditoría sigue rechazando el resultado | Revisar fuente y evidencias; los diagnósticos indican las etapas completadas. |
| PDF demasiado largo | Usar el límite de dos páginas si procede; cambiar contenido/prompts requiere un slug nuevo. |
| Directorio roles existente | Es un resultado terminado: usa una versión nueva del slug. |
| Checkpoints existentes | Reanudar con --resume, o usar slug nuevo. |
| active.lock tras interrupción abrupta | Verificar que no queda ningún proceso para ese slug antes de retirar únicamente ese archivo. |
| Publicación rechaza HEAD | Publicar desde un checkout limpio de la base remota, copiando sólo los siete resultados revisados. |

Los diagnósticos están en `.private/runs/<slug>/diagnostics/` y se numeran por intento;
los errores guardan metadatos sanitizados. Las respuestas válidas se guardan privadas,
incluidas las que luego necesitan una corrección semántica. Una respuesta inválida por
esquema o privacidad no se guarda como resultado reutilizable.

Un timeout de red puede ocurrir después de que el proveedor haya procesado la solicitud.
Un reintento podría consumir de nuevo: los límites de solicitudes acotan los intentos,
pero no implementan una garantía de ejecución exactamente una vez en el proveedor.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas no necesitan claves ni llaman a modelos: simulan los transportes y la
compilación en las pruebas de orquestación. Cubren configuración, evidencias, privacidad,
presupuestos, reanudación, corrección semántica y rechazo de publicaciones con commits
ajenos. Una prueba real con cada proveedor requiere credenciales y acceso a su modelo;
el soporte de una API compatible se verifica contra el servicio elegido.

Para la prueba opcional de compilación real, configura TECTONIC_BIN y ejecuta:

```powershell
python -m unittest discover -s tests -p test_pdf.py -v
```

Usa contactos ficticios y un directorio temporal; comprueba el compilador y el texto
extraíble, sin consumir un modelo ni marcar el PDF como revisado visualmente.
