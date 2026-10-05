# ZelerData AMQP — existencia pasiva exacta preparada, sin repair

**ENTREGADO; NO SIGO MODIFICANDO.** **16 unittest fakes PASS**, cero skips;
ruff, formato y mypy enfocados PASS en tres fuentes privadas.
No broker real, Docker real ni producción ejecutados por este especialista.
La eventual creación de un recurso no forma parte de esta herramienta ni queda
autorizada por la entrega: root verifica permiso/ledger por separado.

## Quick path del coordinador

1. Verificar autorización pasiva acotada, fuente y worker/digest aprobado.
2. Ejecutar una sola vez el checker. Nuevo recibo, sin sobrescribir evidencia.
3. Diferenciar `not_found` confirmado por el broker de HTTP404 anterior,
   `access_denied`, timeout o fallo de herramienta; no repair ni retries automáticos.

Referencias: [revisión estructural](zelerdata-historico-amqp-revisado-informe.md),
[ledger](zelerdata-historico-paralelo.md).

## Cuatro paths exclusivos

Privado: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-passive-check-20261005`.
Directorio0700, fuentes0600; logs/recibos/cache propios confinados ahí.

| Path | Contenido |
| --- | --- |
| `<privado>/passive_check.py` | Broker URL canónico, conexión no robusta y RPC pasivo exacto. |
| `<privado>/passive_supervisor.py` | Identidad/hash/digest/one-exec y output cerrado. |
| `<privado>/test_passive_check.py` | Diez casos checker/callbacks y seis supervisorfake,16≤20. |
| `docs/sheets/zelerdata-historico-amqp-existencia-informe.md` | Este informe propio. |

Los cinco deliveries anteriores y sus informes conservan todos sus hashes.
Sin core/runtime/CUOTAS/docs centrales/deps/lockfiles/Git/builds/Mongo/puertos,
otras colas o subagentes. Solo APIs instaladas locales fueron consultadas.

## Una conexión y un método pasivo

Único input: `RABBITMQ_URL` del proceso del worker, sin argumentos/forwarding,
envfile, nuevos credentials o broker alternativo. Validador puro extraído de
canon SHA `66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.
El argumento Management sintético sirve solo a validación pura; nunca se usa para
conectar ni leer HTTP. La URL real del broker no se transforma ni imprime.

Se construye **aiormq.Connection explícita**, no robusta, antes de conectar.
OwnedTransportFactory envuelve el factory TCP/TLS original instalado y retiene
el stream writer antes del primer handshake AMQP. Se abre un canal con
`publisher_confirms=false`, evitando Confirm.Select innecesario.

RPC único `Queue.Declare` para `zeler.sheets.claims.retry.1s`:
`passive=true,durable=true,exclusive=false,auto_delete=false,nowait=false,arguments=null`.
PassiveFalse está prohibido incluso en el helper y tests. No consumer/basic.get,
ACK/NACK, publish, bind, queue create/delete, declaración de exchanges, policy
write, Meli o Mongo. Handshake/Channel.Open/cierre son protocolo inevitable de
la conexión propia, **no otras operaciones sobre entidades**.

## Ownership, deadlines y output

Conexión≤8s; canal≤4s y RPC≤4s; cierre propio con deadline conjunto≤5s.
Se intenta cierre de conexión y se cierra directamente el writer retenido incluso
si connect/handshake/cleanup falló. Hardalarm55 termina solo el Python transitorio
del checker, nunca workerPID1, y cierra sus descriptores por proceso.
Exec65s, remoto120s; root caller130+grupo5 y total≤300s. Sin reconnect/retry.

Worker aprobado: `sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`.
Supervisor: selección/digest, un exec, captura/discard stderr; no env overrides.

Recibo cerrado:

- Counters conexiones/canales/passiveRPC iniciados y completados0..1 o null si
  el progreso es desconocido; completed del RPC incluye respuesta negativa403/404.
- Códigos `exists`, `not_found`, `access_denied`, `tool_error`, `timeout`;
  reply code403/404/null, nunca texto de la excepción. `not_found` solo tras RPC
  pasivo iniciado y excepción de entidad ausente mapeada por la librería.
- Flags del vector exacto, exists bool/null, ownership cerrado y error de cleanup.
- `mutations=0`, `management_http_requests=0`, `meli_requests=0` **de esta operación**.
  No se convierte el historial productivo previo en cero AMQP.

Se suprimen logs de dependencias durante operación/cleanup y stderr del CLI se
descarta en memoria, incluyendo diagnósticos tardíos. No URL/vhost/user/password,
reply text, headers/body, traceback o hash/longitud de secretos. Solo hashes de
fuentes. Una existencia positiva no certifica TTL/DLX/bindings, entrega ni admisión.

## RED/GREEN y relevo

| Evidencia privada | Resultado |
| --- | --- |
| `RED.log` / `RED-receipt.json` | Checker ausente, antes de behavior. |
| `supervisor-RED.log` /recibo | Checker10 PASS; seis errores por supervisor ausente antes de implementarlo. |
| `GREEN-1.log` |16 PASS. |
| `final-unittest.log` |16 PASS/0skip,0.173s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` |PASS en tres fuentes, sin reducir checks. |
| `representative-no-env-stdout.json` /stderr |exit2 seguro/connections0, stderr vacío. |
| `source-binding-receipt.json` |Embedding/canon exactos, veinte hashes anteriores intactos; AST host3.9 PASS, no host runtime sondeado. |

Fakes/callbacks solamente, sockets/DNS prohibidos. Casos: exists, broker404/403,
error/timeout antes del handshake con writer cerrado, cleanup failure, passiveFalse,
input inválido, logs, ownership capture, recibos inseguro/overscope, stdout sin env.
Sin suite general, nuevos builds o llamada productiva aquí.

| Fuente privada | SHA256 final |
| --- | --- |
| `passive_check.py` | `f66b207028b837dc629ad9bca4716ad17c1f08481fa4ee4f80546f9cbe2d6848` |
| `passive_supervisor.py` | `7cbbaf3052457f306f09ede414923b157db80a5ddbf06a8f07470031702497e4` |
| `test_passive_check.py` | `7d7a464d4d506a8085e42abb08f91b6556132f6c455e051a8dbb871cfad434ac` |

Hash del informe fuera en `delivery-receipt.json`. Root conserva autoridad, ledger
y decisiones de mutación. **ENTREGADO; NO SIGO MODIFICANDO.**
