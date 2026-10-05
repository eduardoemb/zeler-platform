# ZelerData AMQP — inspección estructural preparada, sin producción

**ENTREGA LOCAL COMPLETA; operación productiva NO ejecutada por AMQP.**
Preparación del 5 de octubre de 2026: inspector puro y supervisor de una sola
ejecución, **72 pruebas offline PASS**, ruff, formato y mypy enfocados PASS.
La repetición anterior `AMQP-REPEAT-1` permanece consumida con
`management_configuration_invalid`, cero GET y STOP. Estos resultados nuevos
no identifican su rama remota, no corrigen configuración ni acreditan aceptación.

## Quick path del coordinador

1. Verificar autorización concreta y ledger; no reutilizar la excepción agotada.
2. Verificar hashes de esta entrega y binding del inspector dentro del supervisor.
3. Ejecutar únicamente la inspección autorizada en el worker/digest aprobado,
   bajo caller acotado; conservar recibo nuevo sin sobrescribir evidencia.
4. STOP ante cualquier gate. Incluso `configuration_valid` demuestra únicamente
   estructura permitida: esta herramienta nunca inicia HTTP ni autoriza al lector.

Referencias: [informe AMQP original](zelerdata-historico-amqp-informe.md),
[coordinación y ledger](zelerdata-historico-paralelo.md) y
[lector canónico](../../infra/operations/zelerdata_amqp_delay_readonly.py).
Los originales y sus hashes anteriores permanecen intactos.

## 1. Ownership y archivos exactos

Directorio privado nuevo:
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-config-inspection-20261005`.
Modo del directorio `0700`; las tres fuentes privadas son `0600`.

| Archivo asignado | Entrega |
| --- | --- |
| `<privado>/config_inspection.py` | Inspector standalone por stdin en Python 3.11 del worker. |
| `<privado>/config_supervisor.py` | Supervisor standalone por stdin al Python del host; stdlib y sintaxis compatible con Python 3.9. |
| `<privado>/test_config_inspection.py` | Unittest offline: 45 casos del inspector y 27 del supervisor. |
| `docs/sheets/zelerdata-historico-amqp-config-informe.md` | Este informe propio; sin cambios a documentos centrales. |

Logs, recibos y cache de mypy están confinados al directorio privado propio.
No se modificaron reader/supervisor originales, runtime, configuración compartida,
dependencias, lockfiles, core, CUOTAS ni informes anteriores. Sin subagentes,
Docker real, puertos, Mongo, gcloud, red, Git mutante, builds o producción.

## 2. Contrato reutilizado, no adivinado

El inspector consulta exclusivamente `RABBITMQ_URL` y
`RABBITMQ_MANAGEMENT_URL` del proceso del worker; dos `get`, sin iterar el entorno.
No admite valores por argumentos, forwarding, archivos de entorno ni fallback.

Reutiliza la fuente congelada del lector canónico, SHA256
`66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.
Verifica ese hash y extrae por AST únicamente `GateError`, `Configuration` y sus
imports puros (`__future__`, `dataclasses`, `urllib.parse`). No ejecuta el main
ni importa HTTPX, crea clientes o carga funciones de transporte del lector.
No se duplicaron ni endurecieron unilateralmente sus reglas de configuración.

| Resultado | `management_source` | `reason_code` |
| --- | --- | --- |
| Broker estructuralmente inválido/ausente | `not_examined` | `broker_configuration_invalid` |
| Broker no TLS con Management ausente/vacío | `missing_for_non_tls` | `management_required_for_non_tls_broker` |
| Management explícito rechazado | `explicit` | `management_explicit_invalid` |
| Management derivado TLS rechazado | `derived_tls` | `management_derived_invalid` |
| Estructura permitida | `explicit` o `derived_tls` | `configuration_valid` |

El error explícito sigue agregado: no imprime qué URL, usuario, host, puerto o
segmento fue rechazado. La validación estructural no prueba credenciales vigentes,
conectividad, existencia del endpoint/vhost, topología, entrega ni TTL efectivo.

## 3. Output cerrado y límites

El inspector solo emite estas 15 claves; no imprime diagnostics adicionales:

- Booleanos: `read_only`, `inspection_executed`, `configuration_valid`, `stop`,
  `no_retry`, `broker_present`, `broker_nonempty`, `management_present`,
  `management_nonempty`.
- Enums: `management_source` (cuatro valores de la tabla, incluyendo
  `not_examined`) y `reason_code`.
- Enteros exactamente cero: `management_http_requests`, `amqp_connections`,
  `meli_get`, `mutations`.

Además de los cinco motivos de la tabla, los únicos `reason_code` permitidos son
`explicit_inspect_required`, `configuration_input_invalid`,
`validator_integrity_invalid`, `validator_structure_invalid`, `inspection_failed`
y `inspection_cancelled`. Default/argumentos inválidos no consultan el entorno.

El supervisor emite exactamente `read_only`, `inspection_started`, `no_retry`,
`stop`, `configuration_valid`, `code`, `inspection` y los mismos cuatro contadores
cero. `inspection` es null ante rechazo o contiene el recibo validado completo.
Rechaza claves extras/duplicadas, tamaños mayores a 8192 bytes, booleanos como
contadores, cifras no cero, tipos/enums desconocidos y contradicciones entre
presencia, source, motivo, validez y STOP. Nunca pasa stderr o respuesta cruda.

