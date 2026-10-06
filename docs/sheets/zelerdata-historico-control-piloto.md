# ZelerData: preparar, activar y pausar el piloto histórico

Operador canónico: [`infra/operations/zelerdata_history_pilot.py`](../../infra/operations/zelerdata_history_pilot.py).
**Rollout cerrado aplicado y verificado; piloto NO activo**, 4 de octubre de 2026 UTC.
Fuente `b867b27505b424871a92a59da459c45840cf8d8c` publicada/remoto exacto; gateway
corregido construido/verificado y desplegado, API/worker d78 desplegados sin delta
de comportamiento servido (mezcla deliberada). Cinco índices aditivos y registro14
sin Full aplicados. El respaldo/restauración fiel A–F siguen PASS, publicados
previamente en `357e055d5a26dd71f46bd1009c7aa62d6717108a`.
HOLDtrue, historyOFF e interlock legacyOFF: ninguna preparación/activación de plan
ni aceptación OAuth/API/Sheets productiva acreditada. La activación sigue
condicionada a los gates de la
[propuesta de publicación/piloto](zelerdata-historico-publicacion-piloto-propuesta.md).
No confundir una imagen disponible, un recibo local o un flag con aceptación runtime.

## 1. Antes de operar

Solo desde la VM/runtime aprobado, con **Python 3.11 `/app/.venv/bin/python`** y
la configuración Mongo legítima ya instalada. No usar el Python del host, conectar
Mongo productivo desde el asistente local, imprimir configuración ni copiar tokens.
**Las imágenes d78 no contienen este nuevo CLI.** No invocar allí `python -m`
como si estuviera instalado. El operador autorizado prepara fuera de la imagen
la fuente validada/congelada y verifica su SHA; la transmite por **stdin** al
Python3.11 de la API legítima, reutilizando `create_runtime_db` ya incluido. No
copia credenciales ni instala módulos, modifica capas o solicita otro build.
Los dos archivos fuente/tests de la unidad y sus hashes se conservan como evidencia.
El gateway desplegado ya contiene la admisión corregida; no atribuirla a su imagen
d78 antigua ni confundir ese build con este envío de OPS por stdin.

- [ ] Autorización vigente y vendedor HOPEMOB **82453304** legítimamente vinculado.
- [ ] OAuth auténtico, sin force, token transferido ni admisión manual. Si el plan
  legacy carece de `policy_version`, el operador devuelve
  `policy_identity_mismatch` **sin convertirlo**; primero debe actualizarlo el
  flujo existente de OAuth. No fabricar ese campo ni llamar admisión desde un script.
- [ ] Antes de cambiar worker: ausencia demostrada de trabajos/estado incompatibles
  con `policy_authority`, o aislamiento completo demostrado; después conservar
  controles persistidos y worker compatible. Un count histórico no basta.
- [ ] Imágenes/digests/procedencia, capacidad, readiness y recuperación compatible
  comprobados según [deploy](../deploy.md) y la propuesta. Registro objetivo
  **14 = baseline13 + mensajes**, seis routing keys, sin Full; preservar todos los
  demás campos/clientes. No reiniciar API antigua13 tras registrar el contrato14.
- [ ] Gateway inicialmente con admisión en HOLD y worker histórico OFF; allowlists
  de admisión/ejecución limitadas al vendedor. Apertura para OAuth y cambios de flags
  son operaciones seleccionadas del rollout, **no acciones de este CLI**.
- [ ] Interlock legacy del piloto: `ZELERDATA_FORMULA_RECOVERY_ENABLED=false` en
  API **y** worker; `ZELERDATA_REFRESH_ENABLED=false` en worker. El baseline real
  corroborado tenía ambas lanes activas y cohorte única HOPEMOB82453304 (cohorte82);
  API no tenía refresh configurado. Los flags son globales del servicio, no campos
  de cuenta: solo aplicar este interlock si las allowlists originales siguen siendo
  esa cohorte única, conservar listas y demás configuración/campos/cuentas. No
  convertirlo en supresión de otra cohorte ni crear un flag per-seller inexistente.
