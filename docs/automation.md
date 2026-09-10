# Automatización del CV

## Qué hace

URL de oferta → extracción → requisitos estructurados → cruce con el maestro →
redacción → auditoría de evidencias → PDF local → rama y PR opcional.

Usa `codex exec` con la sesión local de ChatGPT, modelo `gpt-5.6-luna` y razonamiento
bajo. Hace tres llamadas normalmente y hasta seis si necesita corregir extracción y borrador.
Consume los límites de tu cuenta Codex; la disponibilidad del modelo depende de la
cuenta. `--model` permite cambiarlo sin tocar el código. La integración no necesita
copiar tu sesión a GitHub ni almacenar una clave API. Las solicitudes de Codex se
procesan en el servicio: «local» significa que el proceso y los archivos están en tu
ordenador, no que el modelo se ejecute offline.

Hay un adaptador opcional `--provider openai --model gpt-5-mini` mediante Responses
API y salida JSON Schema, con `store: false`. Requiere `OPENAI_API_KEY` y facturación
API separada; no está activado por defecto ni es necesario para la opción elegida.

## Primera configuración local (Windows / PowerShell)

Instala Python 3.12+, Git, Codex CLI y Tectonic, disponibles en `PATH`. Abre la carpeta
del fork y ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
codex login
codex login status
New-Item -ItemType Directory -Force .private
Copy-Item contact.example.json .private/contact.json
```

Edita `.private/contact.json` con tu correo, teléfono y perfil LinkedIn. En esta
instalación ya se ha configurado con el correo/teléfono locales y el LinkedIn
facilitado por el propietario. Los tres campos son obligatorios; la generación
se detiene si faltan. No los escribas en YAML, un issue, una PR o un parámetro de Actions.

```powershell
python -m automation.run --url "https://www.linkedin.com/jobs/view/4441905971/" --slug nordex-4441905971 --language en
```

Si ya existe ese resultado, usa un identificador nuevo, por ejemplo
`nordex-4441905971-v2`. Nunca se sobrescriben versiones anteriores. Si Tectonic o
Codex no están en PATH, configura `TECTONIC_BIN`/`CODEX_BIN` con la ruta al ejecutable
(o usa `--tectonic`). El perfil se valida antes de llamar al modelo; la compilación
se ejecuta en un directorio temporal con modo no confiable de Tectonic.

LinkedIn: basta con pasar el enlace largo de búsqueda que contiene `currentJobId`.
Se transforma en una URL canónica sin identificadores de seguimiento. Se consulta
la descripción pública de ese puesto, sin cookies ni acceso a tu cuenta LinkedIn.
Si un portal bloquea la lectura, guarda la descripción como texto UTF-8 en
`.private/oferta.txt` y añade `--job-text .private/oferta.txt`. Se registrará ese
origen; no se fingirá una extracción web exitosa.

## Resultados y revisión

- `roles/<slug>/`: oferta estructurada, análisis, decisiones, LaTeX sin contactos,
  salida del LLM con IDs de evidencia y validaciones con hashes de perfil/fuente/prompts.
- `build/<slug>/cv.pdf`: documento completo con teléfono, email y enlace LinkedIn.
- `.private/diagnostics/`: última salida de cada etapa para depurar fallos, fuera de Git.

Se comprueban formato, requisitos cubiertos en el análisis, existencia y atribución
de evidencias, cifras, ausencia de contactos en resultados publicables, compilación,
texto extraíble, contactos en el PDF y máximo de dos páginas. `--max-pages 1` exige
una página. La auditoría semántica también la realiza un LLM y puede equivocarse;
la revisión visual y editorial sigue pendiente hasta que una persona la compruebe.
No se calcula una probabilidad de contratación ni se envía una candidatura.

Abre el PDF, revisa su distribución y contrástalo con `match.md`. Para registrar una
revisión visual realizada, cambia `visual_review` en `validation.json` y documenta
quién la hizo. No marques como revisado un PDF que no hayas abierto.

## Modificar el perfil maestro

Edita `profile/profile.yaml`. Actualiza `version`, `reviewed_on` y el historial de
`profile/evidence.md`. Los hechos mantienen IDs estables y los resultados conservan
el SHA256 de la versión utilizada. El proceso no modifica el maestro ni aprende
hechos de sus propias adaptaciones. `base.tex` queda como referencia inicial; para
las nuevas adaptaciones manda el YAML. Los títulos, empresas, fechas, formación e
idiomas se conservan literalmente; el selector de idioma adapta el resumen,
competencias y bullets, sin traducir automáticamente las credenciales originales.

## GitHub Actions usando tu sesión local

`checks.yml` se ejecuta en runners efímeros de GitHub para probar código y evidencias.
No utiliza contactos ni consume llamadas a Codex.

`tailor-cv.yml` permite introducir URL, identificador e idioma en **Actions → Tailor
CV (private local Codex) → Run workflow**. Necesita un runner Windows propio, encendido
y conectado, porque la sesión de Codex y el PDF permanecen en tu ordenador.

Configuración única, después de integrar esta PR en la rama predeterminada:

1. En **Settings → Actions → Runners → New self-hosted runner**, sigue los comandos
   oficiales de GitHub para Windows y añade la etiqueta `cv-private`. Usa una carpeta
   dedicada al runner, distinta de tu checkout de trabajo. Ejecútalo como el mismo
   usuario de Windows que hizo `codex login`; una cuenta de servicio distinta no
   tendrá esa sesión. Instala las dependencias de `requirements.txt` en el Python
   que utilice el runner y asegúrate de que `pwsh`, Git, Codex y Tectonic estén en PATH.
2. Crea el environment `cv-private`, limita sus ramas de despliegue a la rama
   predeterminada y añade como secreto `CV_CONTACT_JSON` el contenido del archivo
   privado. Si utilizas GitHub CLI autenticado, este comando lee el archivo sin
   poner su contenido en el historial:

   ```powershell
   Get-Content -Raw .private/contact.json | gh secret set CV_CONTACT_JSON --repo alvarogv20/resume --env cv-private
   ```

3. En **Settings → Actions → General → Workflow permissions**, permite crear PRs
   desde Actions. El workflow pide `contents: write` y `pull-requests: write` para
   publicar sólo los siete archivos permitidos del resultado.
4. Ejecuta manualmente el workflow desde la rama predeterminada. El PDF final queda
   en `%USERPROFILE%\CV-private\output\<slug>\cv.pdf` en el ordenador del runner,
   además del directorio de compilación temporal del checkout. Una PR en borrador
   enlaza la documentación pública; no se sube el PDF como artifact.

El runner privado sólo recibe ejecuciones manuales del propietario, desde código
de la rama predeterminada. No añadas eventos `pull_request`, `pull_request_target`
o ejecución de ramas ajenas a ese runner. Dado que el fork es público, cualquier
colaborador al que concedas capacidad de modificar la rama predeterminada también
debe ser alguien a quien confíes la ejecución de código en ese ordenador. No uses
esa instalación como runner genérico para otros workflows o repositorios.

No se han registrado runners ni configurado secretos automáticamente: esos cambios
requieren acceso administrativo de GitHub y a la instalación del runner. El conector
empleado para el fork no expone la administración de runners/secrets. Hasta completar
estos pasos, el comando local funciona y la ejecución privada de Actions no está activada.

## Publicar un resultado desde el ordenador

Revisa primero la documentación publicable. Configura autenticación Git para el
fork y una credencial `GH_TOKEN` con permisos de contenido y PR; no reutilices la
sesión de Codex como credencial GitHub. Establece `GITHUB_REPOSITORY=alvarogv20/resume`.

```powershell
python -m automation.publish --slug nordex-4441905971 --base master
```

El script crea la rama `codex/cv-<slug>`, confirma sólo el listado permitido y abre
una PR en borrador. Si falla al crear la PR después de publicar la rama, la rama se
conserva y puedes abrir la PR en GitHub sin volver a ejecutar la generación. No usa
`git add .` ni añade PDFs. También puedes pedir a Codex que publique el resultado
mediante el conector GitHub, tras inspeccionar los archivos.

## Privacidad y límites

Los contactos sólo se cargan para la comprobación de privacidad y compilación.
No se pasan en el payload ni el entorno del subproceso LLM. Codex se ejecuta desde
un directorio temporal sin el repo, sin configuración de plugins del usuario,
sin instrucciones de proyecto y con shell y búsqueda desactivados. El modelo
produce JSON; no puede suministrar LaTeX ejecutable al compilador. El renderer escapa
todo texto. La compilación usa sólo la plantilla y el contacto generados por código.

El perfil profesional es público en este fork. Los análisis de las candidaturas
que publiques también lo serán. El PDF completo permanece local: no hay artifacts,
releases ni GitHub Pages con contactos. El `.gitignore` no es cifrado ni control de
acceso al ordenador; las comprobaciones previas a publicar complementan esa exclusión.

Los fallos de extracción, respuesta incompleta, evidencias inválidas, auditoría,
compilación o privacidad detienen el proceso. Como máximo hay una corrección del
borrador. Un enlace caducado o un requisito no cumplido no se sustituye por datos inventados.

## Comprobaciones

```powershell
python -m unittest discover -s tests -v
```

Fuentes técnicas:
- [Codex no interactivo](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Salidas estructuradas](https://developers.openai.com/api/docs/guides/structured-outputs)
- [GPT-5 mini para el adaptador API opcional](https://developers.openai.com/api/docs/models/gpt-5-mini)
