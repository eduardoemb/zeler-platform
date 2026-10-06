# CUOTAS: aceptación ZelerData y auditoría canónica propuesta

**ENTREGADO; NO SIGO MODIFICANDO. Auditoría local, no aceptación ni operación productiva.**
Único archivo escritor de este encargo. Sin agentes, código/tests, Git mutante,
builds, AMQP ni producción. Checkout observado `main`,
`0fc0c952766aef182acfd51edf4b1812b867fa88`; cambio existente del paralelo preservado.

Autoridad vigente: goal del paralelo **«termina zelerdata, autorizo todo»**. Permite
operaciones necesarias delimitadas por Root; no redefine aceptación ni elimina
preservación/Full excluido/cotas. Handoff §9 conserva evidencia fechada: cinco
retries estructuralmente disponibles, imágenes352f preparadas, **sin nuevo
rollout/OAuth/piloto**. No interpretar los estados antiguos de §9 como permisos
para repetir un fallo ni los resultados fechados como salud actual.

## 1. Matriz exhaustiva de aceptación del alcance vigente

Estados de esta tabla: **LOCAL** = implementación/pruebas reportadas por handoff;
**PENDIENTE REAL** = esta auditoría no verificó producción. Ningún gate se cierra
por un HTTP200, estado ready, count, build o metadata de broker aislados.

