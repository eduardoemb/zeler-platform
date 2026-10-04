# ZelerData: preparar, activar y pausar el piloto histórico

Operador canónico: [`infra/operations/zelerdata_history_pilot.py`](../../infra/operations/zelerdata_history_pilot.py).
**Este runbook no acredita despliegue ni piloto activo.** La preparación registra
imágenes d78 verificadas y descargadas; el respaldo y su restauración aislada fiel
son PASS, con cierre A–F publicado previamente en `357e055d5a26dd71f46bd1009c7aa62d6717108a`.
**El gateway requiere una nueva imagen** por el fix de admisión BSON, desde el
SHA exacto que se publique; API/worker conservan comportamiento d78 y sus imágenes
ya verificadas/cacheadas, sin reconstruirlas por OPS/docs. La ejecución productiva
sigue condicionada a los gates de la
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
El build necesario del gateway es distinto de este envío de OPS por stdin: no
atribuir disponibilidad de la admisión corregida a su imagen d78 antigua.

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
comportamiento. Hace falta **un build gateway** desde publicación exacta verificada;
no tres builds por copiar `core`, ni rebuild por operador/docs.

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
**Baseline runtime de cuatro servicios PASS**, 2026-10-04
03:07:00.996899→03:07:05.538659 UTC: HTTP200/dependencias OK/healthy/restart0/OOMfalse,
digests anteriores, sin reparación ni despliegue. El fallo de diagnóstico previo
queda histórico: el checker esperaba `ready` booleano, pero `/ready` del gateway
devuelve `status="ready"`; clasificado con seis fixtures offline y la captura propia.
No hubo incidente productivo demostrado ni nuevas llamadas para clasificarlo.
Esta salud de imágenes anteriores no prueba el rollout nuevo: publicar SHA exacto,
build gateway/procedencia, índices seleccionados y rollout/piloto siguen pendientes;
repetir los gates seleccionados después del despliegue autorizado.

Continuar con gates de [rollout/piloto](zelerdata-historico-publicacion-piloto-propuesta.md#5-despliegue-y-rollback-seleccionados)
y evidenciar ventana/cobertura parcial real. Full permanece fuera de alcance.
