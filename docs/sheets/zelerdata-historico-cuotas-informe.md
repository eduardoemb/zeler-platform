# CUOTAS: reparto físico del piloto ZelerData

**ENTREGADO; NO SIGO MODIFICANDO. Evidencia exclusivamente local.**
Cerrado el escape de envío sin reparto y endurecido h1; **NO cerrado el gate
funcional de adquisición normal/eventos**. Esa habilitación requiere intención
confiable y decisión/integración del coordinador, no inferencia del especialista.

Base HEAD: `7cbd1629ab1fda657d88f5ecf20a798bd6f3ac34`.
Ownership: [paralelo §2.1](zelerdata-historico-paralelo.md).

## Propuesta previa para archivos reservados

El contrato autenticado actual del proxy aporta módulo y vendedor, no fuente/fase
para GET normales/eventos. `/orders/*` es compartido entre órdenes y reclamos;
no se puede decidir la fase por path, por el estado global de onboarding ni por
headers arbitrarios. La única atribución existente es h1, respaldada por un
crédito persistido que `PlanBudgetGateway` cobra por fuente/fase antes del envío.

Antes de habilitar normales/eventos, el coordinador debe resolver explícitamente
su intención durable confiable en `core/src/zeler_platform_core/history_onboarding.py`
y su integración por flujo en `modules/sheets/src/zeler_sheets/consumer.py` y
`modules/sheets/src/zeler_sheets/sync_jobs_processor.py`. La propuesta es reutilizar
la autoridad por fuente/fase y el cargo único de `PlanBudgetGateway` únicamente
cuando la intención real de cada trabajo la justifique, con tests de eventos,
reintentos y carreras. No agregar tags inferidos del endpoint ni permitir mintar
créditos desde headers. Si el contrato persistido necesita ampliarse, requiere
decisión del coordinador sobre modelos y operador antes de implementarlo.

**No se implementa esa propuesta ni se editan esos archivos reservados aquí.**
Mientras esa dependencia siga abierta, el cambio mínimo autorizado es fail-closed:
GET seleccionado sin atribución h1 válida queda en WAIT antes de cargo/transporte;
no usa el cargo global como sustituto del reparto. h1 conserva cargo previo y
reserva de envío sin doble cargo, con revalidación de autoridad actual.

El gate de ejecución normal/eventos atribuibles permanece pendiente. Bloquear no
acredita dos incrementales reales ni autoriza activar el piloto.

## 1. Inventario y cambios mínimos

| Camino | Cargo / atribución actual | Resultado local |
| --- | --- | --- |
| Históricos iniciales `PlanBudgetGateway` | CAS incrementa `budget.<fuente>.consumed`, `total_consumed`, `execution_consumed` y crédito `execution_charged.<id>.<fuente>.initial`. | Cinco fuentes probadas con worker y proxy reales; sin cambiar worker. |
| Mantenimiento `PlanBudgetGateway.incremental` | CAS incrementa diario total/fuente, ejecución y crédito `maintenance`; conserva iniciales. | Cinco fuentes probadas, no préstamo entre fases. |
| h1 discovery/bootstrap o detail/sheets | Header válido + crédito persistido exacto, path permitido y CAS tardío de sent total/fuente/fase. No incrementa consumo nuevamente. | No doble cargo; controles obligatorios del seller seleccionado también para discovery bootstrap. |
| GET normal/evento seleccionado sheets, sin h1 válido | JWT solo identifica módulo/seller; path o headers arbitrarios no acreditan fase/fuente. | WAIT `pilot_execution_unavailable`, HTTP429/attempts0 por ruta autenticada; sin cargo ni transporte. No adquisición funcional acreditada. |
| Retry interno normal del gateway | El gate de atribución se ejecuta antes de construir/enviar solicitudes seleccionadas. | Cero intentos si no hay atribución; no permite agotar solo el total global. |
| Retry de llamada h1 | h1 exige retry gateway disabled; cada nueva llamada al worker cobra una sola vez. | Tres respuestas502 simuladas por cada fuente/fase: tres cargos y tres envíos, nunca nueve. |
| Kernel `_reserve_pilot_get_send` + hook retry | Conservado como regresión low-level de CAS global; **no autoridad de reparto**. | Tests originales de backoff/fallo físico se ejecutan sobre kernel directamente, no prueban habilitación normal del proxy. En proxy seleccionado el gate impide alcanzarlo sin h1. |
| Seller no seleccionado, otros módulos o métodos | Selector ordinario sigue limitado a sheets/GET/seller opt-in; no ampliado. | Regresiones de no intervención preservadas. Validación de cuenta/OAuth/scopes sigue antes del forwarding. |
| Bootstrap sin h1, tráfico de otros módulos | No pertenece al selector ordinario actual; no se amplía por analogía. | Identificar cualquier tráfico atribuible al ensayo en esos caminos antes del piloto es gate del coordinador. No afirmar cobertura universal. |
| Full / items | Full excluido; items no es sexta fuente del piloto. | Unattributed seleccionado bloqueado; prueba autenticada mantiene denegación Full por scopes. No requests reales. |