| Requisitos | Prueba/evidencia necesaria para cerrar | Estado/límite |
| --- | --- | --- |
| H01/H17, T01/T21: OAuth normal y admisión automática | Sesión/cuenta legítima HOPEMOB82453304, callback sin force → plan con policy/autoridad válidas fuera del request OAuth. Relink no exige permisos mensuales del producto ni admisión por script. Registrar evento/admisión y latencia, no tokens. | LOCAL; PENDIENTE REAL. HOLD y scope deben permitir ese callback seleccionado. |
| H02/H05, T02/T03/T12: idempotencia y recuperación | Baseline existente → relink/duplicados/reinicio sin reemplazar cutoff, datos, jobs/checkpoints/proofs ni identidad. Ownership/fence/leases conservados; publicación no duplicada. No borrar para simular cuenta vacía. | LOCAL; baseline real pendiente. Riesgos condicionales §4. |
| H03, T04: corte y calendario | Cutoff original estable, date_from = un año calendario anterior con leap-day/fin de mes, date_to/cutoff y zona coherentes; horizonte recuperable real por fuente. Cuenta joven no implica actividad previa. | LOCAL; no prometer365 días ni horizonte API no comprobado. |
| H04, T05/T08/T09: discovery completa o límites explícitos | Recibos de páginas/scroll/subdivisiones, terminación y reconciliación frente a fuente cambiante; fuente, rango y denominador acreditados. Canceladas desconocidas/no enumerables y retención se declaran, no se inventan. | PENDIENTE REAL por cada fuente; vacío de una consulta no prueba año vacío. |
| H06/H10, T17: conservación y exactitud | Junio/otros períodos previamente certificados siguen legibles; rangos disjuntos conservan pruebas independientes y no se fusionan mediante min/max atravesando huecos. DEVOLUCIONES exige provenance/vector vigente y relaciones; exacto falla cerrado sin proof. | LOCAL; comparar lectores reales antes/después. |
| H07, T07/T10: independencia | Caída de una fuente no bloquea lanes ajenas; dependencia order→shipment/pack/claim queda por registro y visible. Costos opcionales ausentes no son cero; desconocer órdenes no demuestra ausencia global de envíos/mensajes. | LOCAL; medir progreso real y causas por fuente. |
| H08/H09/H15, T06/T11/T18: utilidad parcial auténtica | Enumeration unknown ≠ detalles puntuales faltantes ≠ campo opcional ausente. Pendientes durables con causa/alcance/reintento/consumo; registros válidos consumibles, estado con observaciones sin total/porcentaje ficticio. No fabricar caso9999+1 productivo. | Prueba sintética LOCAL no sustituye parcial real por API normal. |
| API parcial compatible | POST `/sheets/formulas:execute` normal autenticado, ZELERDATA_ORDENES con allow_partial=true: valores adquiridos y metadata visible de incompletitud; default exacto y otras fórmulas no se relajan. | PENDIENTE REAL. api.py:601,763–780; **no parcial nativo Sheets**. |
| Lectores/fórmulas y muestra nativa | Reconciliación/recibos ↔ datos persistidos ↔ lectores por fuente; muestra declarada/tamaño/rango, normales/vacíos auténticos/errores exactos/retención. Hoja privada, sesión/token existente legítimos y celdas delimitadas; readback efectivo. | Smoke4×4 anterior no prueba circuito anual; no adaptar/publicar addon ni añadir fórmulas. |
| H11, T16: mantenimiento real | **Dos ciclos con cambios auténticos posteriores al cutoff**: detección/admisión, GET físico atribuido, persistencia y reader actualizado; watermark/solapamiento/catch-up, sin nueva rescan anual. | PENDIENTE REAL. Vacíos, renovación de certificados, eventos/pedidos fabricados no cuentan. |
| H12, T14: límites físicos y stops | Fuente/fase/global compartidos, normales/eventos/retries+h1/work, CAS antes transporte/pacing; ultimo crédito y lease/day/deadline/paused/revoked. Contar cargo conservado aunque no hubo envío, y audit real de envío. | LOCAL; current ceilings/saldos y runtime real pendientes. Bootstrap no trazado es gate §4. |
| H14, T19: no efectos de comunicación | Solo GET autorizados; mensajes con mark_as_read=false; ningún envío/respuesta/lectura marcada, token copiado/reasignado ni autorización manual. | Código collector: onboarding_sources.py:223. Verificar wire/efectos reales sin publicar mensajes de prueba. |
| H15: visibilidad segura | Backend/cuenta/progreso y límites honestos; distinguir adquisición/staging/publicación/proof/reader. No contenidos de mensajes, datos de compradores, raw exceptions ni credenciales en recibos. | API backfill/progress declara exact_coverage=false (api.py:158–190); no convertir status en prueba. |
| H16, T20: reversibilidad | Backup coherente/restauración aislada/evidencia anterior preservados; compatibilidad y baseline actuales, no restore sobre negocio. Rollback forward compatible conserva tokens/hechos nuevos y plan PAUSED/HOLD. | Rescate anterior es evidencia fechada, no permiso de nuevo corte/restauración. Root confirma vigencia. |
| H18, T22: anual/escala | Evidencia local de volumen/varias cuentas/renovación y métricas reales de avance/publicación/justicia/backlog. Disponibilidad útil dentro de quotas; no certificar año por muestra ni por tiempo fijo. | LOCAL según handoff; duración/hambre/ventanas reales pendientes. |
| Runtime y transporte | Fuente/digests352f exactos, worker primero/gateway después, API preservada; capacidad fresca/PRIMARY/dependencias/consumer readiness/settling; WAIT diferido confirmado antes ACK y reanudación real, no-loss. | Root y AMQP tienen gate propio. Cinco buckets/GET metadata no acreditan entrega. |
| Contratos/alcance | Registro **14 sin Full**, routing6 y demás clientes/campos conservados; otras cuentas aisladas. Jobs/datos/cutoff/checkpoints/consumos/plazos no reset/takeover/refund. | Auditoría/baseline actual pendientes. |
| H13/T15 y cláusulas antiguas Full | **EXCLUIDOS**, 0 GET/cargos/retries Full. Items/publicaciones tampoco son sexta fuente presupuestaria. | No reabrir investigación ni afirmar “no aplica” a la cuenta por exclusión de alcance. |

Base: especificación **171–188,192–251,275–289,325–378,421–442,500–528,587–597**;
handoff **19–37,446–471**. La excepción externa documentada no equivale a fuente
implementada sin arrancar ni habilita declarar completado algo que sigue pendiente.

### Cinco fuentes: qué demostrar, sin préstamo de cuotas

| Fuente | Inicial máximo adicional / mantenimiento | Evidencia distintiva y límite |
| --- | --- | --- |
| orders/comisiones | 800 / dentro de500 y≤300 fuente | Unidades calendario anuales, discovery/hydration/publicación, comisiones/cancelaciones y límites enumerables; modificación posterior no reabre año. |
| questions/respuestas | 150 / idem | Inventario/rango y reconciliación; ANSWERED sin respuesta válida queda pendiente, no KPI inventado. |
| shipments/costos | 250 / idem | IDs deduplicados de órdenes adquiridas, relaciones/costos, ausencia opcional y cobertura condicionada al inventario de órdenes. |
| messages | 300 / idem | Packs deduplicados de órdenes, páginas y ventana de mensajes; targets desconocidos no son cero. Collector inicial y periódico separados; no marcar leído. |
| claims_returns | 500 / idem | Ventanas/runs/proofs conjuntos claim+return+order y certificados acumulativos por intervalo; `/orders` derivado de claim carga claims_returns. |

