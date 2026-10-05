# ZelerData AMQP — review de policy: UN GET preparado

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local: **29 unittest PASS**,
cero skips; ruff, formato y mypy enfocados PASS en tres fuentes privadas.
No producción ejecutada por AMQP. No lector completo relajado ni policy modificada.

El coordinador informó que su lectura anterior consumió un GET200 de events y
terminó `queue_policy_requires_review`. Esta entrega obtiene únicamente evidencia
efectiva de esa cola para su decisión; no interpreta ese STOP como error del servidor,
ausencia de cola, causa del404 anterior o autorización para ignorar policies.

## Quick path del coordinador

1. Verificar permiso/ledger y hashes; conservar todos los intentos anteriores.
2. Ejecutar **una vez, un GET** del mismo destino/vhost configurado y events.
3. Revisar campos públicos filtrados y documentación. `known_non_lifecycle`
   describe claves, **no declara benignidad global ni salud/entrega**.
4. Cualquier preparación/read23 posterior queda en decisión del coordinador,
   bajo alcance concreto; esta herramienta nunca continúa hacia bindings.

## Archivos exactos y preservación

Privado: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-policy-review-20261005`.
Directorio0700, fuentes0600; logs/recibos/cache propios confinados ahí.

| Path asignado | Entrega |
| --- | --- |
| `<privado>/policy_inspection.py` | UNGET metadata, normalizador anterior puro y clasificador separado. |
| `<privado>/policy_supervisor.py` | Selección/hash/digest y un exec; stdout cerrado. |
| `<privado>/test_policy_inspection.py` | 14 pruebas puras, ocho HTTPMock y siete supervisorfake. |
| `docs/sheets/zelerdata-historico-amqp-politica-informe.md` | Este informe propio. |

Los tres deliveries anteriores y sus informes conservan todos sus hashes.
Helper normalizado congelado SHA `4d391872cc8c32eb021590b266e713de155502f7ae839b2f49451aa28d6b941c`,
canon SHA `66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.
Sin runtime/core/CUOTAS/docs centrales/deps/lockfiles/Git/builds/puertos/Mongo,
Docker real o subagentes. Solo se consultaron documentos públicos oficiales.

## Campos seguros y clasificación mínima

Endpoint único: plantilla `/api/queues/{vhost}/zeler.sheets.events`, métodoGET.
Mismo destino y BasicAuth ya configurados; solo userinfo coincidente quitado en
memoria por helper anterior. Sin otra URL/auth, discovery, export o conexión AMQP.

- Policy/operatorpolicy: **presencia y forma válidas únicamente**, nunca nombres.
- Efectiva: validez/empty, valores conocidos filtrados, `unknown_key_count`,
  flags lifecycle/review-only; sin keys desconocidas ni sus valores.
- Metadata: queue type cerrado classic/quorum/stream/unknown/null, counts ready,
  unacked y consumers no negativos o null; argumentosTTL/DLX esperados verificados.
- Stats: un request máximo, status/bytes/truncación/tiempo/cleanup y errores fijos;
  topología, publicación confirmada y timing real siempre false.

Whitelist mínima: `ha-mode` all/exactly/nodes; `ha-sync-mode` automatic/manual;
`queue-mode` default/lazy; `ha-params` y `ha-sync-batch-size` enteros positivos.
Nodes requiere review: **no se emiten listas/nombres de nodos ni su longitud**.
También se muestran, si su valor tiene forma segura, keys públicas de lifecycle
(`message-ttl`, `expires`, `max-length`, `max-length-bytes`, `delivery-limit`,
`overflow`, DLX/routing-key) y review-only (promoción HA, queue-version).
Los strings DLX solo salen si coinciden con recursos canónicos públicos; otros
strings se omiten y la definición deja de considerarse validada.

| Clasificador puro | Condición |
| --- | --- |
| `empty_no_operator` | Definición efectiva vacía/validada y sin operator, aunque policyName exista. |
| `known_non_lifecycle` | Solo whitelist documentada válida, sin operator/lifecycle/review-only/unknown. |
| `requires_review` /STOP | Operator, lifecycle/cap/TTL/DLX/overflow/delivery-limit, desconocidos, forma no acreditada o perfil de cola inválido. |

Para verificar solo argumentos/identidad/counts, se llama `_queue` canónico sobre
**copia local** con los campos policy apartados. Metadata original permanece intacta;
esta comprobación no aprueba/ignora la policy ni relaja el lector23. Defaults false
o countsnull sin metadata examinada no prueban ausencia ni cero backlog.
Prohibidos nombres, host/vhost/URL/credenciales, body/headers, traceback y hashes/
longitudes de secretos. Se hashean solamente fuentes.

## Documentación primaria y límites de inferencia

Mirroring configura réplicas/sincronización, no TTL ni límites de longitud; fue
retirado desde RabbitMQ4.0. Promover réplicas no sincronizadas puede perder datos:
se conserva review-only, no aprobación automática. [RabbitMQ3.13 mirroring](https://www.rabbitmq.com/docs/3.13/ha).

Queue mode lazy/default afecta almacenamiento; desde3.12 se ignora esa selección.
No se infiere versión real ni comportamiento efectivo del servidor.
[RabbitMQ lazy queues](https://www.rabbitmq.com/docs/lazy-queues).

Operator policies pueden imponer límites y prevalecer sobre argumentos de aplicación;
su presencia siempre exige review aquí. [RabbitMQ policies](https://www.rabbitmq.com/docs/policies).

## Presupuesto y evidencia

Un worker running/digest anterior aprobado79f5, un exec, ninguna variable forwardeada.
GET≤4s; lectura≤60s/body≤64KiB; cleanup≤5s. Hardalarm80 del Python transitorio,
exec95, remoto150; caller del coordinador130+grupo5 y total≤300s. Progreso desconocido
se conserva null. No segundo GET incluso ante clasificación positiva.

| Recibo/log privado | Resultado |
| --- | --- |
| `RED.log` | Inspector ausente antes de behavior. |
| `supervisor-RED.log` |22 pure/HTTP PASS; siete errores por supervisor ausente antes de implementarlo. |
| `GREEN-1.log` |29 PASS. |
| `final-unittest.log` |29 PASS/0skip,0.206s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` |PASS en tres fuentes, sin reducir checks. |
| `representative-no-env-stdout.json` /stderr |exit2 seguro, requests0, stderr vacío. |
| `source-binding-receipt.json` |Embedding/helper exactos, entregas anteriores intactas; AST host3.9 PASS, no host runtime sondeado. |

MockTransport/pure fixtures/fake Docker; sockets/DNS prohibidos, sin suite general.
Las pruebas no acreditan estado productivo, bindings o entrega real.

| Fuente privada | SHA256 final |
| --- | --- |
| `policy_inspection.py` | `f793c659248652a9a4f8c208313c8e9a8f0f890839f82f5e50b480abbf2f7276` |
| `policy_supervisor.py` | `c691407e97a919c49070a8333c2b5c8184b5a58586ee27f05b741d0fa0a86d37` |
| `test_policy_inspection.py` | `a7f11f476ae897f52aac0b8ed37019d3e9673bf5010557e0d5d3a04ec4b70b22` |

El hash del informe queda fuera en `delivery-receipt.json`. Solo root lleva ledger
y opera. El techo agregado propuesto25Management (uno usado+policy1+eventual23)
debe quedar explícito en su alcance/registro; no modifica el presupuestoMeli2500.
Esta entrega no ejecuta esa operación ni concede permisos.
**ENTREGADO; NO SIGO MODIFICANDO.**
