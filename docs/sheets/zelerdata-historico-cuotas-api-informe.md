# CUOTAS — prueba operador de API normal parcial

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local solamente. Root instala/ejecuta en el proyecto privado Apps Script existente de Lalo y conserva registro único. No backend ni producción modificados por este especialista.

## Entrega exacta

Directorio privado `/Users/eduardoramirez/.codex/cache/zelerdata-integracion-20261005-8dafff186997/normal-api-proof-20261006`:

- `normal_api_proof.gs`: `ZelerDataPilotNormalApiProofV1()` sin argumentos ejecuta el callback y devuelve receipt cerrado sin Logger/console. `ZelerDataPilotNormalApiProofRunV1()` es el entrypoint Editor Run: llama V1 exactamente una vez y hace un único Logger.log de JSON reconstruido con whitelist estricta (no body, token, args, IDs, texto libre ni campos desconocidos). Sin customfunction, menu, trigger ni escritura de celdas/Properties.
- `test_normal_api_proof.cjs`: 22 fakes Node offline, sin red/DB/puertos/credenciales.
- Este informe, único documento nuevo del encargo.

## Gates antes de ejecución Root

1. Verificar identidad del proyecto existente/cuenta Lalo, bytes SHA de la función y presencia de los helpers ya guardados. No crear token/grant ni leer/copiar UserProperties desde fuera: la función usa solo `getZelerDataExtensionToken_()`.
2. Probar contexto backend Mongo-only/recovery OFF por evidencia Root. La función solo cuenta sus POST al API; **no** puede probar cero requests Meli internos: receipt `direct_provider_requests=0`, `provider_zero_verified=false`.
3. Seleccionar rango realmente no certificado. Default HOPEMOB, Sep25–Oct5 de2026, estado todos, compradores vacío, encabezados si. Si Root cambia el rango por progreso real, requiere nuevo payload SHA y rerun del fake de argumentos; no fabricar falta de readiness ni cambiar la selección durante la función.
4. Endpoint derivado por `zelerdataBuildEndpoint_(getZelerDataApiBaseUrl_())` debe ser exactamente `https://sheets.zeler.ai/sheets/formulas:execute`. Redirects OFF y validación TLS ON; no otro destinatario/fallback.

Root invoca `ZelerDataPilotNormalApiProofRunV1()` explícitamente una sola vez desde Editor Run y recoge el único JSON sanitizado del log; Editor Run ignora el return del callback. El wrapper no añade HTTP/retries. No instalar fórmula en celda ni usar su resultado como prueba Sheet. Sin argumentos aceptados, no token suministrable por caller.

## Dos POST máximo, sin retries

Normal contrato existente: formula `ZELERDATA_ORDENES`, cuenta y args arriba, request_id generado por `Utilities.getUuid()` (distinto en ambos POST, no execution_id), Authorization solo en memoria/HTTP al endpoint autorizado. Primer payload top-level `allow_partial:true`; segundo `false` con exactamente iguales args.

**Primero:** HTTP200 y envelope `ok:true`; coverage `exact:false`, `scope:acquired_rows_only`, `reason:requested_range_not_certified`, pending_count null. Orders_count entero positivo (bool/negativo rechazados), tabla con aviso full-width PARCIAL + header ID Orden + filas útiles con identidad no vacía y width uniforme. Exacttrue, valores vacíos, metadata/stringfalse/bogus, aviso/header ausente o error: STOP, nunca consume segundo POST.

**Control:** solo HTTP200 con envelope `ok:false` y code DATA_UNAVAILABLE o PROCESSING prueba el guard exacto. Otro resultado/error, inclusive exact200OK,429,5xx,redirects,network,JSON/shape: STOP. No tercer request.

Receipt permite únicamente enums fijos, bool, status numérico y counts; nunca token, UUID, body, datos/texto/IDs, request payload ni mensaje libre. `proven:true` acredita únicamente este contrato normal parcial+control; `native_sheet_proven:false` siempre. No acredita cinco fuentes/año, backend0Meli, dos cambios incrementales ni objetivo completo.