- [ ] Medición/presupuesto de las cinco fuentes y del tráfico atribuible al ensayo
  disponibles. No iniciar si recovery ajeno al coordinador evade esos límites.

No aplicar seeds generales, validadores, resets ni modificaciones de otras cuentas
para cerrar un gate. El CLI no verifica OAuth, imágenes, jobs, capacidad ni flags:
las confirmaciones afirman evidencia obtenida independientemente.

### Estado cerrado y Compose persistente

Aplicado/verificado: gateway HOLDtrue/seller82453304; worker historyOFF/seller82453304;
recovery API/workerOFF y refresh workerOFF, allowlists HOPEMOB originales intactas.
Registro **13 + único `GET /messages/packs/*` =14**, seis keys, cero scopes Full;
otros seis clientes y demás campos preservados. Índices: cinco nuevos, dos existentes
intactos, metadata anterior preservada, sin documentwrites/collMod/validadores.

Toda futura operación Compose seleccionada debe incluir **ambos** archivos:

```text
base: /opt/zeler-platform/docker-compose.yml
override: /var/lib/zeler-platform/.history-rollout-20261004T022714Z/interlocked-override-b867b27.yml
override SHA256: b7b85d5628b5df6580c8c34544db5c4bb0350ec8cb3b04fcd43c5a6234919dd1
```

No operar solo la base: perdería los interlocks/pins persistentes. Preimagen privada
del registro13 SHA `61a0e7641c2635c197b8d7cc63d3a22cf6d422389d9815b78eb461b1473853f8`
preservada: **no restaurarla automáticamente bajo API14**. Recuperación forward,
sin worker antiguo sobre `policy_authority`; no borrar jobs ni resetear estado.

## 2. Límites y conservación

| Fuente | Intentos físicos iniciales adicionales, máximo |
| --- | ---: |
| Órdenes/comisiones | 800 |
| Preguntas/respuestas | 150 |
| Envíos/costos dependientes | 250 |
| Mensajes | 300 |
| Reclamos/devoluciones | 500 |
| Full | **0**, excluido; no consultas ni retries |

Total inicial **2,000** + mantenimiento **500**, ≤300 por fuente: máximo **2,500
intentos físicos adicionales**, dentro de **90 minutos y el mismo día UTC**.
`prepare` inicia esa ventana; activar más tarde no la extiende. Se usan los menores
entre cuotas originales y ceilings calculados desde consumos existentes; una cuota
agotada sigue agotada. El límite compartido de mantenimiento puede ser conservador
cuando los consumos por fuente difieren. No se promete terminar doce meses.

Se conservan cutoff, fechas, consumos, checkpoints, trabajos, proofs, leases y
campos ajenos. No takeover, deletes, refund ni reset. Si la jornada de mantenimiento
es anterior, el recibo indica `daily_rollover_pending:true`, disponibilidades `null`
y límites de rollover natural; **el operador no reinicia contadores ni infiere
capacidad disponible**. Antes de activar, verificar día/deadline y que el runtime
aplicará sus límites naturales antes de cualquier adquisición.

## 3. Ruta mínima: dry-run → prepare → recibo fijado → activate

Los ejemplos son plantillas: sustituir los marcadores por el ID aprobado de
32 caracteres hexadecimales y rutas privadas aprobadas. No contienen credenciales.
**Ejemplo local:** solo con fixture Mongo de desarrollo verificada, nunca con
configuración productiva. `-m` requiere el checkout local donde el CLI existe.

```bash
# Default dry-run; sin escrituras Mongo ni archivo.
.venv/bin/python -m infra.operations.zelerdata_history_pilot prepare \
  --execution-id '<ID_HEX_32_APROBADO>'
```

**Operación VM:** únicamente el operador autorizado transmite el archivo congelado
a la API seleccionada. Los fragmentos siguientes describen su llamada interna,
no autorizan acceso SSH ni operar otro contenedor. La ruta de recibos debe existir
y estar aprobada dentro del runtime; el operador preserva sus bytes fuera del
contenedor. No ejecutarlos desde el asistente local.

