# Piloto: parada conservadora ante 429 sin alterar producto ordinario

**ENTREGADO; NO SIGO MODIFICANDO.** El objetivo integral no está aceptado.
Sin producción, DB real, red, Git, builds, agentes, AMQP ni suite general.

## Alcance exclusivo

Dos fuentes existentes (`history_onboarding.py`, `devoluciones_runner.py`), helper
producto nuevo `history_pilot_stop.py`, dos tests nuevos y este informe. Core,
Gateway, collector RETURNS, modelos/schemas/config y tests anteriores intactos.

El helper recibe snapshots persistidos validados por los wrappers; no deriva
autoridad del path, headers del caller ni ambiente. EID capturado, seller,
policy/authority, eligibility y controles de ejecución deben concordar.

- Remote429 probado: status429 y `X-Zeler-Upstream-Attempts='1'`.
- Local0: WAIT local, no prueba remota.
- Metadata ausente/inválida: abortado conservador, no remote429 inventado.
- CAS sólo `{state:'paused'}` del EID/seller/controles capturados; ningún reset,
  refund, plazo, crédito, checkpoint ni fase relabelled. Un reemplazo de EID no
  permite pausar al nuevo. Un CAS perdido no demuestra pausa confirmada.
- RETURNS usa stop tipado derivado de `SourceCallBudgetError` para atravesar su
  rama abortada antes del throttle retry. El runner lo convierte a WAIT antes
  de etiquetar presupuesto agotado o producir un failed artificial.
- Ordinary sin ejecución acotada conserva la excepción y el retry previo.

Esto cubre **429**, no promete fail-fast de todos los 5xx/timeouts. No autoriza
reanudar ni repetir la lectura productiva fallida. Las solicitudes ya en vuelo
no pueden deshacerse retroactivamente.

## TDD y comandos

RED antes de fuentes: **18 FAIL / 1 PASS, 1.22 s**, `red-rate-stop.log` O_EXCL.
GREEN final: **124 PASS, 0.92 s** = 23 nuevos + 101 regresiones offline.
Ruff/formato y mypy **cinco targets PASS**, sin ignores/config reducida.

Comando pytest: `.venv/bin/python -m pytest` con los dos tests nuevos,
`test_devoluciones_onboarding_diagnostic.py`,
`test_history_question_incremental_capacity.py` y
`gateway/tests/test_pilot_get_budget_allocation.py`,
`--noconftest -o addopts='' --import-mode=importlib -q`.
Entorno externo `env -i PATH=... HOME=...`; fixtures sin ambient credentials,
sockets prohibidos, mocks/CAS RAM y collector RETURNS real contra fuentes fake.

Cobertura negativa explícita: metadata None/0/2/bad; carrera nuevo EID;
último crédito conservado; respuesta posterior al deadline sin renovación;
ordinary collector mantiene tres intentos acotados, piloto sólo uno;
conversión WAIT sin failed/proof/budget mislabel. Cinco fuentes y ambas interfaces
fetch/request. El formatting/suppress del logger conserva best-effort y quedó
cubierto por las ocho regresiones de diagnóstico.

Logs finales privados `monitor-guard-20261006`: `green-rate-stop-delivery-124.log`,
`mypy-rate-stop-delivery.log`, `ruff-rate-stop-final.log`, `format-rate-stop-final.log`.
Mypy namespace collision de fixtures se corrigió sólo con imports canónicos
del directorio tests; no se modificaron fixtures antiguos.

## Runtime afectado

`consumer.py` crea el histórico y su work gateway (`PlanBudgetGateway`), y el
callback refresh a `advance_due_devoluciones_run` → `advance_onboarding_devoluciones`
→ `OnboardingDevolucionesGateway`. Son entrypoints worker. El escaneo local de
callers no encontró ruta API servida hacia estos métodos modificados; renovación
de certificados/readers no cambió. **Imagen afectada: sheets-worker**. No rebuild
API/Gateway/Core por empaquetar/importar módulos. Root verifica drift y decide
build/deploy separados después de sus gates conjuntos.

Shipments250 agotado conserva parcial/pendientes honestos, no prueba aceptación
anual ni autoriza trasladar saldo a maintenance. Full sigue excluido, y el plazo
productivo original `2026-10-06T20:32:58Z` no se amplió.
