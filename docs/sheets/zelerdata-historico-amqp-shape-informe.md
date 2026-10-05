# ZelerData AMQP — regla de Management: preparación local completa

**ENTREGADO; NO SIGO MODIFICANDO.** Herramienta diferenciada de forma, sin red,
preparada el 5 de octubre de 2026. **56 unittest offline PASS**, cero skips;
ruff, formato y mypy enfocados PASS en tres fuentes privadas.
No producción ejecutada por este especialista ni estado remoto nuevo acreditado.

La inspección anterior del coordinador quedó consumida/STOP con
`management_explicit_invalid`: broker y Management presentes/no vacíos, cero
HTTP/AMQP/Meli/mutaciones. Esta entrega distingue la regla concreta sin volver
a ejecutar ese diagnóstico agregado, corregir configuración o probar rutas.

## Quick path del coordinador

1. Verificar permiso de inspección diferenciada y ledger; conservar intentos previos.
2. Verificar los hashes y binding final inspector/supervisor.
3. Ejecutar una sola inspección autorizada en el worker/digest aprobado, con caller
   acotado; registrar un recibo nuevo. Primer error STOP; no retries ni fallback.
4. Decidir cualquier lectura Management posterior bajo su autoridad concreta.
   La herramienta siempre termina con cero red, incluso si config pasa.

Referencias: [informe de configuración anterior](zelerdata-historico-amqp-config-informe.md),
[ledger](zelerdata-historico-paralelo.md) y
[validador canónico](../../infra/operations/zelerdata_amqp_delay_readonly.py).

## 1. Cuatro paths y preservación

Directorio privado nuevo: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-management-shape-20261005`.
Directorio `0700`; fuentes privadas `0600`.

| Path asignado | Contenido |
| --- | --- |
| `<privado>/shape_inspection.py` | Inspector standalone por stdin en Python 3.11 del worker. |
| `<privado>/shape_supervisor.py` | Supervisor stdlib por stdin al Python del host; sintaxis 3.9 comprobada por AST. |
| `<privado>/test_shape_inspection.py` | 29 pruebas del inspector/equivalencia y 27 del supervisor fake. |
| `docs/sheets/zelerdata-historico-amqp-shape-informe.md` | Este informe propio. |

Logs/cache/recibos propios están confinados al directorio privado. La entrega
anterior `config_*` y su informe conservan todos sus hashes. No se modificaron
runtime, core, CUOTAS, documentos centrales, dependencias ni lockfiles.
Sin Docker real, puertos, Mongo, red, gcloud, builds, Git mutante o subagentes.

## 2. Fuente exacta y outputs seguros

Lee **solo dos variables** del proceso: `RABBITMQ_URL` y
`RABBITMQ_MANAGEMENT_URL`; no admite forwarding, env files o valores por argv.
Reutiliza `Configuration.from_urls` y `GateError` del lector congelado SHA256
`66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.

AST extrae las clases/imports puros y los **ocho operandos exactos** del guard
Management, conservando orden: host, usuario, password, query, fragment,
transporte, componente `api` repetido y dot segments. No copia predicados
divergentes ni importa HTTPX/main/transporte. La clasificación compara su
aceptación con el validador real; divergencia produce `validator_equivalence_failed`.
El prefijo local se calcula como lo hace el canon para validar, no para modificar
variables, persistir una URL normalizada o iniciar una petición.

| Primer rechazo concreto | `reason_code` |
| --- | --- |
| Parse de Management | `management_parse_invalid` |
| Puerto inválido | `management_port_invalid` |
| Host ausente | `management_host_missing` |
| Userinfo presente | `management_userinfo_forbidden` |
| Query / fragment | `management_query_forbidden` / `management_fragment_forbidden` |
| Transporte no admitido | `management_transport_forbidden` |
| Componente `api` duplicado / dot segment | `management_duplicate_api_component` / `management_dot_segment_forbidden` |
| Marcador público exacto de template | `placeholder_unresolved` |

Además: `configuration_valid`, `broker_configuration_invalid`,
`management_required_for_non_tls_broker`, `management_derived_invalid`,
`explicit_inspect_required`, `configuration_input_invalid`,
`validator_integrity_invalid`, `validator_structure_invalid`, `inspection_failed`,
`inspection_cancelled` y el fallo de equivalencia anterior. Lista cerrada.

Flags booleanos nuevos: `management_examined`, `management_parse_valid`,
`management_port_valid`, `management_host_present`, `management_userinfo_present`,
`management_query_present`, `management_fragment_present`,
`management_transport_allowed`, `management_duplicate_api_component`,
`management_dot_segment_present`, `management_placeholder_recognized` y
`broker_cloudamqp_host`. Este último solo comprueba que el hostname parseado
termina en `.cloudamqp.com`; no verifica DNS/conectividad ni muestra el hostname.
Si no se examinó Management o falló su parse, los flags posteriores quedan false
por default: **no prueban ausencia de esos componentes**.

`management_userinfo_matches_broker` es únicamente bool/null: compara credenciales
decodificadas como el canon, sin valores. Null significa no comparadas; igualdad
no prueba autenticación ni habilita su uso. Los demás campos son los booleanos
comunes de presencia/ejecución/validez/STOP, `management_source` cerrado y cuatro
contadores enteros exactamente cero: `management_http_requests`,
`amqp_connections`, `meli_get`, `mutations`.

