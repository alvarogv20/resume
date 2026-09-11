# Configuración de proveedores

Precedencia: **argumentos CLI → variables CV_* → archivo TOML → valores internos**.
El archivo inicial es `config/default.toml`. Para otro archivo, utiliza `--config`
o `CV_CONFIG`; las rutas relativas se resuelven desde el directorio de trabajo.
No escribas claves dentro del TOML: `api_key_env` sólo nombra una variable de entorno.

## Codex predeterminado

```powershell
./tailor.ps1 "URL_OFERTA" -Slug empresa-puesto
python -m automation.run --url "URL_OFERTA" --slug empresa-puesto --model gpt-5.6-luna
```

Sin overrides usa `codex`, modelo `gpt-5.6-luna`, razonamiento `medium`. Cambia el
modelo con `--model` / `-Model`, o `CV_MODEL`; cambia razonamiento con `--reasoning`
o `CV_REASONING`. La disponibilidad depende de la cuenta. Requiere Codex CLI en PATH
o `CODEX_BIN`, y autenticación preparada mediante `codex login`.
El modelo se ejecuta en el servicio, aunque el proceso y el PDF sean locales.

## OpenAI Responses API

Configura `OPENAI_API_KEY` en tu entorno mediante tu gestor de secretos. Después:

```powershell
./tailor.ps1 "URL_OFERTA" -Slug empresa-api -Provider openai -Model gpt-5-mini
```

Usa `https://api.openai.com/v1/responses`, `store=false` y salida JSON Schema estricta.
Su facturación es independiente de la sesión Codex. No redirige claves a endpoints
alternativos: para otro servicio utiliza `compatible`.

## Otra API compatible con Chat Completions

Configura `LLM_API_KEY` en tu entorno y sustituye endpoint/modelo por los de tu servicio:

```powershell
python -m automation.run --url "URL_OFERTA" --slug empresa-otro --provider compatible --model "MODELO_DEL_SERVICIO" --base-url "https://api.tu-proveedor.example/v1"
```

El adaptador añade `/chat/completions`. Requiere HTTPS, autenticación Bearer,
`messages`, `max_tokens`, `response_format` y respuestas con `choices`/`finish_reason`.
El modo inicial es `json_schema`; si el servicio sólo acepta JSON Object, selecciona
explícitamente `--structured-output json_object`. El JSON se valida localmente en ambos
casos. No se rebaja el contrato ni se cambia de proveedor automáticamente.

Esto no implica compatibilidad universal con APIs nativas de otros proveedores. Un
servicio con un protocolo diferente necesita su propio adaptador en `providers/`.
Las políticas de almacenamiento del servicio externo deben consultarse en ese servicio;
el adaptador compatible no presupone que admita el parámetro `store` de OpenAI.

También puedes guardar `.private/provider.toml`:

```toml
provider = "compatible"
[providers.compatible]
model = "MODELO_DEL_SERVICIO"
base_url = "https://api.tu-proveedor.example/v1"
api_key_env = "LLM_API_KEY"
structured_output = "json_schema"
```

```powershell
./tailor.ps1 "URL_OFERTA" -Slug empresa-otro -Config .private/provider.toml
```

## Presupuestos y variables

| Ajuste | CLI / variable | Predeterminado |
|---|---|---|
| Proveedor | `--provider` / `CV_PROVIDER` | codex |
| Modelo | `--model` / `CV_MODEL` | Por proveedor |
| Endpoint compatible | `--base-url` / `CV_BASE_URL` | Se exige explícito |
| Variable que guarda la clave | `--api-key-env` / `CV_API_KEY_ENV` | OPENAI_API_KEY o LLM_API_KEY |
| Timeout por intento | `--timeout` / `CV_TIMEOUT` | Codex 600 s; API 180 s |
| Reintentos transitorios | `--retries` / `CV_RETRIES` | 2 |
| Solicitudes reales por slug | `--max-requests` / `CV_MAX_REQUESTS` | 18, incluidos reintentos y ejecuciones anteriores |
| Presupuesto temporal LLM | `--max-seconds` / `CV_MAX_SECONDS` | 1800 s por invocación |
| Máximo de tokens de salida API | `--max-output-tokens` / `CV_MAX_OUTPUT_TOKENS` | 12000 |

El presupuesto temporal comprueba el tiempo antes de cada intento/espera y limita el
timeout de la siguiente operación. No es un límite de facturación ni incluye una
garantía de tiempo total de descarga, compilación o publicación. Codex no utiliza el
parámetro API `max_output_tokens`. Los tokens no disponibles se omiten, no se estiman.

`CV_RUNS_DIR` cambia el directorio privado de checkpoints. En Actions se fija fuera
del checkout para sobrevivir a la limpieza de la siguiente ejecución. Las claves
se obtienen sólo del entorno; no se imprimen ni forman parte de los checkpoints.

Tectonic se busca en PATH y después junto al ejecutable Python del entorno virtual.
Esto permite usar una instalación en `.venv/Scripts` incluso sin activar el entorno.
Una ruta explícita mediante `--tectonic` o `TECTONIC_BIN` tiene precedencia y debe existir.

Referencias: [Codex no interactivo](https://learn.chatgpt.com/docs/non-interactive-mode),
[salidas estructuradas de OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs).
