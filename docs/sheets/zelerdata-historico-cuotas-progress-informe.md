# CUOTAS — lector acotado de progreso y baseline

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local, sin ejecución productiva ni modificación de backend. El coordinador conserva producción, Git, builds y aceptación.

## Contrato y comando

Fuentes privadas: `source-progress-20261006/progress_reader.py` y `test_progress_reader.py`, bajo `/Users/eduardoramirez/.codex/cache/zelerdata-integracion-20261005-8dafff186997`.

Default sin argumentos: NOOP, cero conexiones. Operación únicamente por stdin Python 3.11 en el API previamente verificado por Root (identidad/digest/mounts/runtime factory). Factory legítima incluida en imagen: `infra.operations.zelerdata_read_model_reconcile.create_runtime_db`; nunca se ejecutó localmente. No supervisor adicional, Docker local ni producción desde este especialista.

```sh
# Solo coordinador, después de sus fences VM/VPC/API y binding SHA del payload:
timeout 85s docker exec -i "$VERIFIED_API_CONTAINER_ID" \
  /app/.venv/bin/python - --inspect-source-progress < progress_reader.py
```

El contenedor no se selecciona por nombre/tag ambiguo: Root verifica el pin API autorizado `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417`. El reader no atesta imágenes. El coordinador acota la llamada remota/caller y registra un intento; no retry ni fallback.

## Exactamente nueve comandos explícitos

Todos de lectura. PRIMARY `hello` y ocho `find` con `maxTimeMS=4000`, `limit=batchSize=cap+1`, `singleBatch=False`, un solo firstBatch y cursor BSON cero obligatorio. Cursor vivo, cap, shape, error, timeout o cleanup fallido: STOP inmediatamente, sin getMore. `started/completed` cuentan estos comandos explícitos, no handshake/endSessions del driver. Body 50 s, hard wall 70 s, cierre bounded 5 s, salida máxima 64 KiB; errores cerrados, sin strings del driver.

| Comando | Filtro | Cap |
|---|---|---:|
| hello | PRIMARY | 1 |
| sheets_history_backfill_plans | seller/_id=82453304; execution_id=868b413e20184befb7e8358e0051924f | 1 |
| sheets_read_model_freshness | seller int/string; read_models orders/questions/shipments/messages/devoluciones | 5 |
| CERTIFICATES (constante canónica importada) | seller string | 20 |
| sheets_devoluciones_operations | clave exacta seller:devoluciones | 1 |
| sheets_formula_recovery_jobs | seller; history_plan_id pilot-12m:cutoff ISO milliseconds; orders/questions | 100 |
| orders | seller int/string; date_created BSON > cutoff | 100 |
| questions | idem | 100 |
| messages | idem | 100 |

No se repite archivo recovery cap1001, ni account/registry/bootstrap. No writes, leases, ACK, proveedor HTTP, OAuth, AMQP, reset, prepare ni activación.

## Evidencia y límites