Prohibido: valores/env completo, URL, host/vhost/path reales, credenciales,
query/fragment reales, headers/body, longitudes/hashes de secretos, excepciones
libres o traceback. Solo se hashean fuentes. No se inicia HTTP ni se deriva un
endpoint para utilizarlo; no normalización de configuración, corrección o fallback.

## 3. Supervisor y presupuestos

Selección de un único sheets-worker running, ID/digest verificados antes del exec.
Imagen esperada: `sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`.
Únicos Docker calls: `ps`, `inspect`, `image inspect` y un `exec`, sin env overrides.

- Inspector: SIGALRM55s; timeout Docker60s, reserva cleanup5s.
- Supervisor remoto: SIGALRM150s; setup calls individuales≤5s.
- Caller del coordinador:≤285s y cleanup dentro de≤300s totales.
- Always0 HTTP/AMQP/Meli/mutaciones propias; no describe tráfico concurrente.

stdout cerrado: recibo anidado validado o null y códigos fijos de setup/identidad,
hash, deadline, ejecución o recibo inválido. Valida keys exactas, tipos/enums,
contador0 (no bool), no duplicadas, body≤8192bytes y coherencia de motivo con
flags/source/presencia/STOP. No pasa stderr o JSON crudo. Gate fallido antes de
exec impide iniciarlo; gate fallido después exige STOP, nunca segundo intento.
La sintaxis host3.9 está comprobada, **no se ejecutó ni sondeó su runtime real**.

## 4. Evidencia local y hashes

| Evidencia privada | Resultado |
| --- | --- |
| `RED.log` | exit1, inspector aún ausente, antes de behavior. |
| `initial-rules-RED.log` | Primera guard-shape expectativa falló; canon tiene ocho operandos, no nueve. Fail-closed corregido contra AST/fuente exacta. |
| `supervisor-RED.log` | 56 tests: inspector29 PASS; 27 errores por supervisor aún ausente, antes de su behavior. |
| `GREEN-1.log` | 56 PASS, 0.350s. |
| `final-unittest.log` | **56 PASS**, cero skips, 0.348s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` | PASS, tres fuentes, sin reducir checks. |
| `representative-no-env-stdout.json`, `representative-no-env-stderr.log` | stdin sin env: exit2, JSON seguro `broker_configuration_invalid`, stderr vacío. |
| `source-binding-receipt.json` | Embedding final exacto; entrega config anterior intacta; AST supervisor3.9 PASS. |

Tests stdlib/unittest, entradas sintéticas; sockets/DNS prohibidos y Docker fake.
Incluyen equivalencia con el canon, prioridad de reglas, placeholder público,
suffix boundary del host, igualdad/userinfo codificado, shapes, cancelación,
tamper, recibos inseguros/incongruentes y runner stdin. Sin suite general.

| Fuente privada | SHA256 final |
| --- | --- |
| `shape_inspection.py` | `ed55f5b4226835ee1e615c0688025e41a7ca647cd75292afc078ac6474a8f139` |
| `shape_supervisor.py` | `e2835a65c4c0dfe305e10624c604db026dd72b9ce6a5f937f580ffedb5d5a8df` |
| `test_shape_inspection.py` | `b831af1f8d8ce18e07e4766086f1c85973fc999661e83d58c6fcee893e0b4f30` |

Hash del informe y relevo de cuatro paths en `delivery-receipt.json`, fuera del
informe para evitar autorreferencia. Todos los logs previos quedan preservados.

## 5. Formato/origen: hallazgos estáticos, no hechos remotos

- `infra/gce/env-templates/sheets-worker.env.template:7–9` contiene ambos placeholders;
  Management se describe solo como endpoint HTTP de preflight. No establece su
  forma real ni demuestra que un placeholder haya quedado en producción.
- `infra/gce/zeler-platform-secrets.sh:48–49,149–155` obtiene `cloudamqp-url` y
  `cloudamqp-management-url` y entrega Management directamente al worker, sin
  validación/transformación de formato allí. No se ejecutó ni leyó ningún secret.
- `gateway/src/zeler_gateway/config.py:50` define `RABBITMQ_URL`;
  `modules/sheets/src/zeler_sheets/app.py:151–156` usa ese URL para readiness.
  Esos contratos no prueban que la URL Management sea aceptada por el lector.

El coordinador aportó documentación primaria de
[CloudAMQP HTTP API](https://www.cloudamqp.com/docs/http.html): Management HTTPS443
con BasicAuth RabbitMQ. La [Console API](https://www.cloudamqp.com/docs/api.html)
es distinta; no usar su API key ni otro endpoint como fallback.
Este especialista no consultó red ni deduce valores/estado remoto de estas fuentes.

Ownership devuelto al coordinador. Solo él conserva ledger, decide continuación
legítima y ejecuta producción. La lectura Management≤23GET/60s, si procede bajo
autoridad concreta, no forma parte de esta herramienta ni de esta entrega.
**ENTREGADO; NO SIGO MODIFICANDO.**