Total inicial2000 + mantenimiento500, **2500 adicionales/90min/mismo UTC**; no saldo
prometido. Límites reales son los menores con policy previa y consumos medidos.
Implementación: history_onboarding.py **818–912,913–965,966–1062,1064–1174**.
Retención/source totals/fechas recuperables/producto activo no se pueden confirmar
solo con el código; requieren evidencia fuente real y limitaciones declaradas.

## 2. Auditoría productiva mínima propuesta — NO ejecutada

Root prepara tool separado con TDD y closed output. **Un API exec aprobado**,
Python3.11/factory create_runtime_db legítima en VM/VPC, PRIMARY y cierre bounded;
no asistente local Mongo. Máximo **11 comandos Mongo explícitos**, secuenciales,
maxTimeMS4000 cada lectura,50s cuerpo +5s cleanup,≤5min operación total.
Primer error/timeout/inconsistencia/resultado truncado: STOP, sin fallback/retry.
No writes/upserts/lease claims/Meli/AMQP/Google/API auth minting. Esta lectura no
es un snapshot transaccional: registrar fecha de cada grupo y deriva detectada.

Filtros: S="82453304", V=[S,82453304]. Todas las agregaciones exclusivamente
`$match → $limit → $project → resumen`, sin `$out/$merge/$function`. Una respuesta
compacta por agregado, batch1 y cursorID0; no getMore. `limit(cap+1)` detecta
truncación: cap alcanzado produce lower_bound/unknown, **no total ni ausencia**.

| Comando / colección exacta | Filtro y cap | Proyección permitida / salida segura |
| --- | --- | --- |
| 1 hello | client.admin; una vez | PRIMARY boolean, sin topología/host/URI. |
| 2 meli_accounts | seller_id∈V; cap1+1 | status enum, connected_at/created_at/updated_at/expires_at/last_refresh_at, lock_held_until; solo boolean de platform owner presente. Nunca nickname/IDs de usuario/scopes/token/cipher/nonce/KMS/last_error. Duplicado/missing bloquea. |
| 3 sheets_history_backfill_plans | `$or` _id=S o seller_id∈V; cap1+1 | identidad match boolean, policy/authority.kind/state/eligible/sources; cutoff/date_from/date_to/timezone/admitted_at/last_linked_at/next_cycle_at/lease_until; budget.<cada5>.physical_attempts/consumed,total_budget/total_consumed; execution_id/until/utc_day/attempt_limit/consumed/sent, incremental_day/policy/consumed/source counters. No lease_token ni progress/checkpoints raw. Full solo presencia/exclusión, no adquisición. |
| 4 misma colección, resumen ledger | _id=S/seller_id=S; cap1 | execution_charged/execution_sent_by_source/execution_work_sent_by_source: **solo fuente/fase/counters** del ID validado, sin claves raw en salida. execution_work: proyectar server-side únicamente source/phase/credit/sent; máximo2501 receipts procesados, counts/sumas/shape-invalid/unsent. No event/resource/claim/job identities ni owner tokens. Cap/deriva => unknown. |
| 5 module_registry | _id="sheets"; cap1+1 | status; cardinalidad/fingerprint y checks14 scopes/sinFull, routing6/contrato esperado, demás campos preservados. No credenciales/admin secrets; no seeds. |
| 6 bootstrap_jobs | seller_id∈V; cap1000+1 | state/triggered_by enum, fechas, dispatch_attempts, lease_until; checkpoint/dag **presencia y cardinalidad** solo. Resumir active/protected/terminal y riesgo de reconstrucción; no payload, IDs negocio ni tokens. |
| 7 sheets_formula_recovery_jobs | seller_id∈V; cap1000+1 | state/read_model/policy_authority, attempts/available_at/lease_until, history_protocol_version/generation/pass/checkpoint_revision/date_from/date_to/updated_at; owner token solo presencia. Agrupar legacy vs policy, active/live/expired leases. No *_ids/resource/payload/error libre. |
| 8 sheets_sync_jobs | seller_id∈V; cap1000+1 | state,created_at/requested_at/delta_through_at/available_at,attempt_count/fence/lease_until/append_started_at/updated_at; tokens solo presencia. Sin spreadsheet ID/cursor event IDs/body. |
| 9 platform_migrations | _id="sheets_sync_jobs_v2_activation_cutoff"; cap1+1 | activation_cutoff exclusivamente; permite clasificar cohortes del poller, no alterar migración. |
| 10 sheets_devoluciones_runs | seller_id∈V; cap100+1 | state, fechas/rango, expires_at, policy/plan binding solo boolean/fingerprint; numérico progreso/budget si existe. No claims/orders/windows payload. Enums desconocidos se cuentan como unknown. |
| 11 sheets_devoluciones_operations | seller_id∈V; cap100+1 | scope/state/fence/lease_until/started_at/updated_at; coverage_mode/coverage_ack_fence/coverage_epoch y contadores renewal si existen; propietario solo presencia. Sin attempt_token/owner/source fingerprint raw ni takeover. |