```bash
# Preview VM del mismo archivo: solo lectura; no crea recibo en disco.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - prepare \
  --execution-id '<ID_HEX_32_APROBADO>' \
  < '/ruta/privada/fuente-congelada/zelerdata_history_pilot.py'

# Gates completos: prepara PAUSED, recibo exclusivo0600; fuente solo por stdin.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - prepare \
  --execution-id '<ID_HEX_32_APROBADO>' --apply \
  --confirm-approved-runtime --confirm-pilot-authorization \
  --receipt-out '/ruta/privada/aprobada/prepare.json' \
  < '/ruta/privada/fuente-congelada/zelerdata_history_pilot.py'

# Fijar SHA del recibo aplicado dentro del runtime; solo metadata, sin Mongo.
docker exec '<API_RUNTIME_APROBADO>' /app/.venv/bin/python -c \
  'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("/ruta/privada/aprobada/prepare.json").read_bytes()).hexdigest())'
```

Conservar el recibo y su SHA. El dry-run de preparación **no** sirve como permiso
de activación: esta exige `applied:true` y hash del **plan completo** sin deriva.
Antes de activar deben estar comprobados OAuth, presupuestos/capacidad/digests,
plan pausado, aislamiento/autoridad, allowlist seller-only y worker/gateway
compatibles. `--runtime-controls-verified` no ejecuta esos checks.

```bash
# Preview de activación: exige los mismos gates y recibo fijado; aún sin writes.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - activate \
  --receipt-in '/ruta/privada/aprobada/prepare.json' \
  --receipt-sha256 '<SHA256_RECIBO_APLICADO>' --runtime-controls-verified \
  < '/ruta/privada/fuente-congelada/zelerdata_history_pilot.py'

# Únicamente después de los gates: PAUSED → ACTIVE, sin reset ni ampliación.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - activate \
  --receipt-in '/ruta/privada/aprobada/prepare.json' \
  --receipt-sha256 '<SHA256_RECIBO_APLICADO>' --runtime-controls-verified \
  --apply --confirm-approved-runtime --confirm-pilot-authorization \
  --receipt-out '/ruta/privada/aprobada/activate.json' \
  < '/ruta/privada/fuente-congelada/zelerdata_history_pilot.py'
```

La activación rechaza lease vigente, día/deadline/límite inválido, recibo no aplicado,
pin incorrecto o cualquier cambio del plan desde `prepare`. No ampliar cuotas ni
ventana para resolver el rechazo. Los recibos de salida son exclusivos: no
sobrescribir un archivo existente. Un fallo puede dejar un archivo vacío reservado;
conservarlo y comprobar estado antes de decidir otro alcance.

## 4. Pausa, races y retirada

```bash
# Preview; no modifica el plan ni requiere un recibo de prepare.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - pause \
  < '/ruta/privada/fuente-congelada/zelerdata_history_pilot.py'

# Pausa persistida; execution-id opcional cerca la ejecución exacta preparada.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - pause \
  --execution-id '<ID_HEX_32_APROBADO>' --apply \
  --confirm-approved-runtime --confirm-pilot-authorization \
  --receipt-out '/ruta/privada/aprobada/pause.json' \
  < '/ruta/privada/fuente-congelada/zelerdata_history_pilot.py'
```

Cada apply hace **una CAS del documento completo**, no upsert: una adición o cambio
concurrente, incluido consumo/checkpoint/lease, produce `plan_changed` y **STOP sin
retry**. Después de escribir se compara el readback completo; fallo o
`applied_readback_changed` puede ser estado incierto. Inspeccionar evidencia/estado
en el contexto aprobado antes de cualquier nueva decisión; no reejecutar a ciegas.
Exit0 acredita el resultado del operador, no salud del servicio ni requests reales;
exit2 es rechazo controlado y exit1 exige inspección. Diagnósticos sanitizados,
sin URI ni datos de negocio. Guardar tiempos, SHA de recibos y contadores medidos.