Defectos reproducidos antes del cambio:

1. GET normal/evento enviaba con cargo exclusivamente global, sin fuente/fase.
2. CAS de h1 podía enviar tras deriva de `authority.kind` o `seller_id`.
3. h1 seleccionado aceptaba ausencia de deadline/día/cap/counter; sent negativos
   o crédito booleano también permitían envío.

`router.py` bloquea el primero y cerca los otros en CAS con identidad, autoridad,
campos existentes y tipos/rangos. No cambia headers, schema, cuotas, modelos,
selector ni contrato de WAIT. Datos corruptos se rechazan, no se reparan.
Una reserva cuyo deadline vence después del CAS permanece consumida y no envía;
fallos de transporte conservan cargos. Los contadores sent son reservas
conservadoras, **no prueba de recepción de Mercado Libre**.

## 2. Límites preservados

| Fuente | Inicial adicional máximo | Mantenimiento adicional máximo |
| --- | ---: | ---: |
| orders | 800 | ≤300 dentro del conjunto500 |
| questions | 150 | ≤300 dentro del conjunto500 |
| shipments | 250 | ≤300 dentro del conjunto500 |
| messages | 300 | ≤300 dentro del conjunto500 |
| claims_returns | 500 | ≤300 dentro del conjunto500 |
| Full | **0** | **0** |
| Conjunto | **2,000** | **500** |

Techo conjunto **2,500 intentos físicos adicionales / 90min / mismo día UTC**.
Estos números NO son saldos consultados. Se conserva la autoridad del operador:
ceilings absolutos calculados sobre consumos canónicos, mínimos de las cuotas
previas, sin reset/refund/reprepare/reasignación. El operador reservado no fue
modificado ni ejecutado. Su recibo/baselines/prepare/activate siguen pendientes
del contexto autorizado; no se infiere disponibilidad porque el piloto no inició.
Las pruebas usan baselines no cero y comparan cutoff/checkpoints/leases/límites
antes/después. Deadline o cambio de día bloquea antes del rollover; no extiende
ventana ni saldo. No se cambió la política natural fuera del piloto.

## 3. TDD, recursos y comandos

El usuario confirmó **turno reservado CUOTAS; AMQP no ejecuta pruebas simultáneas**.
Fakes propios con `asyncio.Lock` para CAS, ASGI local y `httpx.MockTransport`.
No Mongo, broker ni proveedor; ningún target existente reutilizado. `.venv`
ya instalado, `uv run --no-sync`, sin installs/dependencias/config global.
Caches/logs/basetemp propios:
`$HOME/.codex/cache/zelerdata-paralelo-20261005/cuotas/`.
`PYTHONDONTWRITEBYTECODE=1`, pytest sin cacheprovider; ruff sin cache y mypy cache
propio. Los lotes finales bloquearon `socket.socket.connect/connect_ex` a nivel
de proceso; las URLs impresas por httpx son de MockTransport, no llamadas reales.

