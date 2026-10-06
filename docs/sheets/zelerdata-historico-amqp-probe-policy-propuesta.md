# ZelerData AMQP — propuesta de un perfil temporal exacto, no policyglobal

**ENTREGADO; NO SIGO MODIFICANDO.** Propongo una **variante nueva y estricta**
para un único intento corregido, sujeto a revisión/asignación/TDD de Root.
**No implementada ni ejecutada.** No cambiar policies, colas business o guards
anteriores; conservar el primer probe fallido. Único archivo escritor:este documento.

## Evidencia privada verificada

| Recibo relativo al cacheROOT | Evidencia segura / SHA256 |
| --- | --- |
| `amqp-isolated-delay-probe-settled-20261006/AMQP-ISOLATED-DELAY-PROBE-1-end.json` |policy_invalid antes de publish;1GET completo,0pub/get/ACK;2ownDeleteconfirmados,resourceDeletionTrue,TCPssl_error/remoteFalse. SHA`0fcc63b5390e4ca38473e9e6c4b1335ded843b9adbae5e2fc82afb0a4bd8a705`. |
| `amqp-policy-definitions-20261006/AMQP-POLICY-DEFINITIONS-1-end.json` |4reglas normales enlista,solo2resumidas;row2queuesprio−9 `{expires:60000,max-length:1000,message-ttl:60000}`;unknown0/regexunsupported/matchnull. SHA`15d76e125be3f97c9c36ad30dff7424eba53e37d6b7a0cfe77cd3bd7167b5995`. |
| `amqp-operator-policy-read-20261006/AMQP-OPERATOR-READ-2-end.json` |1rulequeuesprio0 `{max-length:10000,max-length-bytes:1073741824}`;unknown0/regexnoevaluado/matchnull. SHA`f96bd7590e2b2b5ae552166ae47f5df65e3aba1bd717b3ac42ef2faae93421f6`. |

Los53GETManagement conocidos y losconsumos viejos/desconocidos permanecen.
No nombres/patrones/QName antiguos recuperados; el body fallido no se conservó.
**Estos recibos NO prueban el perfil efectivo de las dos próximas colas.**
Tampoco completan las dos reglas normales no resumidas. No repetir esos listados
ni inferir match real del ejemplo sintético/de una regex no evaluada.
[Ledger único](zelerdata-historico-paralelo.md), resultados de operatorread y encargo.

## 1. Único perfil candidato aprobado por metadata, no por inferencia

Para **cada una** de las nuevas colas propias, exigir exactamente:

```json
{"expires":60000,"max-length":1000,"message-ttl":60000,"max-length-bytes":1073741824}
```

Es una **hipótesis operacional revisada**, no un estado remoto ya confirmado.
Solo int reales(no bool), las cuatro keys/valores exactos;sin desconocidos ni
reglas extra(DLX/routing/overflow/deliverylimit/etc.). No aceptar `{}`, el perfil
business28d/max10000 o una serie de alternativas para “hacerlo pasar”.

Antes de publicar, dos metadataGET reales de nombres **server-returned propios**:

- Nombre/vhostidentidad exactos enmemoria,typeclassic,durableFalse/exclusiveTrue/
  autoDeleteTrue;policy/operatorpresentes como strings no vacíos,flagsreales retenidos,
  sin publicar nombres. No afirmar presencia desde los listados anteriores.
- Destination argumentos **exactamente** x-expires60000;Delay x-expires60000,
  x-message-ttl30000,DLXdefaultvacío y routingDestinationpropio. Solo extra
  broker x-queue-typeclassic ya permitido;otros argumentos→STOP.
- Counts ready/unacked/consumers int0; perfilesefectivos exactos de ambascolas.
  Unknown/typeinvalid/missing/stale/mismatch→STOP **antes de publish**.
- Espera fija6s después deambasDeclareOk antes de los dos GET,sin poll/retry.
  No garantiza frescura ni permite convertir ausencia en0.

Validar el dict `effective_policy_definition` por separado de `arguments`:
el primero registra reglas de policy;los segundos y la precedencia determinan
la retención efectiva del mensaje. No reescribir/proyectar metadata real ni
ocultar que las policies están presentes. Nueva variante cambia **solo el perfil
admisible temporal y su validación/recibo cerrado**;no el guard de colas business.

## 2. Precedencia y por qué la inferencia es condicional