`pause` solo cambia `state` a `paused`: **no prueba quiescence**. HOLD de admisión y
flags OFF tampoco demuestran cero writers ni cancelan trabajo ya cobrado/en curso.
Esperar/drainar la unidad activa y usar parada graceful autorizada con stop grace
y timeout externo suficiente; no hardkill ni takeover. Un cobro puede permanecer
consumido aunque termine en HTTP0; no reembolsarlo ni resetearlo.

Detener ante auth/denegación, presupuesto/deadline, 429 persistente, error canónico,
deriva/lease inesperado, readiness/OOM/restarts/capacidad o deterioro vivo frente
al baseline. Tras admitir estado `policy_authority`, recuperación **forward**:
mantener worker compatible, registro14 y jobs/hechos/proofs/cutoff/consumos. No
worker legacy, downgrade13, restore ciego ni borrar estado para simular rollback.
Una corrección/build/rollout adicional exige su autorización correspondiente.

## 5. Evidencia y siguiente gate

**Calidad final local PASS**, recibo privado
`zeler-pilot-gate-707d3daba082/verification-receipt.md`:

- Suite Linux completa: **5,981 passed/9 skipped/393.71s, exit0**,
  2026-10-04 02:56:23.139478→03:02:59.525633 UTC, Mongo/Rabbit propios y broker integrado.
- Protected Mongo separado: **8 passed/2.09s, exit0**. Cubre los ocho skips
  protectores del full; el noveno es Caddy intencional sin keys requeridas.
  No sumar ambos lotes como una sola ejecución pytest.
- Ruff/formato/mypy **655 fuentes** y lint direct-Meli PASS; bytes/modos de fuente
  RO intactos, OOMfalse/restart0, limpieza exclusiva de fixture propia PASS.
- Enfocadas: [operador](../../tests/test_zelerdata_history_pilot.py) **29 passed/0.10s**
  y [admisión/eventos gateway](../../gateway/tests/test_history_admission_controls.py)
  **17 passed/0.13s**.

**Dos fixes localizados, probados RED→GREEN:** admisión normaliza únicamente el
cutoff BSON leído para cálculo; activación normaliza únicamente la comparación
de `execution_until`. Default BSON devuelve UTC naive. No cambiar cliente global,
reescribir cutoff ni relajar caps, deadline, lease, counters o CAS. Caller servido
de admisión: OAuth del gateway; API/worker usan helpers de ejecución sin delta de
comportamiento. El único nuevo build gateway necesario ya terminó SUCCESS/VERIFIED
y está desplegado; no hubo tres rebuilds por copiar `core` ni rebuild por OPS/docs.

Separadamente, **Mongo real aislado con lector real default `tz_aware=False` PASS**:
CLI usa `create_runtime_db()`, dry-run sin writes, prepare→activate→pause,
deadline rechazo sin writes y race de campo añadido rechazado por CAS `$$ROOT`;
budgets/cutoff/consumos/checkpoints/leases/jobs/otro seller preservados.
Admisión gateway con constructor Motor exacto también PASS: nuevo/legacy/relink,
cutoff/progreso/certificado y colección sentinel preservados, relink solo cambia
`last_linked_at`. Son pruebas sintéticas locales, **sin OAuth/session/provider**.
El recibo CAS anterior con lector aware no cubría estos defectos; no usarlo como
evidencia final. Archivo fuente de ensayo SHA
`914f36ec6475d4860b47e8735aacbe7305d59ba720602d472bc7dc21857da396`,
base `357e055` más cuatro cambios ejecutables; no inventar un SHA de commit nuevo.

Contrato de las tres imágenes cacheadas comprobado sin red: 14 scopes
(baseline13+mensajes)/seis keys/sin Full. No es registro productivo ni despliegue.