| Ejecución | Resultado / exit | Recibo local |
| --- | --- | --- |
| RED1, allocation inicial | **16 fallos funcionales**, exit1, antes de cambiar router. | `red.log` |
| GREEN inicial con regresiones corregidas al nuevo bloqueo | 79 passed, exit0. | `green-second.log` |
| Matriz worker+proxy ampliada | 68 passed, exit0; sin cambios worker. | `matrix.log` |
| RED2, controles obligatorios/créditos corruptos h1 | **7 failed / 68 deselected**, exit1, antes de ampliar CAS. | `red-h1.log` |
| GREEN h1 intermedio | 138 passed, exit0. | `green-h1.log` |
| FINAL gateway, tres archivos | **150 passed / 0 skipped**, 0.53s, exit0. Incluye 87 allocation, no sumarlo con lotes previos. | `final-gateway.log` |
| FINAL pacing sin Mongo | **6 passed / 10 deselected**, 0.40s, exit0. Lote independiente. | `final-pacing.log` |
| Ruff/check y format/check sobre tres archivos cambiados Python | PASS, exit0 / 3 ya formateados, exit0. | `ruff.log`, `format.log` |
| Mypy enfocado, tres archivos Python | PASS, exit0. **No mypy del repo completo.** | `mypy.log` |
| Lint direct-Meli | PASS, exit0. Scan estático, no ejecución runtime. | `direct-meli.log` |

Se corrigió un error de import durante colección (`test_pilot_get_budget` bajo
importlib → import por `gateway.tests`) antes de RED1; no se contó como RED de
comportamiento. Fallos iniciales de formato/lint del nuevo test se corrigieron y
los gates enfocados se repitieron. El primer GREEN parcial tuvo siete expectativas
antiguas de normal global-only; se reemplazaron por bloqueo y por pruebas
low-level explícitas del kernel, sin usar mocks para simular atribución inexistente.

Comandos reproducibles **solo cuando el coordinador vuelva a reservar turno**:

```bash
Q="$HOME/.codex/cache/zelerdata-paralelo-20261005/cuotas"
export PYTHONDONTWRITEBYTECODE=1 UV_CACHE_DIR="$Q/uv"
# Wrapper usado en los lotes finales: cualquier intento de socket falla.
uv run --no-sync python -c 'import socket,sys,pytest; denied=lambda *a,**kw: (_ for _ in ()).throw(AssertionError("CUOTAS socket forbidden")); socket.socket.connect=denied; socket.socket.connect_ex=denied; sys.exit(pytest.main(sys.argv[1:]))' \
  -p no:cacheprovider --basetemp="$Q/final-gateway-tmp2" \
  gateway/tests/test_pilot_get_budget_allocation.py \
  gateway/tests/test_pilot_get_budget.py \
  gateway/tests/test_history_proxy_attribution.py

uv run --no-sync python -c 'import socket,sys,pytest; denied=lambda *a,**kw: (_ for _ in ()).throw(AssertionError("CUOTAS socket forbidden")); socket.socket.connect=denied; socket.socket.connect_ex=denied; sys.exit(pytest.main(sys.argv[1:]))' \
  -p no:cacheprovider --basetemp="$Q/final-pacing-tmp" \
  modules/sheets/tests/test_history_execution_controls.py \
  -k 'concurrent_policy_charges or reserved_credit'

P=(gateway/src/zeler_gateway/proxy/router.py \
   gateway/tests/test_pilot_get_budget.py \
   gateway/tests/test_pilot_get_budget_allocation.py)
uv run --no-sync ruff check --no-cache "${P[@]}"
uv run --no-sync ruff format --check --no-cache "${P[@]}"
uv run --no-sync mypy --cache-dir "$Q/mypy" "${P[@]}"
uv run --no-sync python -m infra.lint.check_direct_meli .
```

RED1 fue pytest de allocation únicamente (`-q` adicional); RED2 mismo archivo
con `-k 'mandatory_pilot or corrupt_prepaid'`. Sus logs preservan las pruebas
antes de cada cambio. El código final ya no reproduce esos fallos; no se revierte
el checkout para reejecutar RED. No se ejecutó la suite general durante escritura.

## 4. Paths, hashes y preservación

Solo cuatro paths propios cambiados, ninguno reservado:

| Path | Estado / SHA256 |
| --- | --- |
| `gateway/src/zeler_gateway/proxy/router.py` | Modificado; `2ae2e390b1f39f1ba958670d17dda982b28470bbdca7358a162a87edf058a332` |
| `gateway/tests/test_pilot_get_budget.py` | Modificado; `f79f024f2b108bc3f76c3dffb9090e7d4edcd564c2a6b0a1eb9dcc81ccbb6bc7` |
| `gateway/tests/test_pilot_get_budget_allocation.py` | Nuevo; `9163e6e2b647d801e36098fac04b4e7710d46ee40d1b43120c5a7a4a0db260f0` |
| Este informe | Nuevo; SHA final en recibo privado `cuotas-final-receipt.json`, no autorreferencia circular. |