No recurrir a count_documents ilimitado. No logs completos ni dump Mongo. JSON
salida≤64KiB; unknown keys/tipos corruptos bloquean, no se imprimen libremente.
Si hace falta fingerprint de un checkpoint para preservación, obtenerlo en VM
mediante un **alcance adicional delimitado**, no ampliar proyecciones raw de esta
auditoría. Este baseline de metadata no prueba por sí solo conservación integral.

Separar **saldo aritmético** de **saldo ejecutable**. Con counters válidos, inicial
por fuente es el mínimo positivo de source remaining/total initial remaining/
execution remaining; mantenimiento usa source daily remaining/daily total
remaining/execution remaining. Si rollover pendiente, disponibilidad maintenance
es null, no500 gratis; si día/deadline cerrado, el saldo ejecutable es0 aunque la
resta positiva subsista. Charged−sent no es refund ni prueba de request recibido.
Las receipts work están ligadas al plan, no contienen execution_id individual:
su atribución al ID actual necesita que el ledger pruebe identidad no sustituida;
si no, resumir como plan-level/unknown, no reconstruir historia ficticia.

**Campos no existentes:** no hay `execution_enabled` ni inicio de ejecución
canónico en estos contratos. Emitir habilitación **derivada** bool/unknown de
autoridad+active/eligible+scopes+controles obligatorios+saldo+flags actuales, no
fabricar esos campos. Inicio solo desde receipt `prepare.applied/observed_utc`
y ledger; **nunca `until−90min`**, porque la ventana puede cortarse a medianoche.

Root debe cotejar además flags no secretos en **sus servicios reales**: HOLD,
admission sellers, history enabled/sellers, gateway budget sellers, recovery en
API+worker, refresh y sync poller en worker. Emitir solo booleans/scope82-only/
cardinalidad/presencia, no env raw. API Mongo no acredita flags de gateway/worker.
Bases: core/history_onboarding.py **84–163**; config.py **21–23**;
consumer.py **1364–1395,1591–1618,1644**; recovery.py **735–747**;
sync_jobs_processor.py **59–75**; devoluciones_runs.py **134–135**.

### Pruebas/progreso: segunda lectura independiente, no ampliar audit inicial

Después del baseline y antes/después del ensayo, Root puede proponer hasta4
agregados adicionales, cap64+1/maxTimeMS4s por colección,≤30s lectura:
`sheets_history_acquisitions` (seller_id∈V, read_model orders/questions; fases,
rango/generation/pass/checkpoint_revision y counts, sin payload);
`sheets_read_model_freshness` (seller S y read_model orders/questions/shipments/
devoluciones; intervalos/proof estado/fechas, sin IDs);
`sheets_devoluciones_certificates` (seller S; date_from/to,state,valid_until,
needs_reacquisition,epoch/fence y presencia provenance);
`sheets_devoluciones_operations` (seller S,scope="devoluciones"; cap1+1,
coverage_mode/coverage_ack_fence/coverage_epoch/fence, sin owner). El control
no está en una colección nueva: coverage_control usa operations
(devoluciones_certificates.py:260–275). Staging receipts no equivalen a coverage
(history_acquisition.py:1,90–91); certificados se validan contra provenance real
y lector, no solo por contar rows (devoluciones_certificates.py:354–378,516–548).

