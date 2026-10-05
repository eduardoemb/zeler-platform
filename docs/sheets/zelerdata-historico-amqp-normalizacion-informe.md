# ZelerData AMQP — userinfo compatible en memoria, sin cambio persistente

**ENTREGA LOCAL COMPLETA; producción NO ejecutada por AMQP.** Preparación del
5 de octubre de 2026: **30 unittest offline PASS**, cero skips; ruff, formato y
mypy enfocados PASS en tres fuentes privadas. Ownership se devuelve al coordinador.

El coordinador confirmó antes de este encargo que el único rechazo era userinfo:
credenciales decodificadas iguales al broker, broker CloudAMQP y restantes guards
válidos. Su operación anterior quedó STOP/consumida con cero red. Esta entrega
prepara una operación distinta, no reescribe ese intento ni afirma salud productiva.

## Quick path del coordinador

1. Verificar autoridad de la única lectura, ledger y hashes de esta entrega.
2. Verificar el worker/digest autorizado y ejecutar exactamente una vez bajo
   caller acotado; guardar un recibo nuevo. Primer error STOP, sin retry/fallback.
3. Interpretar topología, publicación confirmada y entrega/TTL real por separado.
   La herramienta jamás publica, consume mensajes o acredita los dos últimos.

Referencias: [shape y contrato previo](zelerdata-historico-amqp-shape-informe.md),
[ledger central](zelerdata-historico-paralelo.md) y
[lector original](../../infra/operations/zelerdata_amqp_delay_readonly.py).

## 1. Cuatro paths exclusivos

Privado: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-userinfo-reader-20261005`.
Directorio `0700`; fuentes privadas `0600`.

| Path | Entrega |
| --- | --- |
| `<privado>/normalized_reader.py` | Wrapper standalone por stdin al Python3.11 del worker. |
| `<privado>/normalized_supervisor.py` | Supervisor stdlib por stdin al host; sintaxis3.9 verificada por AST. |
| `<privado>/test_normalized_reader.py` | 16 pruebas del reader y 14 del supervisor fake; total30, bajo cap60. |
| `docs/sheets/zelerdata-historico-amqp-normalizacion-informe.md` | Este informe propio. |

Logs, recibos y cache de mypy propios permanecen en ese directorio. Fuentes e
informes anteriores config/shape y lector canónico conservan todos sus hashes.
Sin core, CUOTAS, documentos centrales, dependencias, lockfiles, Docker real,
puertos, Mongo, red, gcloud, Git mutante, builds o subagentes.

## 2. Normalización exacta y gates

El módulo canónico completo se carga sin ejecutar su main tras verificar SHA256
`66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.
Su validación, cliente BasicAuth, inspect, límites, sanitización y filtros de logs
no se modifican. HTTPX se importa, pero nunca se llama antes del preflight.

El wrapper consulta únicamente las dos variables del proceso
`RABBITMQ_URL`/`RABBITMQ_MANAGEMENT_URL`. Exige broker con hostname parseado
terminado en `.cloudamqp.com`, userinfo explícito con usuario/password y
credenciales decodificadas exactamente iguales a las del broker canónico.

Se elimina **solo el tramo userinfo hasta el último `@` del netloc**, en memoria.
Scheme/case, autoridad restante, hostname/puerto y path originales se conservan
exactamente; no se elige otro destino. El URL resultante se revalida con
`Configuration.from_urls`: cualquier query, fragment, duplicación API, dot segment,
transporte u otro rechazo sigue bloqueado. El prefijo `/api` sigue la construcción
original del lector; no se introduce otra ruta ni normalización adicional.

Credenciales distintas, userinfo ausente, broker fuera del guard, input inválido,
fuente alterada o cualquier otro rechazo dejan **requests0 y STOP**, sin alternativa.
No env write, configuración persistente, Secret Manager, rotación, TLS-disable,
redirects o retries. BasicAuth continúa usando las mismas credenciales del broker.
Default/argv distinto de `--inspect` no lee entorno ni inicia transporte.

## 3. Output y presupuesto

Recibo canónico preservado: flags readonly/no-retry/STOP/topología, requests con
operación/etapa/etiqueta/plantilla `{vhost}`/status/bytes/tiempo/error fijo y totales
iniciados, respuestas y cuerpos completados separados. Solo agrega booleanos
`userinfo_normalization_applied` y `same_target_verified`.
Nunca emite URL, host/vhost reales, credenciales, headers/body, longitudes/hashes
de secretos, stderr crudo o traceback; únicamente se hashean fuentes.