Estos resultados no acreditan CAS contra Mongo productivo, prepare/activate
productivo ni aceptación OAuth/API/Sheets. Intentos de full anteriores invalidados
por fixture/prerrequisitos o cambio de fuente permanecen históricos, no gates.
**Runtime cerrado asentado de cuatro servicios PASS**, 2026-10-04
03:31:10.296437→03:31:16.126840 UTC: API/gateway/worker/bootstrap-dispatcher
readiness200/dependencias OK/healthy/restart0/OOMfalse. Identidades desplegadas:

| Servicio | Fuente / referencia inmutable |
| --- | --- |
| Gateway | b867b27 / `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/gateway@sha256:7054e427c15835608955cd23f694314aacccc798273cf2ac8e57b03f8c4a4b62` |
| Sheets API | d78 / `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417` |
| Sheets worker | d78 / `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:79f5c6f40f5fd25f47ae572cc9f9a9fd56e4ab1438279467d9d2ad4ea5aeba7e` |

Gateway build `3a393853-4c2a-4044-81fd-050f0fc766a0` SUCCESS, VERIFIED/procedencia
verificada, fuente completa b867b27505b424871a92a59da459c45840cf8d8c.
Builds conservados: API `99bb01b9-8254-4151-a559-74ba18bfc259` y worker
`6be598c0-8c97-4a26-9823-31808e6264cb`, ambos con fuente completa
`d78ff4e57915ca5e81a5eb6f1976ec65f111824b`.
Capacidad final: `/`35,065,282,560B/6,198,886 inodos;
Mongo47,458,525,184B/3,276,153 inodos; MemAvailable1,941,520,384B.
**Full0 consultas en esta fase; piloto inactivo.** Recibos privados
`rollout-final-closed-four-services-health-capacity-terminal.json` y terminales
worker/API-registro/gateway/índices preservados. El fallo de diagnóstico previo
queda histórico: el checker esperaba `ready` booleano, pero `/ready` del gateway
devuelve `status="ready"`; clasificado con seis fixtures offline y la captura propia.
No hubo incidente productivo demostrado ni nuevas llamadas para clasificarlo.
La salud del rollout cerrado no acredita aceptación del piloto. **Pendiente
intervención humana:** OAuth legítimo Cuenta Zeler y complemento HOPEMOB; apertura
controlada de HOLD cuando corresponda, sin force/copiar tokens ni admisión manual.
Aún sin prepare/activate, fórmulas reales, partial API productiva ni dos cambios
incrementales auténticos. El caso9,999+1 acredita solo prueba local del handler/API
normal, **no parciales disponibles en Sheets**. No activar/consultar por defecto
ni inventar evidencia humana; conservar pausa y límites hasta cerrar esos gates.

