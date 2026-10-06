# CUOTAS: regresiones de admisión legacy y seed prospectivo

**ENTREGADO; NO SIGO MODIFICANDO. GREEN26 local, no producción.**
Tres writers exactos de CUOTAS:

1. `core/tests/test_history_onboarding_admission.py`.
2. `gateway/tests/test_history_admission_pilot_seed.py`.
3. Este informe.

Root implementa `core/.../history_onboarding.py` y `gateway/.../oauth/events.py`,
compatibilidad del fake BSON anterior y documentos centrales. No source behavior,
config/deps/lock/Git/build/producción/agentes/Mongo/AMQP ni suite general por CUOTAS.
Propuesta95c399ad y herramientas/informes previos permanecen intactos.

## RED reproducible antes del comportamiento

Privado:
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/legacy-admission-red-20261006/`.
`red-unit.log/xml`, O_EXCL y log0600: **19 FAIL / 4 PASS, 23 casos**, 0.51s.
Comando de pytest con pyproject estándar, plugin asyncio explícito, noconftest
para no heredar recursos reales; cache propia/no-sync/offline. Solo estos dos
targets, ambiente whitelisted sin MONGO_URI/secrets y sockets connect/connect_ex
bloqueados. Sin fallback, puerto, URI de pruebas o recursos compartidos.

Fallos observados y entregados a Root antes de escribir comportamiento:

- `pilot_seed` todavía no existe; Gateway no pasa True para scope seleccionado.
- Legacy budget parcial/consumed17+9/total26 y estado/cursor/daily existentes
  sobrescritos cuando falta policy_version.
- null/bool/negativo/budget corrupto aceptados como nuevos datos en vez de WAIT.
- Lease live/token sin expiry/null/legacy envelope no impide otorgar authority.
- CAS ausente permite perder counter drift/field añadido entre read y update.
- Dos links concurrentes pierden consumo; last_linked_at retrocede.
- Ledger sin identidad de ejecución conocida recibe authority nueva.
- Ruta real OAuth no deja nuevo piloto pausado/five-source/noexec.

Cuatro controles PASS: fake BSON/dotted/snapshot CAS/$max/matched_count; scopes
no seleccionado/default; admission hold conserva bootstrap protegido.
Tests Gateway verifican trece jobs (doce failed y uno succeeded), sin replacement,
publish ni force; existing selector funcional permanece sin cambios por CUOTAS.

## Contrato fijado

`admit_history_onboarding(..., pilot_seed=False)`: True solo por membership en
Settings trusted existente, jamás env logic en Core ni request/header/path.
Missing canónico genuino puede iniciar0 como **contador prospectivo nuevo** con
authority pausada: no demuestra consumo histórico0 ni saldo libre2500.
Source caps800/150/250/300/500, total2000 y daily500/300, cinco sources; slot
Full0 solo para forma interna compatible, sin seleccionarlo/GET/cuota nueva.
Si consumo Full previo existe, se preserva sin refund ni selección.

Cutoff Sep24 BSON/milisegundos, bounds calendar derivados, progress/checkpoints,
todos los counters/limits/day/plazos/identity/leases/metadata ajena conservados.
No seed execution_id/day/until/attempt_limit, no reiniciar ventana ni reenviar
callbacks para evitar OAuth. Malformed/unknown ledger/lease → ValueError WAIT.
Whole-document CAS y readback idempotente; relink de policy solo last_linked_at
monotónico, sin activar paused/reset. Jobs.attempts/progress no es ledger GET.

## RED3 adicional y GREEN final

Root ejecutó independientemente el primer GREEN23, sus tres casos Mongo reales y
29 adyacentes tras compatibilidad:52PASS, informado por Root, no por este writer.
Antes de freeze detectó tres edges del mismo contrato y encargó solo sus REDs:

| `red-safety3.log/xml`, antes del siguiente patch Root | Resultado observado |
| --- | --- |
| piloto + legacy state=active | No WAIT; no debe sobrescribir active ni otorgar authority activa |
| CAS winner solo policy_version, sin authority/sources | Falso éxito idempotente |
| missing cap orders con consumed801/default800 | Otorga budget inválido en vez de WAIT |

**3 FAIL / 18 deselected**, 0.15s; todos DID NOT RAISE ValueError. Solo tres nuevos
casos en Core, sin archivo/source/alcance adicional ni ejecución de los anteriores.
Los23 iniciales, logs/receipt RED y sus hashes previos siguen preservados.

Root corrigió esos edges y congeló Core/Gateway antes del turno final. Informó
independientemente55PASS (26+29 adyacentes) y tres CAS reales PASS; no son pruebas
ejecutadas por CUOTAS. Root detectó cuatro errores mypy en nuestro control fake
por `document|None`; se agregaron solo asserts explícitos de fixture no-None,
sin ignores ni nuevos casos/comportamiento de producto.

| Recibo final CUOTAS en privado propio | Resultado |
| --- | --- |
| green26.log/xml, bytes finales tras typing | **26 PASS / 0 skips**, 0.37s |
| delivery-ruff.log | PASS, los dos targets propios |
| delivery-format.log | PASS, dos archivos formateados |
| delivery-mypy.log | PASS estricto estándar, dos targets; no reducir checks |

Comando GREEN usa `--noconftest -o addopts='' --import-mode=importlib`, plugin
asyncio explícito, sockets bloqueados y entorno/cache privados como RED.
O_EXCL/0600, sin sobrescribir red-unit ni red-safety3/logs/receipts previos.
No edición ejecutable después de este GREEN/calidad. Informe/coherencia y hashes
en `green-delivery.json`. Root recibe cese para controlar freeze general, CAS real,
publicación/gates y nuevo encargo separado de lectura dirigida; no ejecutado aquí.

Solo Gateway rebuild si delta de admission/caller y helpers worker/API usados
sin cambio, conforme al mapa por símbolo confirmado por Root; no build ejecutado.

## Key Learnings:

1. Ausencia de policy_version no demuestra ausencia de counters ni permite refill.
2. El contador nuevo prospectivo no atribuye intentos antiguos ni abre una ventana.
3. Fakes deben comprobar BSON, dotted paths y matched_count, no aceptar cualquier CAS.
