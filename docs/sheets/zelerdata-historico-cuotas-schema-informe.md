# CUOTAS: preflight de compatibilidad aditiva de validators

**ENTREGADO; NO SIGO MODIFICANDO. Herramientas preparadas, NO ejecutadas en producción.**
Encargo directo/TDD, sin SDD ni modificación de contratos compartidos. El
coordinador conserva ejecución productiva, ledger, Git, builds y rollout. Una
respuesta de estas herramientas no acredita AMQP, documentos válidos, salud del
producto ni aceptación del piloto.

## Alcance cerrado

Paths propios preparados:

- `$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/validator-preflight-20261005/validator_inspection.py`
- En ese mismo directorio: `validator_supervisor.py` y `test_validator_inspection.py`.
- Este informe, único cambio propio en el checkout durante este encargo.

Solo lectura adicional de factory/runbook en
`infra/operations/zelerdata_read_model_reconcile.py` y
`infra/operations/zelerdata_history_pilot.py`. Se cotejó el pin con handoff §3:

```text
us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-api@sha256:3f7ac7c066a09f3c1f5e15201853e89e424c71a9bafb7415e3de5eb898f31417
```

No variante abreviada, typo, tag ni imagen recién construida sustituye ese pin.
Servicio único seleccionado: `sheets-api`. No pulls, restarts, Compose, reparaciones,
config/dependencias, agentes adicionales, Git mutante ni llamadas productivas por
este writer. La modificación existente del paralelo se preservó como ajena.

## Procedimiento preparado — solo coordinador

Default sin argumentos es **inactivo**. Supervisor y lector requieren fuente
por stdin y `--inspect-schemas`; el lector exige Python3.11 antes de crear runtime.
El supervisor es stdlib/Python≥3.9, sin requerir que el helper nuevo esté instalado
en la imagen: lleva el lector congelado y verifica su SHA antes de usarlo.

En VM/VPC aprobado, el supervisor hace únicamente:

1. `docker ps` filtrado a servicio API y running: exige exactamente un ID completo.
2. Inspect con formato cerrado de ID/running/imageID/service, sin env/config raw.
3. Image inspect de RepoDigests y cotejo del pin exacto conservado.
4. **Un único** `docker exec -i <ID> /app/.venv/bin/python - --inspect-schemas`,
   con el lector congelado por stdin. Sin exec `-V`, fallback, probe ni retry.

El lector importa `create_runtime_db` incluido en esa imagen
(`read_model_reconcile.py:1833–1842`); usa únicamente su client/db legítimos.
Ejecuta hello para exigir PRIMARY y **un** listCollections filtrado a:

```text
sheets_history_backfill_plans
processed_event_claims
sheets_sync_jobs
```

Batch máximo3, cursorID debe quedar0. Si falta una colección, hay duplicados,
respuesta inesperada o paginación, STOP: **sin getMore**. Cero queries de
documentos, escrituras, validaciones de documentos, apply/collMod, Meli o AMQP.
Los counters0..2 cuentan comandos explícitos del tool; no pretenden contar los
handshakes/monitorización internos del driver.

Ventanas preparadas: cuerpo lector50s + cierre máximo5s =55s; exec máximo60s.
Supervisor remoto limitado internamente a120s (menor al máximo150s autorizado),
dejando margen al caller130s y cleanup de grupo5s del coordinador. No inicia exec
si queda menos de60s. Cierre de client siempre en finally tras obtener runtime;
alarma acota el cierre productivo. El supervisor no vuelve a ejecutar ni intenta
rescatar un fallo consumiendo otra operación.

## Gate proporcional y salida sanitizada

Salida JSON cerrada, enteros estrictos y tri-state bool/null para compatibilidad.
Solo existencia/tipo, presencia+SHA del validator, presencia/enum de
validationLevel/Action y boolean fences de los campos aditivos. No validator
crudo, documentos, DB/host/URI/env/credenciales, mensajes libres de error ni
tracebacks. La configuración/factory y logging están dentro del sink sanitizado;
el supervisor descarta stderr y rechaza receipts abiertos o incoherentes.