La policy normal con mayor prioridad **entre las que realmente coinciden** gana;
no se combinan todas por orden de lista.−9 vence a−10 si ambas coinciden,pero
no sabemos los matches de QName ni las otras dos reglas. Empates son ambiguos.
Las priorities de normal y operator no forman una sola competición:operator
limita/combina valores;para límites numéricos se usa el más conservador.
Así, **si** se aplican las reglas observadas, max-length=min(1000,10000)=1000 y
max-length-bytes se incorpora como1GiB. [RabbitMQ policies](https://www.rabbitmq.com/docs/policies).

En classic, argumentos del cliente prevalecen sobre la policy normal;operator
puede restringirlos. Aquí no se declara max-length para escapar del límite.
Delay mantiene x-message-ttl30000 aunque la definición normal anuncie60000;
x-expires60000 coincide con el candidato. [RabbitMQ queues](https://www.rabbitmq.com/docs/queues#optional-arguments).

Per-messagewireexpiry5000 usa el menor TTL con queueTTL30000,por lo que el objetivo
es observar expiración de5s,no25s/35s. Destination tiene retención de policy60s;
tras DLX la expiración original se elimina y queda en x-deathoriginal-expiration.
`expires60000` es inactividad decola,no retención/lease exacta deducible de un reloj.
Recepción prevista8–10s es menor a60s;con una sola copia≤64B ycounts0 no se acerca
acap1000/1GiB. Es justificación **de la muestra controlada**,no no-lossglobal.
[RabbitMQ TTL](https://www.rabbitmq.com/docs/ttl),[RabbitMQ DLX](https://www.rabbitmq.com/docs/dlx).

La metadata exacta de ambascolas manda si la combinación real difiere de este
razonamiento;STOP,sin segunda consulta para buscar otra configuración aceptable.
No cambiar policiesglobales,añadirmaxlen enargumentos,ni usar nombresestáticos
para forzar un patrón o escapar de límites. No consultar colas ajenas.

## 3. Scope de un intento corregido NUEVO

Root debe registrar el perfil/procedimiento/artefactosTDD antes de asignar/callar.
No ejecutar el helper anterior otra vez ni alterar su evidencia;variante fuente/
SHA/supervisor nuevos,demostrarREDperfilnuevo rechazaoriginal/GREENsoloexactprofile,
regresión de ownership/TTL/DLX/counts/confirm/timing/redacción ytimeouts.
Después entrega/cese/verificaciónRoot;**una operación**,ningún retry/fallback.

| Operación | Límite inalterado |
| --- | --- |
| Transportes |1ownedconn no robusta/1channelconfirmsTrue+onReturnRaisesTrue,mismo broker/auth/runtimeold79f aprobado,unexec ynoenvforward. |
| Recursos |2server-named exclusivas/autoDelete/noDurable propias,args§1;0exchangecreate/bind/businessops. |
| Management |2metadataGET propios antes de publish,4s cada uno/64KiB;53previos +≤2=≤55. No nuevaslecturas/policies/foreignqueues. |
| Publish |1noncealeatorio≤64B,noJSONnegocio/seller/job/history;defaultExchange→Delaypropio,mandatoryTrue,wire"5000" via timedelta,ACKtipado/noReturn/Nack. |
| Get/ACK |3getsoloDestination:no_ackFalse,earlyt0+4/0.5completo<5 yvacío;late+8/2 recibido≤10s,nonceexacto/x-deathpropioexpiredcount1/original-expiration5000;1ACKlocal soloentonces,get3≤2vacío. |
| Retirada |≤2deleteOWNif_emptyTrue/if_unusedTrue/nowaitFalse;primererror detiene deletes,sinpurge/drain/foreignchanges. |
| Deadline |Work60(incluye settle6),cleanupTOTAL5,hard80/exec95/remoto150/root130+grupo5/total≤300s. |

STOPprimererror/timeout/inconsistencia/unknown oinvalidprofile,nonceextraño,
publicación sinconfirm/return/nack/clock/cleanup. Solo cleanup propio delimitado
trasSTOP;no publish de negocio,faultinjection,AMQPconsumers,Meli/Mongo,config/IAM/
policywrite,GCPrecursos,OAuth oactivaciónpiloto. Full0/registro14/datos/jobs/plazos
counters/cutoff/checkpoints/consumos intactos. Ninguna ampliación automática a2500GET.

Recibo separa perfiltemporalmetadata verificado,brokerProbePassed,
resourceDeletionConfirmed yTCPcleanupfamilies. Preservar SSLerror/waitererror del
primerprobe;no probarproducción para mejorarclose. Unknownprogress=null,
localCloseRequested noescierre remoto;remotecloseFalse. Nombres/nonce/body/
headers/URLs/vhost/secretvalues nunca impresos ni hasheados.

## 4. Alcance de la aceptación y siguiente paso

Si pasa,acredita una muestra **en esta pareja temporal**: perfil real previo,
publishconfirmado/expiryDLX observados/recepciónnonce/ACKlocal/retirada segúnrecibo.
No durabilidad/HA/failover,no-loss90min,estado de colasbusiness,WAIT/backoff/CAS/ACKNACK
real deworker352,OAuth/Meli/Mongo/Sheets ni dosincrementales auténticos.
Ingresobound/noLoss/pilotadmission/deployedWorkerPath/durability permanecenFalse.

Recomiendo aRoot revisar este perfil condicional ydelimitar los cuatro paths de
una nueva varianteTDD;la implementación/publicación yoperación aún NOocurren.
Si metadata no coincide,no auto-repair/otroprobe:reportar ese gate concreto.
Sinedicionesprevias/shared/cfg/deps/lock,GIT/builds/testsuite/productivo/agentes.
**ENTREGADO; NO SIGO MODIFICANDO.** Propiedad de este único archivo devuelta.