## 3. Operador: decisiones y CLIs exactos, NO ejecutados

`control_pilot` lee plan existente, exige identidad de policy/autoridad y **no
upsert** (pilot.py:79–88,282–311). Plan legacy sinpolicy → `policy_identity_mismatch`:
solo OAuth normal puede admitirlo, nunca parche/upsert/admit por script.

| Estado observado | Continuación permitida |
| --- | --- |
| Policy válida y nunca preparado, confirmado por campos+ledger | Puede realizar primera preparación **tras gates** desde consumos reales; ID nuevo aprobado32hex, no reutilizar presupuesto antiguo consumido. Ventana empieza al prepare, máximo90min y se corta a medianoche. |
| PAUSED, receipt aplicado fijado, mismo ID/day, until futuro y saldo | Reutilizar ese receipt y ventana restante; comprobar hash completo del plan/leases/gates, preview activate. No reprepare para conseguir nuevo recibo. |
| ACTIVE y ventana vigente | Observar/continuar trabajo autorizado dentro del saldo/plazo; no ejecutar activate/prepare para repetirlo. Pausar ante stop conservando consumos. |
| Día distinto, until vencido, cap agotado, receipt perdido/derivado o identidad inválida | STOP de esa ejecución; conservar datos/pendientes. No borrar campos, nuevo UUID, reset, reprepare ni flag-bypass. Root debe identificar mecanismo futuro compatible/autoridad **separada** para lo faltante; la frase amplia no cambia esta aceptación. |

Ceilings: `_prepare` usa mínimos con límites anteriores y consumo medido,
preserva ID/day y acorta al deadline existente (**116–175**). Rollover diario
pendiente produce disponibilidades null; operador no resetea contadores
(**91–113,199–209**). Runtime standing policy puede aplicar rollover natural,
sin reset de inicial/ejecución ni ampliación de deadline; work espera mientras
no exista día actual válido (worker **269–291,341–351**).

Fuente OPS congelada/hash verificados por Root, API legítima aprobada y path de
receipt exclusivo0600 ya delimitado. API d78 **no tiene el CLI nuevo instalado**;
stdin obligatorio, no `-m` dentro de imagen vieja. Cada paso registra inicio,
target/source/limit/resultado/STOP en ledger; no encadenado/retry automático.

```bash
# Solo preview, no archivo ni write Mongo:
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - prepare \
  --execution-id '<ID_HEX_32_APROBADO>' < '<FUENTE_OPS_CONGELADA>'

# Solo primera preparación permitida; PAUSED y receipt exclusivo:
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - prepare \
  --execution-id '<ID_HEX_32_APROBADO>' --apply \
  --confirm-approved-runtime --confirm-pilot-authorization \
  --receipt-out '<RUTA_PRIVADA_EXCLUSIVA_PREPARE>' < '<FUENTE_OPS_CONGELADA>'

# Hash del receipt aplicado; preservar sus bytes fuera del runtime:
docker exec '<API_RUNTIME_APROBADO>' /app/.venv/bin/python -c \
  'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("<RUTA_PRIVADA_EXCLUSIVA_PREPARE>").read_bytes()).hexdigest())'

# Preview exige receipt aplicado/SHA y gates reales ya comprobados:
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - activate \
  --receipt-in '<RUTA_PRIVADA_EXCLUSIVA_PREPARE>' --receipt-sha256 '<SHA_APLICADO>' \
  --runtime-controls-verified < '<FUENTE_OPS_CONGELADA>'

# Único PAUSED→ACTIVE permitido; no amplía ventana:
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - activate \
  --receipt-in '<RUTA_PRIVADA_EXCLUSIVA_PREPARE>' --receipt-sha256 '<SHA_APLICADO>' \
  --runtime-controls-verified --apply --confirm-approved-runtime \
  --confirm-pilot-authorization --receipt-out '<RUTA_PRIVADA_EXCLUSIVA_ACTIVATE>' \
  < '<FUENTE_OPS_CONGELADA>'
```