- **Validator ausente o `{}`:** compatibilidad aditiva inequívoca en cualquiera
  de las tres colecciones. PASS permitido; drift/ausencia respecto del esperado
  se informa mediante `expected_match=false`, no exige instalación/reparación.
- **Claims/sync con fingerprint local conocido:** campos aditivos permitidos;
  PASS si la metadata restante es coherente.
- **Validator custom/restrictivo/desconocido, tipos inesperados o enum desconocido:**
  compatibilidad unknown/false y gate cerrado; sin reinterpretarlo ni repararlo.
- Tipo view/other, ausencia de colección, PRIMARY no acreditado o cleanup fallido:
  STOP/gatefalse.

Payload fingerprint: JSON UTF‑8 compacto, claves ordenadas, excluyendo
validationLevel/Action. Validator explícito `{}` conserva presencia=true y su SHA;
ausente conserva presencia=false/SHA=null. Defaults strict/error mantienen
presencia=false, separados del enum efectivo. No se hashea configuración de conexión.

Fingerprints conocidos:

| Colección | SHA validator |
| --- | --- |
| processed_event_claims | f2358aba1c69e043e724a5de7ed27d464fa13924933f476020b6f359f471dbed |
| sheets_sync_jobs | a8e49386cd8731aa435cb1ef94f25122ca961bf83166fb995ce432fafcd398ba |
| sheets_history_backfill_plans | Sin schema local/fingerprint esperado; solo ausencia/{} es aceptado automáticamente. |

Después de exec iniciado sin receipt confiable: `mongo_counts_known=false`,
counters=null y upper_bound2. **No se inventa cero consumo.** Antes de iniciar
exec, known=true/counters0; un receipt válido de STOP conserva los counts reales.
La marca reader_started se coloca solo al invocar exec, no al planearlo.

## TDD y evidencia offline

Fakes y callbacks exclusivos, sin puertos/red/DB/Docker/gcloud. Factory real no
se creó en pruebas; casos CLI usan factory fake y sys.argv stdin simulado.
Entorno hijo whitelisted, sin MONGO_URI ni credenciales ambientales; sockets
connect/connect_ex bloqueados; uv offline/no-sync, .venv compartido intacto,
pytest sin cacheprovider y basetemp/caches privados dentro del directorio propio.
No suite general ni interacción con recursos AMQP.

| Control | Resultado | Evidencia privada |
| --- | --- | --- |
| RED inicial con stubs, colección correcta | 23 FAIL / 3 PASS, exit1 | red.log / red.xml |
| GREEN inicial | 27 PASS, exit0 | green2.log / green2.xml |
| RED receipt/deadline | 2 FAIL / 30 PASS, exit1 | red-receipt.log / .xml |
| RED fence integer1 aceptado como bool | 1 FAIL / 32 deselected, exit1 | red-fence.log |
| RED CLI versión3.11/hash antes contrato | 2 FAIL / 33 deselected, exit1 | red-cli.log |
| FINAL primera entrega | 35 PASS / 0 SKIP, 0.099s, exit0 | final.log / final.xml |
| Ruff/check y formato/check, tres archivos privados | PASS / PASS, exit0 | ruff.log / format.log |
| Gramática Python3.9 de ambos scripts stdlib | AST PASS, sin ejecutar runtime3.9 | Inspección estática offline |

Los intermedios no se suman al final. Un error inicial de congelación conservó la
expresión placeholder SHA multiplicada y bloqueó seis casos antes de exec;
corregida y GREEN repetido. El checker cerrado exige SHA válido para validator
presente, tipos bool/null auténticos y coherencia de gate/PRIMARY/counts/cleanup.

Ruff usa supresiones localizadas justificadas: asserts solo en test; exec solo
para el contrato congelado y verificado; vectores Docker fijos sin shell; catches
genéricos únicamente para convertir errores de librería/cleanup en códigos fijos.
Sin reducir gates del repositorio, sin Mypy general ni pruebas Mongo nuevas.

### Reapertura acotada: Mypy estándar del coordinador

