# ZelerData AMQP — variante de policy temporal exacta preparada

**ENTREGADO; NO SIGO MODIFICANDO.**14fakesPASS/0skip,1.129s;ruff/formato/mypy3PASS.
Preparación local únicamente;Root único operador/Git/build. No probe productivo por AMQP.
[Propuesta aceptada](zelerdata-historico-amqp-probe-policy-propuesta.md)SHA cc6dfe5f e [ledger](zelerdata-historico-paralelo.md)definen una NUEVA operación corregida, no rerun ciego.

## Variante mínima y CLI exacta

**CLI documental exacta: `--probe-isolated-delay`.** Fuente/SHA nueva identifica la
variante;flag ausente/errónea→NOOP,no env/transporte. No inventar otra flag al operar.
SourceSHA-boundsettled2a17/base d49,espera6s ya incluida. Solo cambia:

1. CAPS global del validador a `{expires:60000,max-length:1000,message-ttl:60000,max-length-bytes:1073741824}`.
2. Dos predicatesmetadata:policy/operator deben serstrings no vacíos;dict efectivo
   debe tener SOLO esas4keys/ints/valores exactos. NO `{}`/business28d/fallback.
3. Recibo/supervisor admite únicamente esos caps yflags realesTrue;hashbindings nuevos.

Identity/vhost/type/exclusive/autoDelete/noDurable,argumentosTTL/DLXprivado,
zeroCounts ytodoel publisher/get/ACK/clock/nonce/cleanup quedan congelados.
No reescribir metadata:el test compara input antes/después;effective_caps devuelto
es copia de los valores **reales** después de validarlos, no proyección inventada.
Sourcebinding compara bytecode/constants de todas las funciones salvo_metadata:
ninguna cambia. Root profile sigue siendo hipótesis hasta ambasmetadata reales.

## Scope y STOP conservados

1ownedconnno robusta/1confirmchannel;2server-namedexclusiveautoDelete/noDurable,
xExpires60000,delayTTL30000/DLXdefault/routingDestinationpropio;settle6→2GETmetadata
propios exactos antesANYpublish;0pub ante mismatch/extra/missing/bool/flags/counts.
1noncealeatorio≤64B mandatory/noReturn/Nack/wireexpiry5000 via timedelta;3get ownDst
máximo(early4/deadline0.5completa<5/empty,late8/deadline2≤10/nonce+xdeathownexpired1
original-exp5000,ACKlocal1 entoncesget3≤2vacío);≤2ownconditionaldelete ifempty/unused.
Work60incluye6/cleanupTOTAL5/hard80/exec95/remoto150/root130+grupo5/total300;
STOPprimererror,cleanupownonly,noretry/fallback/poll. Known53+≤2=55,no resetoldunknown.

Brokerpassed/resourceDeletion yTCPssl_error/waiter se informan separados;
remotecloseFalse siempre. PrimerprobeFAIL0pub/2ownDelete/SSLerror permanece.
Worker352path/durability/ingress/noLoss/pilotadmissionFalse siempre;ningún resultado
local implica policyactualvalidada/publish/timingreal/globalaceptación.
Sin policiesglobales/business/env/config/IAM/otherresources/MeliMongo/Full/writes.

## Cuatro paths y evidencia

Privado0700 `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-isolated-delay-probe-temporary-policy-20261006`;
fuentes0600 ylogs/recibos nuevosO_EXCL SOLODIR.

- `<privado>/probe_temporary_policy.py` — wrapper minimal.
- `<privado>/probe_supervisor.py` — closedreceipt/source/digestold79f/unexec.
- `<privado>/test_probe_temporary_policy.py` —10reader +4sup:14≤16.
- `docs/sheets/zelerdata-historico-amqp-probe-policy-informe.md` — este informe.

RED-profile-original.log:3FAIL+5ERROR/14,original no acepta candidato yvariante/sup
faltan. GREEN-1 yfinal-unittest14PASS;ruff-first/fix/formatted preservan errores
layout/closurebinding de fixture antes de corrección, sin reducirchecks/skips.
Regresiones:foreign/ownership/TTL/DLX/flags/counts0/unknown/bool/caps exactos,
confirm/return/nack/nonce/timing/cleanupSSL/redacción;baseline business/empty rechazados.
Default/wrongflagNOOP ystdinCLI sinenvexit2/counters0/JSONsafe/stderr vacío.
SupAST3.9/embedding y**48previousdeliverySHA**+audit4110/proposalcc6d/ROOTGREEN385a/
failedreceipt0fcc verificados intactos. No tests anteriores rerun/no suitesgenerales.
Fakes/MockTransport,0sockets/DNS/puertos/Docker/Mongo/productivo;no nuevos agentes,
shared/CUOTAS/core/config/deps/lock/Git/build/sourceoldedits o research.

## Hashes finales y cese

- `probe_temporary_policy.py`: `1a96fb2c166890717d075e7de49308d118f9be9aeb360364a3378961d661cd30`
- `probe_supervisor.py`: `c7685818c7c6662050f54c07755799ffa859fc883fde8f9f292b3a64b7e9a485`
- `test_probe_temporary_policy.py`: `ab50d15d677fd8ec1c7f370e4bfc40abf774575d20242e5181b31dce5b0d4512`

Cuatro hashes(incluido informe) en `<privado>/delivery-receipt.json`. Root recibe propiedad/valida/decideONE nuevo intento;**ENTREGADO; NO SIGO MODIFICANDO**.
