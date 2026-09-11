# Automatización del CV

Genera un CV específico a partir de una oferta y del perfil maestro, con evidencias
trazables y PDF local. Codex es el proveedor predeterminado; OpenAI Responses y APIs
compatibles con Chat Completions son opciones explícitas.

- [Flujo detallado y herramientas por etapa](workflow.md)
- [Configuración de modelos y APIs](configuration.md)
- [Reanudación, errores y pruebas](troubleshooting.md)

## Preparación local

Necesitas Python 3.12+, Git, Tectonic y, si usas el proveedor predeterminado, Codex CLI.
Desde la raíz del repositorio, en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
codex login
codex login status
New-Item -ItemType Directory -Force .private
Copy-Item contact.example.json .private/contact.json
```

Si ya tienes el archivo de contactos, consérvalo. Completa email, phone y linkedin.
Los tres son obligatorios. No los incluyas en el perfil YAML, en parámetros de Actions
ni en archivos que se publiquen. La variable CV_CONTACT_JSON tiene precedencia sobre
el archivo de contactos.

```powershell
./tailor.ps1 "URL_OFERTA" -Slug empresa-puesto -Language en
```

Sin slug, PowerShell genera uno con fecha. Para recuperar una ejecución fallida debes
indicar el slug original y añadir -Resume. El CLI Python conserva el comando anterior:

```powershell
python -m automation.run --url "URL_OFERTA" --slug empresa-puesto --language en
```

Si la web bloquea el contenido público, guarda texto UTF-8 en .private/oferta.txt y
añade --job-text .private/oferta.txt (o -JobText en PowerShell). La fuente manual se
registra como tal. LinkedIn se consulta por el identificador de oferta, sin cookies
ni acceso a tu sesión personal.

## Validación y revisión

Antes de las llamadas se comprueban el perfil, IDs de evidencia, contactos,
configuración y herramientas. La generación normal usa tres solicitudes lógicas;
las correcciones limitadas pueden elevarlas hasta once, más los reintentos de
transporte permitidos por el presupuesto.

La extracción conserva condiciones y distingue requisitos individuales, alternativas
y exigencias conjuntas. Si la auditoría detecta un error semántico de extracción,
permite una nueva secuencia extraer/adaptar/auditar. Las afirmaciones dudosas pueden
sustituirse por hechos literales del maestro y volver a auditarse hasta tres veces.
Estas rondas verifican el CV frente a la extracción ya aprobada. Si los
problemas persisten, se detiene la generación.

Se comprueban evidencias, atribución, cifras, longitud de texto, privacidad,
compilación, páginas, texto extraíble, contactos y desbordamientos. El auditor LLM
puede equivocarse: abre el PDF y contrástalo con match.md. validation.json mantiene
visual_review=pending; sólo registra una revisión realizada por una persona.
No se estima la probabilidad de contratación ni se envía una candidatura.

## Archivos y privacidad

- profile/profile.yaml es la fuente de hechos. Actualiza version, reviewed_on e
  historial en profile/evidence.md al revisar el perfil. Nunca se modifica automáticamente.
- roles/<slug>/ contiene siete archivos de revisión sin contactos.
- build/<slug>/cv.pdf contiene el PDF completo local.
- .private/runs/<slug>/ conserva la oferta, respuestas y diagnósticos para reanudar.
  CV_RUNS_DIR permite trasladar este directorio privado fuera del checkout.

Los títulos, empresas, fechas, formación e idiomas se conservan desde el maestro.
El selector de idioma cambia resumen, competencias, bullets y etiquetas; no traduce
automáticamente las credenciales originales.

El texto completo de la oferta se guarda sólo en el checkpoint privado. Las claves
API no se guardan en el TOML ni en los checkpoints. Codex recibe JSON desde un directorio
temporal, sin el repositorio ni los contactos, con shell/búsqueda desactivados. Jinja2
escapa el texto y Tectonic compila en modo no confiable.

El perfil de este fork es público. Los análisis que publiques también lo serán.
.gitignore no cifra archivos: protege los directorios privados con los controles del
ordenador. El proceso no publica PDFs como artifacts, releases ni GitHub Pages.

## Publicación opcional desde el ordenador

La generación y la publicación son comandos separados. Revisa los siete archivos
antes de publicar. Configura GITHUB_REPOSITORY=owner/repo, GH_TOKEN y autenticación
Git para origin. Usa un checkout limpio cuyo HEAD coincida con la base remota:

```powershell
python -m automation.publish --slug empresa-puesto --base master
```

El script comprueba origin, ausencia de cambios rastreados, base remota actualizada,
lista de archivos y diff completo antes del push. Crea codex/cv-<slug> y una PR en
borrador. Si tu checkout incluye commits ajenos a la base, se detiene: copia los
resultados a un checkout limpio de esa base.

Si la API de PR falla después del push, la rama se conserva: abre la PR desde GitHub
sin repetir la generación. Los datos de autenticación de Codex no son credenciales Git.

## GitHub Actions en un repositorio privado

checks.yml ejecuta pruebas en runners efímeros de GitHub sin modelos ni contactos.
tailor-cv.yml tiene una condición explícita que impide su ejecución en repositorios
públicos. Para automatizar remotamente, lleva el código revisado a un repositorio de
automatización privado. El fork público sigue permitiendo la generación local.

En el repositorio privado:

1. Instala un runner Windows dedicado con etiqueta cv-private y las herramientas.
   Para Codex, ejecútalo con el usuario que realizó codex login.
2. Crea el environment cv-private, limitado a la rama predeterminada, con CV_CONTACT_JSON.
   Para OpenAI añade OPENAI_API_KEY; para compatible añade LLM_API_KEY.
3. Habilita la creación de PRs por Actions y revisa config/default.toml.
4. Ejecuta manualmente con URL, slug, idioma y, si quieres, proveedor/modelo/base_url.
   configured respeta la configuración común; sin personalización usa Codex.
5. El PDF queda en %USERPROFILE%/CV-private/output/<slug>/cv.pdf y los checkpoints
   en %USERPROFILE%/CV-private/runs/<slug>. Resume reutiliza estos checkpoints.

El workflow sólo admite al propietario, desde la rama predeterminada, en el repositorio
privado. No actives eventos de PR ni código ajeno en ese runner. Publica automáticamente
una PR borrador después de generar; la revisión visual sigue pendiente.

No se crean repositorios, runners ni secretos al modificar estos archivos. La definición
está preparada para configurarse en el repositorio privado; no cambia la visibilidad
ni la infraestructura del fork existente.

Fuentes: [Codex no interactivo](https://learn.chatgpt.com/docs/non-interactive-mode),
[salidas estructuradas](https://developers.openai.com/api/docs/guides/structured-outputs).