Tras la primera entrega, el coordinador ejecutó Mypy sobre los tres privados y
observó **146 errores no-untyped-def/call**. Ese fallo quedó preservado en
`coordinator-mypy.log`, SHA256
`465dc1ace37d86e7b582f6a3bd8355ae3ec5eb302fe31186def86ec54f051023`;
no se ocultó ni sustituyó por el PASS de pytest.

Se reasignaron exactamente los mismos cuatro paths para añadir anotaciones
stdlib/future annotations, **sin cambiar comportamiento, scope, cotas o tests**.
Los límites SDK/JSON/reflexión mantienen tipos dinámicos explícitos; fixtures y
callbacks quedaron anotados. Mypy luego mostró cuatro errores concretos del
loader opcional y la unión dict/list del fixture Docker: se corrigieron mediante
casts del loader SourceFileLoader de los `.py` controlados y anotación de la unión,
sin cambiar sus valores. No config global, ignore flags o supresiones Mypy.

Controles finales sobre los bytes nuevos:

| Control | Resultado | Evidencia privada |
| --- | --- | --- |
| Mypy estándar pyproject, tres targets, cache propio | **PASS**, exit0, 3 source files | typing-mypy.log |
| Ruff/check y formato/check, tres targets | PASS / PASS, exit0 | typing-ruff.log / typing-format.log |
| Mismos casos focused, sin ampliar suite | **35 PASS / 0 SKIP**, 0.100s, exit0 | typing-final.log / typing-final.xml |
| AST Python3.9 de los tres archivos y binding embebido exacto | PASS | delivery-receipt.json |

Se reembebió el lector ya tipado/formateado y se verificó igualdad de bytes y SHA.
`delivery-receipt.json` fija los cuatro hashes actuales y los recibos de control;
los hashes de la primera entrega no deben usarse para ejecutar esta versión.

Reproducción offline:

```bash
D="$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/validator-preflight-20261005"
UV_BIN=$(command -v uv)
env -i PATH="$PATH" HOME="$HOME" UV_CACHE_DIR="$D/uv" PYTHONDONTWRITEBYTECODE=1 \
  "$UV_BIN" run --offline --no-sync pytest -q -p no:cacheprovider \
  --basetemp="$D/typing-final-tmp" --junitxml="$D/typing-final.xml" "$D/test_validator_inspection.py"

env -i PATH="$PATH" HOME="$HOME" UV_CACHE_DIR="$D/uv" PYTHONDONTWRITEBYTECODE=1 \
  "$UV_BIN" run --offline --no-sync mypy --cache-dir "$D/mypy-writer" \
  "$D/validator_inspection.py" "$D/validator_supervisor.py" "$D/test_validator_inspection.py"
```

## Hashes y entrega

| Path privado, relativo al directorio indicado | SHA256 final |
| --- | --- |
| validator_inspection.py | f5f48d429c18198e448a09065b52ca1a52679551f472c404f65402fca80a6d3b |
| validator_supervisor.py | 7abb8eeefa1c34e03ebb97a53498ef7fc59445f10c0d965223c1150affb8c9fe |
| test_validator_inspection.py | d90a2c764c0f7e363e9b5295ffbd9509a3787ef544b6a135c35e3b5a31199b90 |
| Este informe | SHA final entregado por chat, sin autorreferencia circular. |

El coordinador debe verificar esos hashes y el embebido antes de ejecutar, fijar
inicio/target/source/cotas en su ledger y conservar resultado/STOP incluso si falla.
Esta preparación **no concede autoridad nueva**, no ejecuta el gate y no acredita
el validator productivo actual. La aceptación de datos/piloto y AMQP permanece
separada. No aplicar validators ni reconstruir imágenes por esta lectura.

**ENTREGADO; NO SIGO MODIFICANDO.** Ownership de los cuatro paths devuelto al
coordinador; cualquier reapertura requiere nueva asignación expresa.

## Key Learnings:

1. Ausencia/validator vacío demuestra compatibilidad aditiva sin autorizar repair.
2. Un receipt incompleto después de exec no permite afirmar cero comandos Mongo.
