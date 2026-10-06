# ZelerData AMQP — solo dos listados de definitions preparados

**ENTREGADO; NO SIGO MODIFICANDO.**17 pruebas fake PASS/0skip, ruff/formato/
mypy de tres fuentes PASS. Este especialista no ejecutó producción ni probe2.
Propiedad devuelta a Root, único operador productivo/Git/build.

## Propósito y Quick path

El primer probe real de Root terminó policy_invalid **antes** de publicar:
1GETmetadata,0publish/get/ACK y dos recursos propios borrados confirmados;
TCPssl_error/remotecloseFalse permanecen. No recrear la pareja ni repetir probe
para aprender el patrón. Véase [ledger](zelerdata-historico-paralelo.md), resultado
AMQP-ISOLATED-DELAY-PROBE-1 y alcance siguiente de definitions.

1. Root verifica autoridad,identidadold79f y cuatroSHA; prepara caller acotado.
2. Una CLI explícita `--inspect-policy-definitions`, máximo dos GET únicos.
3. Revisar las definitions/prioridades/clasificación. **No whitelist automático**,
   policywrite ni otro probe por un diagnóstico GREEN. STOPprimererror sin fallback.

## Cuatro paths exclusivos

Directorio0700:
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-policy-definitions-20261006`.

| Path | Rol |
| --- | --- |
| `<privado>/policy_definitions.py` |Solo lectura de dos listados, parser/sanitización cerrados. |
| `<privado>/policy_supervisor.py` |Stdlibhost3.9, hash/digest, un exec y receiptvalidado. |
| `<privado>/test_policy_definitions.py` |9reader +3pure +5supervisor:17≤18. |
| `docs/sheets/zelerdata-historico-amqp-politicas-temporales-informe.md` |Este informe. |

Fuentes0600 y nuevos logs/recibosO_EXCL soloDIR nuevo.40 hashes de diez entregas
previas, auditoría4110 y ROOT/GREEN385a verificados intactos; originales/helpers/
reports/logs y causa del probeFAIL conservados. No shared/cfg/core/CUOTAS/deps/
lock/Git/build/generaltests/otrosagentes. Sin red/Docker/Mongo reales del especialista.

## Contrato exacto: dos GET, cero AMQP

Una instanciaHTTPX y mismo Managementtarget/BasicAuth runtime; normalizaciónuserINFO
solo enmemoria por sourcefrozen4d391872… y canon66e9959a…, hashes verificados.
Solo RABBITMQ_URL y RABBITMQ_MANAGEMENT_URL in-process; sin envforward o archivoenv.
Default sin CLI no lee env/transporte. No TLSdisable, redirects, retries o auth/URLfallback.

1. `/api/policies/{vhost}`.
2. `/api/operator-policies/{vhost}`.

Mismo vhost de configuración, identityde cada regla validada enmemoria; ningún
foreignvhost/colas/hashesnombres/queuenonce a recuperar. Arrays únicamente;
≤50entries **TOTAL** entre ambos listados,64KiB porbody, contentencodingidentity,
ContentLength/JSONdupes/shapes/types failclosed. No paginación, tercerGET o consultas
auxiliares. Body/pattern/name/vhost completos jamás se guardan o imprimen.

Deadline4s porrequest/20sreadTOTAL/cleanupHTTP5s/hard45/exec60/remoto120/
rootcaller130+grupo5/total≤300s. STOPprimererror/inconsistencia/unsupported/timeout;
clientepropio cerrado sin retries. KnownManagement51previos +≤2=≤53, consumos
anteriores y primerintento viejoGETdesconocidos intactos, no reset/renovación de nada.
AMQP/resource/declarations/mutations/publish/provider/Meli/Mongo0 por diseño.

## Output cerrado: información pública mínima

Cada row solo: kind(sequenceporlista),priorityint32signado,apply_toenum,
regex_supported/representative_match,definitionreconocida,unknown_key_count,
requires_reviewTrue. No policynames/rawpatterns/unknownkeynames/rawvalues/hosts/
vhost/URI/exceptionstr/traceback/stdError. Counts de listas no observadas o forma
inaceptable=null, nunca asumir0; progresoHTTP conocido preservado, hardtimeoutunknown=null.

Valores de definition reconocidos:

| Key pública | Valor permitido emitido |
| --- | --- |
| expires |int>0,≤int64máximo; bool no esint. |
| max-length,max-length-bytes,message-ttl |int≥0,≤int64máximo. |
| delivery-limit |int≥−1,≤int64máximo. |
| overflow |drop-head/reject-publish/reject-publish-dlx. |
| dead-letter-exchange,dead-letter-routing-key |Solo relaciónenum:own/default/business/unexpected; nunca valor original. |

`default` significa valorliteralvacío; `business` solo recursoscanónicos conocidos.
**`own` SOLO routingkey igual al REPRESENTANTE SINTÉTICO**, no ownership ni
identidad de una cola real. Cualquier otro valor esunexpected; un nombre amq.gen
arbitrario jamás se reconoce como propio. Unknownkeys solo se cuentan, valores/
tipos no se interpretan ni imprimen. Tipo inválido en key conocida→STOP.

Apply_to cerrado:all/queues/classic_queues/quorum_queues/exchanges. Patrón se
compara SOLO con `amq.gen-` +22letrasA, nunca con nombre real/borrado ni secret.
Regex_support no equivale a scopeaplicable/prioridadganadora o policyefectiva.
Actualqueuepolicy/effectiveconfiguration/probe_retry_authorized **siempreFalse**.

## Regex y límites de interpretación

SubsetASCII≤256characters,anchors/literals/escapescomunes/charclasses/groups
no repetidos y lookaheads simples; máximo un cuantificador deátomo.
Sin alternation, backrefs, lookbehind, flagsPCRE ni quantifiedgroups; bounds{n,m}≤64.
Fuera del subset o re.error/type invalid: **match=null, STOP**, no falsematch.
Esto limita backtracking y no finge equivalencia con PCRE arbitrario.

Si el regexunsupported aparece con row validada, se conserva su definition pública
parcial, prioridad/apply_to y unknowncount; no se gasta el GET siguiente.
La coincidencia del único ejemplo NO garantiza comportamiento para la cola
real aleatoria anterior ni para otra futura; no recuperar nombres borrados.
Root debe combinar/revisar reglas y prevalencia, **no** habilitarTTL/DLX/caps
por estos valores sin gate real posterior. Se informa, no se muta servidor.

## RED/GREEN y límites de evidencia

| Artefacto | Resultado |
| --- | --- |
| RED.log |Módulo reader ausente antes de behavior. |
| supervisor-RED.log |12PASS +5errores por supervisor ausente, antes de su behavior. |
| GREEN-1.log |17PASS inicial. |
| ruff-first/fix/formatted,mypy-first |Errores originales de layout/tipos preservados; sin reducir gates/skips. |
| final-unittest.log |17PASS/0skip,0.179s. |
| final-ruff/final-format/final-mypy |PASS tres fuentes. |
| source-binding-receipt.json |embedding/normalized4d391/canon66e995/ASTsup3.9 y40previos+audit/logPASS. |
| representative-no-env-stdout.json/stderr.log |stdinCLI sinenvexit2/requests0/JSONcerrado/stderr vacío. |

MockHTTP/fakes, sin sockets/DNS/puertos/Docker/DB/productivo. Casos cubren doslistas,
redacción, scope, primerHTTPerror, body/entrybounds, JSON/shapes/numericbool,
regexunsupported+null, default/noenv/sourcemismatch, logs, timeout, enum/relations,
receiptpositivo/unknown/claims/hash/drift/budget. Sin nuevas rondas/casos/research
tras GREEN ycalidad, salvo corrección necesaria de errores de esta unidad.

## Hashes finales y entrega

- `policy_definitions.py`: `266b039a470b11edc68ff893ab3e0fefa6c9d5de6b8037c827fece9723ab860b`
- `policy_supervisor.py`: `ea8546504970ffc53428ec107f6462317db2b07989425915774847b95883232b`
- `test_policy_definitions.py`: `57ce299262b97bcc86f30cded0e65ad355a08e731400482e2f2ab200a69ab819`

Cuatro hashes(incluido informe) en `<privado>/delivery-receipt.json`.
**ENTREGADO; NO SIGO MODIFICANDO.** No se afirma policy real causante resuelta,
probe/timingpassed ni aceptación ZelerData. Root decidirá con los dos listados.
