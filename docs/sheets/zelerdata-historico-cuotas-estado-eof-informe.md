# CUOTAS: variante EOF del audit canónico

**ENTREGADO; NO SIGO MODIFICANDO. Preparación/integración local, no producción.**
Paths exclusivos nuevos, en el privado `pilot-state-audit-eof-20261006/`:
`state_audit_eof.py`, `state_supervisor.py`, `test_state_audit_eof.py` y este informe.
Además, Root permitió adaptar el harness/informe de integración propios.
Shared/core/config/deps/lock/Git/build/prod/AMQP quedan fuera del encargo.

## Delta exacto y binding

`state_audit_eof.py` embebe los bytes del original SHA
`4206e9f8cdee51e4879785cab7bfd0299d452750562ca03570b5d1c414174a5b`.
Antes de compilar verifica SHA, única función async `_body`, único assignment
`command`, única key `cursor`, único literal int batchSize1: cambia **solo1→2**.
AST dump completo exige igualdad con el original salvo esa posición. No texto
de caller/env ni código arbitrario entran a exec; noqa S102 se limita a ese
exec compilado SHA-bound. Defaults/receipts/policy/caps/projections y autoridad
originales no se alteran. El wrapper es autocontenido dentro de la imagen API.

Supervisor deriva del original congelado: solo nuevo embedding/hash y
`EOF_VARIANT_VERSION=1`. Conserva un exec API oldpin3f7, checks de identity/mount,
CLI stdin opt-in, deadlines, output64KiB, sanitización y counts upper_bound11.
Wrapper y supervisor comparten versión de variante1; receipt original siguev1.
Embedding exacto y AST supervisor sintaxis3.9 verificados sin ejecutar Docker.
API continúa `/app/.venv/bin/python`3.11; no rebuild/deploy/instalación realizados.

## Por qué2 sin consultas nuevas

Mongo7 llena batch1 con el único resumen y deja cursor abierto. batch2 permite
alcanzar EOF en ese mismo comando. No aumenta el resultado aceptable: sigue
**firstBatch≤1 + cursorID0 obligatorios**, sin getMore, retry ni segunda consulta.
Cap+1 en servidor y STOP por datos/cursor inciertos se mantienen. Todos los
recibos originales/RED y los cuatro archivos de la entrega anterior intactos.

## TDD y controles

Doce casos offline con sockets bloqueados, no DB/Docker/red/gcloud reales:
original SHA/AST delta, modelo batch1 RED vs2 GREEN, cursor0/no getMore,
firstBatch≤1, caps/projections/deadlines, hash tamper, AST fresco, CLI0op,
embedding/pin/host3.9 y supervisor bad binding0exec.

| Evidencia O_EXCL en privado EOF | Resultado |
| --- | --- |
| red-fakes.log/xml, antes del delta | 4 FAIL / 8 PASS; incluye binding pre-format incorrecto |
| green-fakes.log/xml | 12 PASS |
| delivery-fakes.log/xml, bytes finales | 12 PASS, 0 skips |
| delivery-ruff.log / delivery-format.log | PASS, 4 archivos (incluye harness) |
| delivery-mypy.log | PASS estricto estándar, 4 targets, sin reducir checks |

Lote intermedio ruff marcó SIM300 en un assertion de embedding; se invirtió
comparación sin cambio de comportamiento y se repitieron los doce casos finales.
Logs intermedios permanecen. No pruebas marginales ni suite general.

## Motor real: mismos cuatro casos

Target Root-owned Mongo7.0.43/PRIMARY/loopback; factory local explícita, jamás
ambient MONGO_URI ni factory productiva. `real-eof.log/xml`: **4 PASS** (0.48s).
Detalle/receipts en `zelerdata-historico-cuotas-mongo-integracion-informe.md`.

- Empty/current/legacy: **11/11 reads + diez cursorID0** cada uno.
- Cap1001: **STOP correcto**, count_cap_reached, 6/6 + cinco cursorID0;
  observed lower bound1001, total_known=false, sin continuar otras colecciones.
- Work reduce/sourcephase/credit/sent, ledgers h1 separados, source balances,
  bootstrap/checkpoint metadata, legacy y registro14 sin Full evaluados con filas.
- Todos: fingerprints pre/post idénticos, marker ausente, no getMore/docwrites,
  client.close y endSessions protocolar separado, flags de autoridad no inventados.

Esto demuestra semántica de estos fixtures, **no** estado productivo actual,
validators desplegados, snapshot, OAuth, permiso ejecutable o aceptación ZelerData.
No reanudé producción ni consumí sus intentos. Root valida y ejecuta lo autorizado.

## Hashes finales

| Artifact | SHA256 |
| --- | --- |
| state_audit_eof.py | `3f86e2320829915f8b86137337268b42523a164403dd7ff20e6b60af1bff1b55` |
| state_supervisor.py | `3ab036a23905a2ed62a32ad7e39d28aa962aaff200af4137b38571b3fc7911e3` |
| test_state_audit_eof.py | `2bf6e889edfbeba640c866954046438b2315350a77d4e9c44cd354d2b0938711` |
| test_state_pipeline_mongo.py final | `31dea3314822414752381d2c4e378bb44159486fd3edea72a6b2bdc7579d39d6` |

Hash de este informe y del informe de integración en `delivery-receipt.json`
privado EOF, junto con fakes/GREEN real/RED baseline y frozen hashes.
Todos los writers cesan antes de la validación independiente del coordinador.

## Key Learnings:

1. batch2 puede agotar un único resumen sin aceptar dos documentos ni getMore.
2. La prueba real es necesaria incluso cuando hash, tipado y fakes ya pasaron.