Flags de confirmación **no ejecutan checks**. Activate exige plan completo sin
deriva, receipt applied, sourceidentity/day/deadline/cap y ninguna lease vigente
(pilot.py **213–267,343–387**). Un archivo reservado vacío o CAS fallido se
conserva; inspeccionar antes de decidir otro alcance, nunca regenerar a ciegas.

## 4. Riesgos críticos que el estado real debe discriminar

1. **OAuth legacy:** core upgrade sinpolicy hace `$set budget/total_consumed=0`
   (**54–75**). Si el legacy ya tiene counters canónicos, demostrar preservación
   con fix local/TDD antes de disparar el callback; no manualupgrade ni afirmar
   que ese riesgo existe actualmente sin audit.
2. **Bootstrap:** OAuth sinforce conserva pending/running/succeeded, pero un
   terminal reconstruido lleva checkpoints={} y dispatch_attempts=0
   (oauth/events.py **55–87**). Auditar baseline/protected job; si hay progreso
   terminal a preservar, resolverlo antes del relink.
3. **GET bootstrap sin h1:** selector ordinario solo module sheets
   (proxy/router.py **404–417**); no crédito universal2500 para bootstrap directo.
   Pending/running/nuevo bootstrap debe estar ausente/protegido o totalmente
   aislado, o requiere integración trusted local antes de adquisición. Nunca
   etiquetar por path, permitir items como sexta fuente o prestar cuota.
4. **Fuentes/partials:** status ready y head completed no prueban rango anual ni
   consumo. Messages/shipments dependen de inventario de órdenes; horizon unknown
   sigue unknown. API parcial solo ORDENES, no extender addon para ponerlo verde.
5. **Ventana vencida:** el código no contiene un camino seguro de renovar esa
   ejecución preservando su deadline. Seguir local/lectores/rollout independientes
   autorizados mientras Root delimita lo faltante; no afirmar goal cumplido ni
   encadenar otra ventana para reunir dos cambios reales.

## 5. Orden mínimo para avanzar el goal

Root recibe ambas auditorías → prepara lectura canónica propuesta con TDD →
discrimina riesgos anteriores y saldos → cierra únicamente bloqueantes reales →
preflight/rollout seleccionado con recuperación compatible y settling → abre
admisión solo seller82 con worker historyOFF → OAuth normal → plan/baseline
preservados → prepare permitido/receipt → controles/activate → adquisición y
lectores por fuente + API parcial + muestra nativa + **dos cambios reales** dentro
de ventana. En error429/timeout/inconsistencia/límite/finUTC, STOP con pendientes
durables; sin ampliar fuentes, cuotas, tiempo o permisos originales por conveniencia.

No hacer otra build si las fuentes afectadas352f siguen ligadas a imágenes VERIFIED;
un fix necesario posterior exige nueva congelación/checks y mapa de imágenes Root.
No marcar objetivo completo hasta cerrar todos los gates de alcance, ni reducirlo
a “suficientemente bueno” con evento vacío, sample o readiness como sustituto.

Referencias abreviadas del informe: `pilot.py` =
`infra/operations/zelerdata_history_pilot.py`; `core/history_onboarding.py` =
`core/src/zeler_platform_core/history_onboarding.py`; worker `history_onboarding.py`,
`consumer.py`, `api.py`, `onboarding_sources.py`, `history_acquisition.py` y
`sync_jobs_processor.py` están en `modules/sheets/src/zeler_sheets/`;
`recovery.py` en su `formulas/`; `oauth/events.py` y `proxy/router.py` en
`gateway/src/zeler_gateway/`, igual que `config.py`; `devoluciones_runs.py` y
`devoluciones_certificates.py` en `core/src/zeler_platform_core/`.

**ENTREGADO; NO SIGO MODIFICANDO.** Solo este informe cambió por CUOTAS; ningún
estado/counter productivo fue consultado por el writer. SHA final entregado por chat.

## Key Learnings:

1. execution_enabled/inicio no son campos canónicos: habilitación se deriva e
   inicio exige receipt aplicado, no arithmetic del deadline.
2. OAuth sinforce no garantiza por sí solo preservar todo legacy; auditar estado
   y tráfico bootstrap antes de elegir la ruta normal reutilizable.