## Deadline honesto

Corrección factual por evidencia oficial actual: **UrlFetch sí ofrece `timeoutSeconds` Integer**, default360s en documentación actualizada2026-05-15. Se fija `timeoutSeconds:9` en ambos POST y receipt `configured_timeout_seconds:9`; la afirmación anterior "no configurable" era obsoleta. [Documentación oficial Google, fetch(url, params), Advanced parameters](https://developers.google.com/apps-script/reference/url-fetch/url-fetch-app#fetchurl,-params).

Checks antes/después de cada fetch y al terminar rechazan elapsed>=20000ms o clock negativo; si primer fetch consume el tiempo, nunca inicia segundo. Opción SDK documentada/configurada **no** prueba cancelación real ni garantía wall20: receipt `transport_deadline_guaranteed:false` permanece; deadline_observed indica tiempo observado al retorno. Timeout del caller o ejecución sin receipt/log deja counts/result desconocidos y exige STOP del ledger Root, no repetición automática. Root no debe asumir cancelación por timeout externo.

## TDD y controles locales

- `red.log`: 20 FAIL contra stub antes de comportamiento.
- Primer `green.log`:20 PASS.
- `red-empty-row.log`:1 FAIL antes de cerrar falsa utilidad por fila sin identidad (mismo caso existente, no nuevo alcance).
- Baseline `final-green.log`:20 PASS / 0 FAIL, preservado.
- `red-timeout.log`:1 FAIL antes de añadir timeoutSeconds9 y metadata; `green-timeout.log`:20 PASS.
- `red-wrapper.log`:2 FAIL antes del entrypoint Editor Run/whitelist.
- Final `green-wrapper.log`: **22 PASS / 0 FAIL**; `syntax-wrapper.log` y `gas-syntax-wrapper.log` PASS. Tests wrapper acreditan exact-one-call/max2POST, un único JSON Logger y rechazo de receipt forjado con rawfields/freeerror/secret.
- `syntax.log`: `node --check test_normal_api_proof.cjs` PASS.
- `gas-syntax.log`: parse `vm.Script` de GS PASS. La suite ejecuta realmente la función en sandbox con fake helpers/UrlFetch, spies que prohíben console/properties/cells y Logger en V1; RunV1 permite únicamente un log sanitizado y marcador sintético de secretos/negocio no retornable.

Backups `.before-timeout.bak` preservan exactamente los hashes entregados previamente (GS4c63d243, test21431630, informe53e55a4b). Logs nuevos O_EXCL0600 preservados. Env whitelisted sin Mongo/AMQP ni secretos; no dependencias instaladas. Ruff/Mypy no aplican a estos dos archivos JavaScript; no hubo Python ni código compartido que validar. Fakes/parse no prueban transporte Apps Script, sesión Google, token real ni producción.

## Referencias locales verificadas

- `modules/sheets/apps_script/sheetseller/Client.gs:1-33`: helper token, payload normal, bearer y endpoint canónico.
- `modules/sheets/apps_script/sheetseller/Formulas.gs:418-429`: args ORDЕNES, todos/buyer/header.
- `modules/sheets/src/zeler_sheets/formulas/handlers_orders_questions.py:159-272`: opt-in interno desde API, notice antes del header, coverage y orders_count.
- `modules/sheets/tests/test_partial_history_api.py:55-88,135-166`: contrato normal partial/default, empty nozero certificado y certified opt-in no partial.
- Lessons L-028: pruebas por intervalo independiente; normal API no sustituye native Sheet ni cobertura fuente completa.

## Hashes SHA-256

- normal_api_proof.gs: `348b7cff59c9c9c6e850f9ca04bb797ebad1a3a36f42ad1954e655fbd932e5d8`
- test_normal_api_proof.cjs: `0b0cee6ac007ecaf51e4746cf2517d4730ae215166433c05f1a6e7081b78cf9e`

Hash del informe entregado por chat para evitar autorreferencia. Tras esta entrega no sigo modificando ni ejecutando pruebas.