Continuar con gates de [rollout/piloto](zelerdata-historico-publicacion-piloto-propuesta.md#5-despliegue-y-rollback-seleccionados)
y evidenciar ventana/cobertura parcial real. Full permanece fuera de alcance.


## 6. Reanudar la MISMA ejecución después de un STOP (continuación 6 octubre)

`resume` es un control OPS nuevo, no otra preparación ni una autorización de
cuota. **Aún requiere publicación, gates finales y runtime compatible**. La
única ventana preparada empezó `2026-10-06T04:22:57.845386Z` y termina en BSON
`2026-10-06T05:52:57.845Z`; no cambiar ID/día/deadline aunque la corrección o los
builds consuman tiempo. El primer STOP conservó **69 cargos/67 envíos**,
56 iniciales +13 de mantenimiento, Full0. Esos saldos no se reembolsan.

El operador requiere simultáneamente:

1. Recibo **prepare aplicado original**, fijado por SHA.
2. Recibo **pause aplicado del snapshot actual completo**, fijado por SHA,
   obtenido después de quiescencia graceful y aprobación independiente del estado.
3. Runtime actualizado/compatible, flags, scope seller-only, capacidad y controles
   verificados; sin lease vivo. El CLI no verifica esos controles por sí solo.
4. Mismo execution ID/día, plazo aún futuro y no posterior a la hora original de
   preparación +90 minutos ni medianoche UTC. Caps actuales no superiores a los
   saldos originales del recibo, máximo2500/daily500/source300 y sin crédito Full.

La CAS escribe **únicamente `state: active`**. Conserva documento completo,
consumos, ledger, checkpoints, cutoff, jobs, leases y plazo. No llama `prepare`,
no admite otra policy, no reconstruye un recibo original perdido y no hace retry.
Los recibos antiguos con crédito diario no determinable se rechazan de forma
conservadora: no inferir saldo ni fabricar permiso para eludir ese gate.

```bash
# Fuente OPS congelada por stdin al Python del runtime API aprobado.
# Preview: 0 escrituras; ambos recibos aplicados y hashes siguen siendo requeridos.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - resume \
  --receipt-in '<RECIBO_PREPARE_ORIGINAL>' --receipt-sha256 '<SHA_PREPARE>' \
  --paused-receipt-in '<RECIBO_PAUSE_ACTUAL>' --paused-receipt-sha256 '<SHA_PAUSE>' \
  --runtime-controls-verified < '<FUENTE_OPS_CONGELADA>'

# Apply exclusivo: una CAS; no se extiende ni reinicia la ventana.
docker exec -i '<API_RUNTIME_APROBADO>' /app/.venv/bin/python - resume \
  --receipt-in '<RECIBO_PREPARE_ORIGINAL>' --receipt-sha256 '<SHA_PREPARE>' \
  --paused-receipt-in '<RECIBO_PAUSE_ACTUAL>' --paused-receipt-sha256 '<SHA_PAUSE>' \
  --runtime-controls-verified --apply \
  --confirm-approved-runtime --confirm-pilot-authorization \
  --receipt-out '<RECIBO_RESUME_EXCLUSIVO>' < '<FUENTE_OPS_CONGELADA>'
```

Si el snapshot cambió desde el pause, la ventana venció, un cap/counter es inválido
o hay lease vivo, STOP; no reprepare, otro UUID, refund ni restore. Resolver la
causa localmente y conservar pendientes. `pause` no demuestra quiescencia por sí
solo; apagar el poller/recrear exclusivamente worker con gracia y comprobar su
asentamiento antes de fijar un nuevo snapshot, sin modificar leases/jobs.

Pruebas enfocadas Root:18 nuevas +29 existentes =47PASS, Ruff/formato/mypy2PASS;
los gates conjuntos siguen pendientes mientras CUOTAS escribe. El error real de
mensajes se atribuyó mediante lectura readonly: BSON guardó sweep_end
`.407000`, mientras el checkpoint ISO preservó `.407414`, mismo milisegundo.
No repetir el endpoint fallido para diagnosticarlo ni debilitar la identidad del
collector; preservar el checkpoint original y corregir el caller.


### Controles conjuntos de esta corrección, 2026-10-06T04:56:13.345519+00:00

Freeze1104/tar`76db7abc2647614cd9c13512af4a96c5f3e7f2207959b915b587d29b1e71d10b`: **full6446PASS/20SKIP**, protected19PASS, enfocadas109PASS; Ruff/formato/mypy669/direct-Meli/schemaPASS. Ocho exit0 y snapshotantes/despuésintacto;907codebytes+modos delcheckout coinciden. Full402.282s/protected5.666s. Colisión inicial de importtests en focusedLinux conservada; solo fixture independiente corregida, sin excluir controles ni cambiar runtimecode. Ambos especialistas habían cesado antes de suite.

Imagen afectada: **solo Sheets worker** por caller de mensajes; OPSresume via stdin, Gateway/API sin comportamiento servido afectado. Sourcebuild exactmain pendiente de publicar/verificar; no reconstruir imágenes no afectadas. El piloto siguePAUSED69/67/Full0 y hasta05:52:57.845UTC original; gates verdes no son despliegue, reanudación ni aceptación. Native reentrada mismafórmula16celdas no produjo rutaAPI observada en readlogacotado: no afirmar recálculo fresco.