Asignados pero intactos respecto de HEAD:

| Path | SHA256 |
| --- | --- |
| `gateway/src/zeler_gateway/proxy/retry.py` | `a78cd0bbc141ec4925cbf01f6886e7f04a7452a8bd07b2a7f9c946ad77c46438` |
| `modules/sheets/src/zeler_sheets/history_onboarding.py` | `84d4a4c01bc6e02c186c25e07ebc2f2ed68e160eea42bcc4acaa733b31682a5f` |
| `gateway/tests/test_history_proxy_attribution.py` | `ccbbf9cf9d274640e2d2ed14ddcd29019675ad6c0e656ecda53564a341ce0a65` |
| `modules/sheets/tests/test_history_execution_controls.py` | `8cf92b1e79cc2cdc3a74aa232b193cfbf4bca7b69afc7cfc46f990207e60f0c6` |

El paralelo sin seguimiento ya estaba presente al comenzar; durante el trabajo
aparecieron paths AMQP ajenos (`test_pilot_get_budget_consumers.py`, informe AMQP,
tests/helper AMQP). Se preservaron sin editarlos/staging/commit. `git status`,
`git diff`, `git show` y `git diff --check` fueron lecturas; ninguna operación
Git de escritura, branch/worktree/stash/reset/build ni producción.

## 5. Gates, imágenes y pendientes para el coordinador

| Gate | Estado |
| --- | --- |
| No envío normal seleccionado sin atribución | **CERRADO LOCAL**, fail-closed, no adquisición funcional. |
| Fuente/fase h1, sin doble cargo, cinco fuentes/ambas fases | **PASS LOCAL**, cargo worker existente + envío CAS gateway. |
| Último crédito concurrente fuente/fase/global, normal+h1 y replay | **PASS LOCAL fakeCAS**; no evidencia de atomicidad Mongo real. |
| Día/deadline/paused/lease, conservación, fallos físicos | **PASS LOCAL** con límites de fixtures y pacing. |
| Habilitación normal/eventos con atribución auténtica | **PENDIENTE** propuesta inicial; resolver origen por trabajo/flujo y revisar bootstrap sin h1. No reactivar por el techo global. |
| Mongo real, protected y diez casos deselectados de execution_controls | **PENDIENTE** target propio verificado por coordinador. No llamarlos PASS ni skips cubiertos. |
| Congelación de ambos especialistas + cuatro gates generales | **PENDIENTE COORDINADOR**; no hay recibo de aprobación/review fabricado. |
| AMQP real, consumo canónico, imágenes/config/runtime/OAuth/piloto | **NO VALIDADO NI OPERADO** por CUOTAS. |

Delta CUOTAS afecta **gateway**. No cambió implementación worker/API, core,
dependencias, Dockerfiles ni operador. El coordinador debe combinar el delta AMQP
antes de determinar imágenes finales. Para servir este fix necesita gateway de
fuente final publicada/validada, no el pin cb63260 anterior; publicación/build y
deploy son operaciones separadas fuera de este encargo. No se construyó nada.

Antes de activar: resolver el gate funcional de normales/eventos o registrar
explícitamente su bloqueo y aceptación pendiente; validar Mongo real/counters/CAS,
topología/WAIT, runtime servido, scopes/identidad, presupuestos canónicos y
día/deadline. La evidencia local no autoriza prod ni sustituye aceptación anual,
parcialAPI, smoke nativo o dos incrementales reales. No ampliar cuotas ni ventana
para obtener esos cambios. Reportar STOP/gates concretos si no ocurren.

**ENTREGADO; NO SIGO MODIFICANDO.** Ownership devuelto al coordinador. Cualquier
ajuste posterior requiere solicitud expresa y nueva evidencia afectada.

## Key Learnings:

1. Módulo/seller autenticados y path no bastan para atribuir fuente/fase; unknown
   se bloquea, no se etiqueta ni se cobra solo al global.
2. Crédito h1 prepagado y CAS de envío deben cercar autoridad/identidad/controles
   y tipos; un header no crea crédito ni debe aceptar contadores corruptos.
3. FakeCAS/MockTransport prueba conservación local, no Mongo real ni proveedor;
   una entrega fail-closed no acredita habilitación normal/eventos o piloto.
