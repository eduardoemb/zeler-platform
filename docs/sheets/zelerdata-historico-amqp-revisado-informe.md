# ZelerData AMQP — estructura revisada, admisión NO acreditada

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local: **20 unittest PASS**,
cero skips; ruff, formato y mypy enfocados PASS en tres fuentes privadas.
No producción ejecutada por este especialista. La admisión del piloto sigue
explícitamente sin acreditar, aun si la inspección estructural pasa.

## Quick path del coordinador

1. Verificar alcance/ledger y cuatro hashes; conservar intentos previos.
2. Ejecutar un único round≤23GET en el worker/digest aprobado, mismo destino/auth.
3. Interpretar estructura y límites registrados por separado del riesgo operativo.
   No activar piloto, retirar HOLD o inferir ingreso seguro de un resultado GREEN.

[Política observada/revisión previa](zelerdata-historico-amqp-politica-informe.md),
[ledger](zelerdata-historico-paralelo.md),
[canon](../../infra/operations/zelerdata_amqp_delay_readonly.py).

## Cuatro paths exclusivos

Privado: `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-reviewed-reader-20261005`.
Directorio0700, fuentes0600; logs/recibos/cache propios confinados ahí.

| Path | Contenido |
| --- | --- |
| `<privado>/reviewed_reader.py` | Round23 estructural con excepción exacta revisada y evidencia real separada. |
| `<privado>/reviewed_supervisor.py` | Hash/digest/one-exec y recibo cerrado, rechaza admisión positiva. |
| `<privado>/test_reviewed_reader.py` | Doce pruebas reader y ocho supervisorfake;20≤35. |
| `docs/sheets/zelerdata-historico-amqp-revisado-informe.md` | Este informe propio. |

Los cuatro deliveries anteriores y sus informes conservan todos sus hashes.
Helper normalizado SHA `4d391872cc8c32eb021590b266e713de155502f7ae839b2f49451aa28d6b941c`;
canon SHA `66e9959a34a6d01bd1140dd1631e7fe9d8d653690f71e630dfc1a0e05d63befb`.
Sin runtime/core/CUOTAS/docs centrales/deps/lockfiles/Git/build/puertos/Mongo,
Docker real, producción, nuevas observaciones o subagentes.

## Excepción exacta, no policy ignorada

Solo permite para revisión **estos tres keys y valores**, enteros reales, no bool:

```json
{"expires":2419200000,"max-length":10000,"max-length-bytes":1073741824}
```

La forma de policy/operator debe ser string/null. Cualquier regla adicional,
valor diferente o forma inválida produce STOP. Metadata sin policy y definición
vacía sigue el canon original: no se suprime indiscriminadamente su guard.

Después de validar el tuple, `_queue` canónico recibe **copia local proyectada**
para verificar argumentos/TTL/DLX/identidad/counts. Metadata original y servidor
no se modifican. Se registra por cola la policy real en `reviewed_queues`:

- `policy_present`, `operator_policy_present`, `policy_review_exception_applied`:
  booleanos reales; no nombres ni simulación de ausencia en la evidencia.
- `effective_caps`: tuple real revisado, o `{}` cuando sigue el caso vacío del canon.
- `message_bytes_ready`: entero no negativo/null; bool, negativo u otra forma STOP.
- `idle_since_available`: presencia; `idle_age_seconds`: edad solo para fecha
  inequívoca con timezone, pasada/no futura; ausente/naive/ambigua/inválida→null.
- `idle_lease_expiry_verified=false`: **la edad no prueba expiración restante**.

No se emite timestamp original, host/vhost/URL, policy/operatornames, credenciales,
headers/body, hashes/longitudes de secretos o traceback. Solo se hashean fuentes.

TTL/DLX/bindings/exchanges pueden quedar estructuralmente verificados. Siempre:

```json
{"ingress_bound_verified":false,"no_loss_window_verified":false,"pilot_admission_safe":false}
```

El supervisor rechaza si cualquiera aparece true. No se infiere futura entrada,
ráfaga, capacidad durante una interrupción o ausencia de pérdida de una captura.
Publicación confirmada y timing real del canon también permanecen false.

## Operación y STOP

Mismo worker aprobado `sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e`.
Una selección/validación/digest y un exec, sin env forwarding. Diez colas metadata+
bindings y tres exchanges, GET secuenciales≤23,4s/request,60s lectura,64KiB/body,
cleanup5s. Hardalarm80 del Python transitorio, exec95, remoto150; caller root130+
grupo5 y total≤300s. Primer error STOP, sin retry/fallback ni mensaje de control.

Conserva cliente BasicAuth, normalización userinfo ya verificada, TLS/redirect/no-retry,
sanitización/filtros y demás gates canónicos. Default sin `--inspect` no consulta
env/transporte. No declara/publishes AMQP, Meli, policy/server/configwrites, scopes
nuevos o lectura fuera de ese round. Root conserva ledger y presupuesto agregado
**dos Management previos+23=25**; no cambia el techoMeli2500 ni plazos/checkpoints.

## RED/GREEN y hashes

| Evidencia privada | Resultado |
| --- | --- |
| `RED.log` / `RED-receipt.json` | Reader ausente, antes de behavior. |
| `supervisor-RED.log` | Reader12 PASS; ocho errores por supervisor ausente antes de implementarlo. |
| `GREEN-1.log` | Un fallo de fixture: FakeDocker alteraba codeNone de éxitos; validator runtime pasaba. |
| `GREEN-2.log` |20 PASS tras corregir únicamente el default del fake. |
| `final-unittest.log` |20 PASS/0skip,0.247s. |
| `final-ruff.log`, `final-format.log`, `final-mypy.log` |PASS, tres fuentes, sin reducir checks. |
| `representative-no-env-stdout.json` /stderr |exit2, requests0, JSON seguro/admisión false, stderr vacío. |
| `source-binding-receipt.json` |Embedding/helper exactos,16 hashes previos intactos; AST host3.9 PASS, no host runtime sondeado. |

MockTransport/fake Docker; sockets/DNS prohibidos, sin suite general. Tests cubren
tuple exacto/admisión nunca true, cambio/bool/unknown/shapes STOP1, TTL y binding
canónicos, bytes/edad nullable, HTTP404, logs/default, receipts positivos/negativos.

| Fuente privada | SHA256 final |
| --- | --- |
| `reviewed_reader.py` | `816e2c4511bf6fff38a41b93d0092463337ddebd7ef1094824e74df085041202` |
| `reviewed_supervisor.py` | `460cb46d78f64f7d6d851eb122f972cd8fb30eb1b96a9953f84ad01c5553dcf5` |
| `test_reviewed_reader.py` | `d472479e96a532286aa02f83dd47a5d20e8bcb16f58d733803a86ce8fa9794d2` |

Hash del informe fuera en `delivery-receipt.json`. Solo el coordinador decide
rollout con bounds faltantes y opera; esta entrega no acredita admisión segura,
despliegue, datos sin pérdida, piloto o cumplimiento de aceptación.
**ENTREGADO; NO SIGO MODIFICANDO.**
