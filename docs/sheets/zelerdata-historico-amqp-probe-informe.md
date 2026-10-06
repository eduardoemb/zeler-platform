# ZelerData AMQP — probe temporal aislado preparado

**ENTREGADO; NO SIGO MODIFICANDO.**24 unittest fake PASS/0skip; ruff,
formato y mypy de tres fuentes PASS. No operación productiva del especialista.
El broker todavía no se ha probado con esta herramienta; Root único operador.

## Quick path de Root

1. Confirmar scope en [ledger](zelerdata-historico-paralelo.md)1018–1046,
   snapshot fresco23/identidadold79f y hashes. No repetir cleanup fallido anterior.
2. Ejecutar una sola CLI `--probe-isolated-delay`, únicamente después de gates.
3. Interpretar broker_probe_passed, retirada de recursos y cleanup por separado;
   STOP ante fallo/timeout/inconsistencia. No retry, reparación adicional ni negocio.

[Propuesta aceptada](zelerdata-historico-amqp-runtime-gates-informe.md)§4 permanece
congelada SHA4110eda2…, y esta entrega no activa piloto ni comprueba worker352WAIT.

## Cuatro paths y preservación

Directorio privado0700:
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-isolated-delay-probe-20261006`.
Fuentes0600; nuevos logs/recibos con creación exclusiva/O_EXCL solo en ese directorio.

| Path | Contenido |
| --- | --- |
| `<privado>/probe.py` |Una operación propia, transportes/guards/deadlines y receipt cerrado. |
| `<privado>/probe_supervisor.py` |Host stdlib3.9, fuente/digest, un exec, recibo cerrado. |
| `<privado>/test_probe.py` |15 casos probe y9 supervisor:24≤24; solo fakes/MockTransport. |
| `docs/sheets/zelerdata-historico-amqp-probe-informe.md` |Este informe, único cambio repo. |

32 hashes de ocho deliveries previos, informe runtime4110 y antiguo ROOT/GREEN385a
verificados intactos. Ningún helper/código servido/central/CUOTAS/config/deps/lock,
Git/build/agente o dato anterior editado. Sin sockets/DNS/Docker/Mongo productivos.

## Método cerrado y ownership

Default sin CLI no lee env ni transportes. Solo `--probe-isolated-delay` ejecuta.
Configuración runtime existente RABBITMQ_URL/RABBITMQ_MANAGEMENT_URL; normalización
userinfo en memoria por helper congelado SHA8b34b81a… y guards reviewed/canon.
No forwarding de variables, fallback de auth/destino, TLSdisable, redirects o retries.

- Una conexión aiormq **no robusta**, stream retenido antes del handshake por factory
  congelada. Un canal `publisher_confirms=true,on_return_raises=true`.
- Dos Queue.Declare `queue=""` server-named, `passive=false,durable=false,
  exclusive=true,auto_delete=true,nowait=false`. Nombres retornados solo memoria;
  exige DeclareOk/counts0 y nombre server-generated `amq.gen-*` distinto del anterior.
  Nombre inseguro/duplicado→STOP, nunca se usa nombre proporcionado por operador.
- Destination argumentos exactos `{x-expires:60000}`.
- Delay `{x-expires:60000,x-message-ttl:30000,x-dead-letter-exchange:"",
  x-dead-letter-routing-key:<destination propio>}`. Sin declarar exchanges o binds.
- Antes de publicar, **dos GETmetadata** sameconfiguredManagement/auth, solo las
  colas propias,≤64KiB/cuerpo e identidad/vhost/typeclassic/counts0/exclusive/
  autoDelete/noDurable/argumentos exactos. Solo extra broker `x-queue-type=classic`
  admitido; no otros argumentos. No imprimen nombres/vhost/argumentos routing.
- Effectivepolicy solo empty o tuple de tres ints EXACTOS
  `{expires:2419200000,max-length:10000,max-length-bytes:1073741824}`.
  Flags policy/operator **reales** retenidos; nombres y valores secretos no se emiten.
  Empty efectivo conserva presencia real de nombres si existe; no ausencia ficticia.
  Regla/routing/TTL/shape desconocido impide publicar; no cambiar policy.

## Publicación, expiración, recepción y ACK

Un nonce aleatorio propio32B(≤64), no JSON/businessevent/seller/job/history.
Un basic.publish **solo defaultExchange/routingdelay propio**, mandatoryTrue,
immediateFalse, confirma Basic.Ack tipado deliverytag1; return_raises o Nack/None/
resultado distinto→STOP antes de gets. No publish a colas/exchanges business.
`aio_pika.Message(expiration=timedelta(milliseconds=5000))` y propiedades wire
exactamente"5000" se comprueban antes de enviar; cuerpo/nonce/header nunca salen.

Timing monotónico, t0 antes de publish:

1. Get1 soloDestination/no_ackFalse en t0+4s, deadline0.5s. Debe ser GetEmpty/body vacío
   y completar en [4,5)s; respuesta temprana/clock tardío→STOP.
2. Get2 soloDestination en t0+8s, deadline2s. GetEmpty→STOP, **sin pollloop**.
   Debe ser GetOk con nonce exacto, defaultExchange/routingDestination, deliverytag
   válido; único x-death propio queueDelay/reasonexpired/count1/original-expiration5000.
   Wrongnonce/death/expiry→STOP sin ACK. Ventana de recepción observada [8,10]s.
3. **Un ACK propio** multipleFalse/waitTrue después de validación; es ACK local
   drenado, no confirmación remota del procesamiento. Get3≤2s vacío después del ACK.
   Solo al completar esta secuencia `broker_probe_passed=true`.

No consumo registrado/basic.consume, NACK, republish, replay ni mensajes a negocio;
Meli/Mongo/businesspublish0 por esta operación. No prueba los hooks handler/WAIT.
No reclamar precisión matemática5s ni durabilidad/HA,14scopes/aceptación o90min.

## Retirada y cleanup HONESTOS

≤2Queue.Delete **solo nombres retornados y validados propios**, ordenDelay→Destination,
if_emptyTrue/if_unusedTrue/nowaitFalse; no purge/drain. DeleteOk/count0 requerido.
Primer deleteerror detiene deletes restantes, conserva estado delete_unknown,
pero aún solicita cleanup del transporte propio. No tocar una cola foreign.

Todas las retiradas y HTTPclose/TCPclose/waiter comparten **un deadline5s**.
No empieza una operación async después de agotarlo; coroutine no iniciada se cierra
sin ejecutar y se conserva timeout. Siempre solicita cierre directo del writer
propio aunque connection.close falle/no pueda iniciarse. Waiter retenido antes de
close, shielded, cancelado/recuperado si queda pendiente; errores no se silencian.
Exclusive/x-expires son fallback, no certificado de retirada server-side inmediata.

Outputs separados:

| Campo | Interpretación |
| --- | --- |
| broker_probe_passed |Secuencia propia publish/get/death/ACKlocal observada completa. |
| resource_deletion_confirmed |Dos recursos propios conocidos con DeleteOk/count0; no la mera salida del proceso. |
| local_close_requested / waiter_state |Solicitud local y `none/completed/error/cancelled/timeout`, no prueba remota. |
| cleanup_error_family |Primer error total de retirada/cierre por familia, o null. |
| tcp_cleanup_error_family / http_cleanup_error_family |Errores de cada transporte por tipo, conservados aparte. |
| remote_close_confirmed |SiempreFalse; no convertir SSLshutdown/reset/cancelación en clean. |

Familias cerradas: `ssl_error|reset|cancelled|timeout|other|null`, clasificadas
**solo por tipo de excepción**, no strings/reasons/brokertexts. Puede haber
brokerpassedTrue/resourceDeletedTrue y STOP por cleanupSSL; tres planos distintos.
No se ha operado para diagnosticar o arreglar el cleanup histórico.

## Presupuestos, recibo y STOP

Work≤60s:connect8/canal4/declare4cada uno/Management4cada GET/publishconfirm4/
get0.5,2,2/ACKlocal2; cleanupTOTAL5/hard80/exec95/remoto150/root130+grupo5/total≤300s.
Un intento, sin autoreconnect/retries/faultinjection. STOPprimererror o resultado
inesperado; únicamente cleanup propio autorizado después. Source/digest antes del
único exec:old79f inmutable, misma aprobación y Pythonworker3.11.
Supervisor host AST3.9 probado; versión real host no sondeada.

Límite conocido Management:27 previos +fresh23≤50 +solo2 propios≤52;
Root registra consumo real, no reinicia GETdesconocidos del primer intento viejo,
presupuestos/plazos/checkpoints/Meli/piloto. Full sigue excluido/registro14 intacto.

Receipt valida sets/keys/enums/flags/counters0..límites y progreso semántico;
unknown counters=null/no0 inventado, ownership lastknown por labels lógicos.
Metadata/sucesos se sanitizan a flags/caps públicos/elapsed finitos. No URLs/hosts/
vhost/user/pass/envvalues/secretlongitudes/hashes, nombres temporales, nonce/body,
headersraw/exceptionstr/traceback/stderr libre. Solo hashes de **fuentes**.
`deployed_worker_path_verified,durability_verified,ingress_bound_verified,
no_loss_window_verified,pilot_admission_safe` siempreFalse; supervisor rechazaTrue.

## TDD y evidencia preservada

| Evidencia | Resultado |
| --- | --- |
| RED.log |Import probe ausente antes de behavior. |
| supervisor-RED.log |15PASS+6errores por supausente; antes de behavior supervisor. |
| supervisor-RED-2.log |15PASS+9errores por supausente,24casos cerrados. |
| GREEN-1.log |24PASS inicial. |
| cleanup-deadline-RED.log |1FAIL/24: closeasync empezaba después del deadline por floor0.001s. |
| ruff-first/fix/formatted, mypy-first, format2/ruff2/mypy2 |Errores originales/layout/tipos y una edición de fixture inválida preservados; no skips ni reducción de gates. |
| final-unittest.log |24PASS/0skip,0.441s tras fixdeadline y embedding actualizado. |
| final-ruff/final-format/final-mypy |PASS tres fuentes, configuración estándar. |
| representative-no-env-stdout.json/stderr.log |CLIstdin sinenv:exit2/counters0/safeJSON/stderr vacío; no transporte iniciado. |
| source-binding-receipt.json |Embedding exacto, ASTsup3.9,32 hashes previos+auditoría/log anteriores intactos. |

Pruebas: vectores/counts, ownership/nombres, policy/TTL/exclusive/404antespublish,
return/Nack, wrongnonce/death/wire, early/late/empty sinpoll, partialhandshake,
SSL/reset/cancel/deletionfailure yshareddeadline,logs/default/noenv/hash/receipt
positivo yfallido/NaN/admisión/timeout/unknowncounts. Fakes/callbacks/MockTransport;
no tests generales ni puertos/sockets/Docker reales/Mongo/producción.

## Hashes finales y cese

- `probe.py`: `d49d678d99d397fea18a5fb52b3d6507a87cb86239dfa9be289fed6bc22e9413`
- `probe_supervisor.py`: `c0618d20157a10557ed1ed0971f68618635ae924daf6cf46552bb325567e6a9c`
- `test_probe.py`: `33a034f68bdc913c0e83333ed034909da19d400a416a0e0c5dd545d04b659aec`

El hash de este informe y los cuatro paths están en `<privado>/delivery-receipt.json`.
Ninguna claim de producción/handler352/negocio/acceptance se deriva de GREEN.
Propiedad devuelta a Root; **ENTREGADO; NO SIGO MODIFICANDO**.