Errores propios cerrados: `canonical_source_mismatch`,
`normalization_input_invalid`, `normalization_requirements_not_met`,
`normalization_tool_failed`, `normalization_cancelled`, `explicit_inspect_required`.
Conserva los errores fijos del canon y `management_http_<status>` acotado.
Ante interrupción/desconocimiento del progreso, los tres counters son **null**, no
un cero inventado. Eso siempre implica STOP y no autoriza repetición.

| Control | Alcance/límite |
| --- | --- |
| Selección previa | Un único sheets-worker running, ID e imagen/digest aprobados. |
| Imagen | `sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`. |
| HTTP | GET secuenciales de las mismas diez colas metadata+bindings y tres exchanges; máximo23. |
| Canon |≤4s/request,≤60s lectura,≤64KiB/body y≤5s cleanup; primer error STOP. |
| Procesos | Reader hardalarm80s, Docker exec95s, supervisor remoto150s. |
| Caller | Coordinador impone130s más grupo/cleanup5s; operación completa≤300s. |
| Otros | Cero Meli, conexiones/publish/declare AMQP o mutaciones. |

El hardalarm emite un único JSON cerrado con progreso desconocido y termina
**solo el Python transitorio creado por docker exec**, con `os._exit(2)`; no señala
ni termina el worker PID1. Esto evita que un catch seguro capture SystemExit,
anule el deadline o emita dos recibos. Fuera de ese deadline, cleanup sigue el canon.

El supervisor no forwardea variables: `ps`, `inspect`, `image inspect` y un exec.
Valida keys exactas, enums, recursos/plantillas GET seleccionados, counts0..23
(o null solo en interrupción explícita), relación de contadores, normalización,
flags/STOP, metadata seleccionada y timestamps finitos. Claves duplicadas, campos
extra, URL cruda, métodos distintos o recibo inseguro se descartan, nunca se imprimen.

## 4. RED/GREEN y hashes

| Evidencia privada | Resultado |
| --- | --- |
| `RED.log` / `RED-receipt.json` | exit1, reader ausente, antes de behavior. |
| `supervisor-RED.log` / `supervisor-RED-receipt.json` | Reader16 PASS; doce errores por supervisor ausente, antes de su behavior. |
| `GREEN-1.log` | 28 PASS con MockTransport/fake Docker. |
| `deadline-RED.log` | 30 tests, un error: hardalarm+SystemExit capturado producía dos JSON. |
| `GREEN-2.log` | 30 PASS después del hard-exit propio, incluyendo deadline de un solo JSON. |
| `final-unittest.log` | **30 PASS**, cero skips, 0.635s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` | PASS en tres fuentes, sin reducir checks. |
| `representative-no-env-stdout.json`, `representative-no-env-stderr.log` | stdin sin env: exit2, requests0, JSON seguro, stderr vacío. |
| `source-binding-receipt.json` | Canon exacto, embedding final exacto, entregas previas intactas, AST host3.9 PASS. |

Entradas sintéticas, sockets/DNS prohibidos en reader tests, MockTransport y Docker
fake. Casos:23GET, mismo destino/auth,400/404 STOP1, credenciales distintas y demás
rechazos0, body bound, clock/deadline, cleanup, logs sin secretos, tamper, recibos
cerrados positivos/negativos y stdin. **No suite general ni runtime host3.9 probado.**

| Fuente privada | SHA256 final |
| --- | --- |
| `normalized_reader.py` | `4d391872cc8c32eb021590b266e713de155502f7ae839b2f49451aa28d6b941c` |
| `normalized_supervisor.py` | `f4fc93d91690ab0a83a8ab2332b5538e0b2e395571125b0d34286a60263a6825` |
| `test_normalized_reader.py` | `5bfbd69b242e8190395ce392f8a2d14baefab14b332085ba7596e76669723448` |

Hash de este informe y cuatro paths en `delivery-receipt.json`, sin autorreferencia.

La [documentación HTTP de CloudAMQP](https://www.cloudamqp.com/docs/http.html)
aportada por el coordinador describe Management HTTPS443/BasicAuth RabbitMQ;
no se usa Console API key. La operación productiva queda exclusivamente en sus
manos, bajo ledger/autoridad: esta entrega no la ejecuta ni presupone topología
sana, publicación confirmada, entrega real, rollout o aceptación del piloto.
**ENTREGADO; NO SIGO MODIFICANDO.**