- Plan completo solo RAM: range calendárico 12 meses exacto, cinco estados/reasons cerrados, unidades/persisted/observaciones, initial/maintenance por fuente, cargos/sends totales, until y Full. SHA exacta BSON canónica de **los campos presentes** progress/checkpoints/collector_checkpoints/message_periodic_recovery; cada estado fuente y checkpoint periódico también lleva SHA. No imprime IDs ni targets. Esto permite comparar ese subconjunto, **no** integridad de todos los campos del plan ni snapshot transaccional conjunto.
- Freshness/certificados: intervalos actual y retained independientes, metadata/epoch/revision/valid_until y SHA. Retained máximo100 por documento; no se fusionan huecos por min/max. `joint_provenance_validated=false`, `reader_calendar_coverage_proven=false`, `exact_reader_coverage_proven=false`: metadata no valida facts actuales, vector/provenance ni la lectura normal. Estados/certificados pueden ser insuficientes o desconocidos; no se atribuye cobertura 12 meses por readiness.
- Jobs: cohorte canónica del cutoff, estados y SHA de proyección segura; no archivo global ni identificadores/owner/payload. Estado job no demuestra año recuperado.
- Baseline postcutoff limitado a documentos cuyo **date_created BSON** supera cutoff: orders status+creation; questions creation solamente; messages campos canónicos text/status/creation/pack/from/to hasheados. No considera updated_at, leases/acquisition, watermarks ni contadores persisted como cambio auténtico. No detecta modificaciones a documentos creados antes del cutoff ni fechas string; ese scope queda desconocido. Shipments/claims_returns no se inventan como globalmente vacíos.
- Salida solo parejas SHA(key)/SHA(campos), SHA del sample y metadata segura. El `audit(..., baseline=...)` permite comparar una salida anterior en memoria; CLI entrega un baseline nuevo para que Root conserve/compare los archivos sanitizados. Comparación informa únicamente cambios observados en ese scope, nunca dos ciclos acreditados. `genuine_two_cycles_proven=false` siempre: requieren correlación externa con eventos auténticos, cargo físico, persistencia y reader normal.
- `old_messages_baseline_retained=true` significa **no se escribe ni sustituye el baseline anterior**; no afirma que este reader lo haya cargado/verificado. Baseline original cero permanece responsabilidad del ledger Root.
- Consultas secuenciales no demuestran aislamiento/snapshot común. Empty solo refiere filtro/momento. Si hay >100 negocios postcutoff o >20 certificados, STOP; no entrega baseline truncado como completo. No selecciona una ventana API parcial por ausencia de metadatos; Sep25–Oct5 sigue propuesta a contrastar con respuesta normal.

## TDD y controles

Logs nuevos O_EXCL preservados en el directorio privado:

- `red.log`: fallo inicial de colección/sintaxis, separado del RED de comportamiento.
- `red2.log`: **8 FAIL / 2 PASS** contra stubs antes de implementación.
- `red-bson-cursor.log`: **1 FAIL** con Int64(0); se corrigió type exacto por entero BSON no booleano.
- `red-periods.log`: **1 FAIL** para salida del intervalo retenido independiente antes de implementación.
- `red-eof.log`: **1 FAIL** para no forzar cierre de cursor. singleBatch=True puede devolver cursor0 sin agotar resultados por límite16MiB: se corrigió a False; cualquier cursor vivo STOP sin getMore.
- Final `green-eof.log/xml`: **10 PASS**; `ruff-eof.log`, `format-eof.log`, `mypy-eof.log`: PASS (dos targets, configuración estándar, sin ignores/reducción de Mypy). Los primeros quality failures quedan preservados.

Fakes aislados con sockets prohibidos, env whitelisted sin Mongo/AMQP ni credenciales, sin DB real/puertos. Prueban controles/DTO/command shape, **no ejecución del motor Mongo productivo**. Root realiza revisión/validación y cualquier lectura autorizada; este informe no autoriza resume.

## Referencias verificadas

- `core/src/zeler_platform_core/history_onboarding.py:20`: calendario, no 365 días fijo.
- `modules/sheets/src/zeler_sheets/history_onboarding.py:605-654,718-845`: estados fuente, checkpoint periódico y history_plan_id real.
- `modules/sheets/src/zeler_sheets/formulas/read_models.py:32-34,624-645,1173-1186,1363-1403,1638-1657,1951-1963`: colecciones/campos, proof vector/facts, retained_intervals y coexistencia de fechas BSON/string.
- `docs/sheets/zelerdata-historico-cuotas-aceptacion-informe.md`: aceptación source-by-source, dos cambios auténticos y native Sheet separados; Full permanece excluido. El plazo adicional es la autoridad explícita actual de Root, no reinicio de ese contrato.

## Hashes SHA-256

- progress_reader.py: `ff6b59183a69ae5e2781e6adaef7c55a67c03bd3f5e42bd84f13e8b26afb762c`
- test_progress_reader.py: `9123efb8a42e7b489bedd5f7071d9d4c8125ee4535bdab03c5b2dda2c78ea3c2`

El receipt privado liga bytes finales y logs; el hash de este informe está en receipt, evitando autorreferencia.