Sus errores adicionales cerrados son `tool_sha_mismatch`,
`selected_runtime_unavailable`, `selected_runtime_mismatch`,
`selected_image_mismatch`, `supervisor_deadline`, `inspection_receipt_invalid`,
`inspection_setup_error` e `inspection_execution_error`.

**Prohibido:** valores/env completo, URL, host/vhost/path reales, usuario,
contraseña, query/fragment, headers, body, errores libres, traceback, longitudes
o hashes de secretos. Solo se hashean fuentes. Los contadores corresponden a la
operación propia, no al tráfico concurrente de otros procesos del worker.

| Control | Límite preparado |
| --- | --- |
| Identidad antes del exec | Un único sheets-worker running; ID y repo digest aprobados. |
| Imagen esperada | `sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`. |
| Docker calls | `ps`, `inspect`, `image inspect`, un único `exec`; sin modificaciones ni env overrides. |
| Runtime inspector | SIGALRM 55s, timeout Docker 60s: reserva de cleanup 5s. |
| Supervisor remoto | SIGALRM 150s; llamadas de selección limitadas individualmente a 5s. |
| Caller local | Debe imponer el coordinador máximo 285s y cleanup dentro del total 300s. No implementado por este especialista. |
| Tráfico | Siempre 0 HTTP, 0 AMQP, 0 Meli y 0 mutaciones. |

No iniciar inspector ante fuente alterada, worker ausente/ambiguo, identidad o
imagen distinta, deadline o fallo de setup. Después de iniciar, timeout, receipt
inválido, cancelación o cualquier rechazo exige STOP, sin retry ni corrección.
Se conserva el motivo recibido solo tras validar su esquema cerrado.

## 4. RED/GREEN y evidencia local

Python local de pruebas: **3.11.15**. Entorno de pruebas sin MONGO_URI ni las dos
variables Rabbit del operador; entradas únicamente sintéticas. Socket connect,
connect_ex, create_connection y DNS prohibidos en los tests del inspector.
Supervisor probado con Docker fake; ningún Docker real fue invocado.

| Evidencia privada propia | Resultado |
| --- | --- |
| `RED.log` / `RED-receipt.json` | exit1, import ausente `config_inspection`, antes de tool behavior. |
| `GREEN-1.log` | 45 PASS, 0.273s. |
| `supervisor-RED.log` / `supervisor-RED-receipt.json` | exit1, 64 tests: 19 errores por supervisor aún ausente; inspector previo PASS. |
| `supervisor-GREEN-1.log` | 64 PASS, 0.336s. |
| `supervisor-consistency-RED.log` | exit1, 72 tests: un fallo; recibo con source/motivo contradictorios era aceptado. |
| `supervisor-GREEN-2.log` | 72 PASS tras rechazo de ramas/presencias incongruentes. |
| `final-unittest.log` | exit0, **72 PASS**, 0 skips, 0.349s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` | exit0: checks PASS, tres archivos formateados; mypy tres fuentes PASS. |
| `representative-no-env-stdout.json`, `representative-no-env-stderr.log` | stdin sin env: exit2, JSON cerrado `broker_configuration_invalid`, contadores0; stderr vacío. |
| `source-binding-receipt.json` | Inspector final idéntico al embebido, hashes verificados; originales intactos; AST supervisor sintaxis 3.9 PASS. |

Los primeros lint/type checks locales fallaron por estilo/anotaciones; quedaron
corregidos sin reducir los checks. Los logs originales se conservaron.
La prueba AST 3.9 acredita sintaxis, **no ejecución real en Python 3.9 del host**.
No se sondeó su versión ni se cambió nada remoto. No suite general aquí.

## 5. Hashes y relevo

| Fuente privada | SHA256 final |
| --- | --- |
| `config_inspection.py` | `1550e7cc75915a34c31e66c8e441b68091af65054c40ceb7cceb471a9a5760e4` |
| `config_supervisor.py` | `eb9489b8be679c6318c2356ad02a7cc4d7d20ab0c7bed777c4192b73588c110b` |
| `test_config_inspection.py` | `57fbabc59c2d7937b65014658b2e3ab8a6ed889678191b2a953b8ea9d37d82d4` |

El hash de este informe se registra fuera de él en `delivery-receipt.json` para
evitar autorreferencia. El supervisor original conserva SHA256
`31a298ebb985ab934dd15eef5ee3467c93108c566c76874da654f8df52483e70`.

Esta entrega cubre **solo inspección estructural**. El coordinador verifica la
respuesta y ledger antes de una nueva operación productiva; no se vuelven a
pedir permisos condicionales vigentes de builds/despliegue/piloto. Una lectura
Management posterior, incluso si config pasa, necesita autoridad concreta
que la incluya; esta herramienta no la ejecuta ni la concede. No reparación,
inyección, endpoint/credencial alternativos o ampliación del piloto implícitos.

Ownership de los cuatro paths se devuelve al coordinador para validación e
integración. **ENTREGADO; NO SIGO MODIFICANDO.**
