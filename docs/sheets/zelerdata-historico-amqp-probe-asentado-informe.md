# ZelerData AMQP — espera fija de metadata, sin relajar guards

**ENTREGADO; NO SIGO MODIFICANDO.** Preparación local:10 unittest fake PASS,
cero skips; ruff/formato/mypy de tres fuentes PASS. No producción por AMQP.
Root conserva operación única pendiente; no se ha consumido el probe por esta entrega.

## Cambio único

Wrapper SHA-bound del [probe original congelado](zelerdata-historico-amqp-probe-informe.md),
fuente `d49d678d99d397fea18a5fb52b3d6507a87cb86239dfa9be289fed6bc22e9413`.
Inserta **solo `await sleep(6.0)`** en nestedwork, después del loop de las dos
DeclareOk/ownershipguards y **antes** de crear cliente HTTP/primer GETmetadata.
Ninguna modificación a código/guard/counter original. El sourceSHA fija versión;
AST exige un execute/work,51 nodos originales, único cliente en posición12 y
loop server-named propio anterior. Perfil `settle6_after_declares_before_http_v1`.
Remove-and-compare AST acredita que solo se insertó esa sentencia.

El supervisor conserva exactamente perfil/vectores/validators/deadlines del
originalSHAc0618d20…: comparaciónAST solo permite las dos nuevas bindings de
sourcebytes/SHA. Workerold79f/uncontendorrunning/hash/oneexec/noenvforward unchanged.

Root registró el scope en [ledger](zelerdata-historico-paralelo.md), sección
«Asentamiento de metadata antes de prueba temporal». Reportó freshwhole23PASS
2026-10-06T01:16:13–18UTC, conocido50Management; eso no ejecuta este probe.

## Qué conserva

- Misma CLI explícita `--probe-isolated-delay`; default sin env/transporte.
-1ownednonrobustconnection/1canalconfirmado,2server-namedexclusive/autoDelete/noDurable,
  queueTTL30000/defaultDLXDestination propio/xExpires60000. Ningún recurso business.
-2GET únicos antes de publicar, misma auth/target, metadataguards fuertes: counts
  int0/exclusive/noDurable/autoDelete/typeclassic/argumentos/policy reales exactos.
  Missing/stale/unknown después de6s→**STOP sin publicar**, no convertirlo en0,
  relajar shape, retry/fallback o loop de sondeos.
-1mandatorynonce≤64B/wireexpiry5000 via timedelta;3gets ownDestination máximo,
  ACKlocal1 solo nonce/x-deathoriginalexpiry propios,≤2conditionaldelete propios.
- T0 del publish empieza **después** de espera6 y de ambas metadata válidas:
  early4s/deadline0.5 debe cerrar<5;late8s/deadline2 cierra≤10; último get postACK.
  Contadores no cambian y elapsed original incluye +6s; wrapperload/overhead se
  acota por harddeadline y Root conserva tiempo de pared de la operación aparte.
- WorkTOTAL60,cleanupTOTAL5,hard80/exec95/remoto150/root130+grupo5/total≤300s,
  sin ampliar presupuestos. La espera consume el work existente, no añade otro60.
- Brokerpassed/resourceDeleted/TCPcleanup permanecen separados; familias cerradas,
  desconocidos=null, remotecloseFalse, actualworker352/durability/noLoss/ingress/
  pilotadmissionFalse siempre. Sin business/Meli/Mongo/Full/config/policychanges.

**No hay garantía de que6s basten.** La disponibilidad inmediata de campos no se
acreditó. El intervalo default mencionado por Root no demuestra configuración ni
frescura actual del broker. Espera fija no es permiso de otra lectura si los dos
GET fallan; respetar primer STOP y guardar evidencia. No repetir cleanup anterior.

## Cuatro paths únicos y preservación

Privado0700:
`$HOME/.codex/cache/zelerdata-integracion-20261005-8dafff186997/amqp-isolated-delay-probe-settled-20261006`.

1. `<privado>/probe_settled.py` — wrapper de una sola inserción verificada.
2. `<privado>/probe_supervisor.py` — copia original, solo sourcebindings nuevos.
3. `<privado>/test_probe_settled.py` — siete casos wrapper/timing y tres supervisor.
4. `docs/sheets/zelerdata-historico-amqp-probe-asentado-informe.md` — este informe.

Fuentes0600/logs+recibos nuevosO_EXCL soloDIR nuevo. **36 hashes de nueve deliveries
previos intactos**, además auditoría4110 y ROOT/GREEN385a preservados. Originalprobe
4hashes/24Rootfakes/PASS se conservan; no editar originals/reports/helpers/canon/
central/shared/CUOTAS/config/deps/lockfiles. Sin Git/build/generaltests/producción,
sockets/puertos/DNS real/Docker/Mongo o agentes nuevos.

## RED/GREEN

| Artefacto propio | Evidencia |
| --- | --- |
| RED-original-pre6.log |10casos;4FAIL+5ERROR: fuente original hace primer HTTP antes6, no puede acreditar timing; variante/sup aún no existen. |
| GREEN-1.log |10PASS tras única inserción ybindingsup. |
| ruff-first/fix/formatted y mypy-first |Errores originales de formato/tipos de basefixture preservados; no reducción de checks. |
| final-unittest.log |10PASS/0skip,0.378s; primer/segundoGETafter6 yno publishantesambos, t0early4/late8/elapsed14. |
| final-ruff/final-format/final-mypy |PASS tres fuentes, configuración estándar. |
| source-binding-receipt.json |Una inserciónAST únicamente; sup solo dos sourcebindings;embedding/ASThost3.9/36priorhashesPASS. |
| representative-no-env-stdout.json/stderr.log |stdinCLI sinenvexit2/counters0/JSONcerrado/stderr vacío; sin transporte. |

Fakes/callbacks/MockTransport heredados desde fuente de fixtures originalSHA33a034f6
verificada, sin correr sus24tests otra vez. Casos nuevos≤12 no agregan pruebas de
negocio: missingcounts/caps/TTLafter6 siguenSTOP, unsafeowneranteswait, hash/AST/default/
noenv, receiptpositive/drift/source/unknown/admissionclosed. No nuevo research/librería.

## Hashes finales y entrega

- `probe_settled.py`: `2a17d39d5993053ad86f64fab3981fdebc1ea4581577839d6d9c62d3a37c5b1d`
- `probe_supervisor.py`: `f14a7f72a19b5e94dd0dab4714820a68c1a435bd3caf69fe1972016bbd983e8a`
- `test_probe_settled.py`: `52e102b74400a1248d61444b4e25638845f894717cfcca1a7eec640074cc0db7`

Hash de este informe en `<privado>/delivery-receipt.json` con los cuatro archivos.
ROOT recibe propiedad y conserva única ejecución productiva. **ENTREGADO;
NO SIGO MODIFICANDO.** No resultados productivos ni aceptación global inferidos.
