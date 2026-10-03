# ZelerData: implementación local del histórico al vincular

Cierre local original: 2 de octubre de 2026; actualización Full: 3 de octubre UTC.
Este informe acredita desarrollo local y pruebas
aisladas, **no despliegue ni aceptación productiva**, y no convierte una fuente
pendiente en completa. Fuente actual publicada/verificada:
**`d78ff4e57915ca5e81a5eb6f1976ec65f111824b`**, tree
`54d96092dce1358579989c45d973bd6969f1a4d7` idéntico al staged validado, remoto
confirmado/worktree limpio al publicar. Tres builds nuevos SUCCESS/procedencia
verificados, [recibo/destinos concretos](zelerdata-historico-builds-runtime-20261003.md#publicación-d78-y-tres-builds-verificados),
**sin pull/deploy/piloto**. La fuente anterior de corrección
Full C3 `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d`, C1/C2 y su evidencia original se
conservan como historial. Su ejecución e identidad se registran en el
[recibo de publicación](zelerdata-historico-publicacion-20261002.md).
Este cierre documental se publica por separado; su identidad se consulta en Git
y no cambia el código de la fuente d78. Nueva C propuesta requiere permiso aún no recibido.

Referencia de aceptación:
[especificación](zelerdata-historico-al-vincular-especificacion.md).

## Estado de los cuatro cierres solicitados

| Clasificación | Resultado |
| --- | --- |
| **Completado localmente** | Mensaje nuevo de orden antigua sin cambios: recuperación periódica real; tabla de 9,999 órdenes adquiridas + 1 pendiente mediante API autenticada normal; capacidad compartida de dos fuentes no vacías y certificados de 1,000 membresías. |
| **Bloqueado por evidencia externa concreta** | Mapeo positivo RETIROS Full: no se acredita aún jerarquía retiro/bulto, cantidad originalmente solicitada ni fecha de solicitud. Investigación pública cerrada; descubrimiento posterior y [una reanudación autorizada](zelerdata-full-validacion-acotada.md#4-una-reanudación-preparada--siete-restantes-sin-ejecutar) detenidos por 429: 7/10 GET acumulados sin referencia; tres sin usar no autorizan continuar. |
| **Pendiente de aceptación productiva bajo goal autorizado** | Controles locales y ensayo real completo normal/deadline/guard pasados. Único C del goal falló antes del dump; respaldo consistente/restore inexistentes y no segundo C permitido. Full pytest sin cierre verde. Sheet privada owner-only creada con0 fórmulas; d78 publicado/tres builds verificados, deploy, OAuth, parcialAPI/nativa y dos cambios reales pendientes. |

[Propuesta de publicación/piloto con respaldo y rollback](zelerdata-historico-publicacion-piloto-propuesta.md).
Las tres categorías no se intercambian: una fuente bloqueada no impide los datos
útiles de las demás; una prueba local no demuestra despliegue ni aceptación real.

## Lectura rápida

- OAuth admite una intención durable antes de omitir un bootstrap ya completado.
  Relink no usa `force` para reiniciar el histórico ni reemplaza sus checkpoints.
- La ejecución se activa por separado con `ZELERDATA_HISTORY_ON_LINK_ENABLED`.
  Dentro de esa activación, las cuentas elegibles usan una política persistida,
  sin prompts por mes y sin una lista fija de vendedores piloto.
- Hay progreso independiente por fuente, presupuestos, leases, checkpoints,
  parciales identificados y mantenimiento incremental. Packs conocidos antiguos
  reciben una recuperación periódica acotada aunque la orden no cambie. La cobertura exacta se
  comprueba por sus lectores/certificados; el estado del plan no la sustituye.
- **Retiros Full sigue pendiente de cerrar su contrato de fuente**. Se implementa
  adquisición auténtica de operaciones, pero no se convierten operaciones de
  stock en filas de RETIROS inventando identidades o cantidades solicitadas.
- Goal autoriza completar el circuito real condicionado al ensayo de pausa y
  respaldo consistente. No acredita ejecución: OAuth, lectura nativa/parcialAPI
  y dos actualizaciones reales siguen pendientes de evidencia.

## Preparación de aceptación del goal: OAuth, API normal y Sheets nativo

**Estado actualizado:** controles validados/publicados en d78 y tres builds
verificados; sin pull/deploy/piloto. La identidad del cierre documental separado
se consulta en Git y no cambia código d78. El último C comprobado falló; no ejecutar el piloto antes de cerrar
respaldo/restore y controles de ejecución/admisión. No adaptar el complemento ni
repetir la matriz general de53funciones: usar muestra de las fuentes del goal.

### Controles locales y evidencias actuales; no aceptación productiva

| Evidencia | Resultado y límite |
| --- | --- |
| Admisión/ejecución | Hold de admisión histórica en gateway, claim de vendedor y ejecución acotada con deadline, presupuesto físico persistido y pausa; conservar autoridad, cutoff/consumed/checkpoints. Forward recovery mantiene admisión cerrada/ejecución pausada y worker consciente de autoridad; no sustituirlo por legacy ni resetear datos. |
| Contrato objetivo nuevo | **14 scopes = 13 baseline compatible + `GET /messages/packs/*`; ningún scope Full**, seis routing keys; fingerprint `453bf9eb6014d8055fe6cd372e98b1e2d0190a0241b519417fe5f5397e2c1525`. Manifest/seed/verificador deben coincidir con imagen nueva, no C3/15. SHA fuente d78 publicado y tres builds verificados; sin despliegue. Verificador14 no acredita compatibilidad C1 ni habilita rollback clásico. |
| Checks locales comunicados | Lote74passed/27.76s:12cert×1000/dos workers/cuatro renovaciones/spacing estricto. Capacidad anual3passed/52.16s tras último patch. Finales Ruff/format/mypy651/direct-Meli/schema-export verdes; staged-gitleaks limpio. No sumar lotes ni afirmar rootgate general verde: fragmento2860 tuvo13fail/2838pass/9skip y se clasificó abajo. |
| Transporte/pacing corregido localmente | RED previo: prueba compartida falló spacing(15.96s), porque awaitMongo entre pacing y RPC agrupaba envíos. Ahora fetch/request/claims: reserva/cobro durable + validación persistida → pacingúnico → guard síncrono UTCdeadline/día → RPC, **sin awaitMongo entre pacer/send**. Gateway mantiene guard persistido tardío tras broker/KMS. Si vence mientras espera: consumed1 conservador, HTTP0; no refund ni reset. |
| Ensayo real de pausa normal | Ensayo fresh5: pausa de tres actores sin auto-restart, reanudación de tres y guard complete **pasados**. Helper congelado acepta finalizaciónAPI solo con logs complete del PID/generación; sin RPC stop pendientes. |
| Ensayo real de recuperación | Run5 **completo pasado**, Docker29.4.1: normal + deadline + guard, job fence1/attempt1/lease y Rabbit unacked1→recuperación. No equivale a backup consistente ni restore. |
| Único C del goal | Inicio21:09:57.466075 UTC; `command_failed` antes de dump/writers_stopped. Parser del helper en hostPython3.10 rechazó RFC3339Nano Docker; sentinelsAPI reales de cierre ordenado sí presentes. API/dispatcher recuperados; ningún segundo C permitido automáticamente. [Recibo exacto](zelerdata-historico-builds-runtime-20261003.md#único-c-del-goal-fallido-antes-del-dump). |
| Fix local posterior | Parser de nanosegundos exactos/Python3.10: 37+6 pruebas verdes, helper SHA prefijo30ecbeb. HostPython3.10 verificado read-only alrededor de21:12: proofTRUE con timestamps auténticos, `fixed-parser-host310.jsonl`; estáticos finales verdes. Sin otro ensayo/corte. |
| Readiness origen final | Lectura21:38:58→21:39:05 UTC: gateway/API/worker/dispatcher HTTP200/ready/healthy/restart0/OOMfalse/digests anteriores intactos, baseline13/seis keys/siete clientes exactos/sinFull. Flags seleccionados gateway/worker unset; no hold desplegado ni piloto activo. Capacidad/colas y preflightdry-run sinpull en recibo. Salud no acredita histórico ni fórmulas. |
| Cierre/limpieza | Abandono autorizado: VM/disco temporales eliminados por identidad/listas vacías/evidencia fuera antes; Mongo/perfil locales propios detenidos/limpiados. Sin archivos de negocio/GCS/restore; registros y guard recovery completos. Capacidad/colas finales en [recibo](zelerdata-historico-builds-runtime-20261003.md#runtime-final-fresco-imágenes-anteriores-sanas-sin-activación). |
| Sheet privada creada, inactiva | [Hoja TEMP nativa](https://docs.google.com/spreadsheets/d/1IzBEJ6fTs3-juTvWYv0P9dK_0gMpS5jo5y18KlsmitU/edit?ouid=110356598393864429185), ocho pestañas/0 fórmulas; propietario único coincide con perfilGoogle Zeler110356598393864429185. Alias del conector no sustituye identidad real verificada. Sin llamadas por customfunction; activar solo durante piloto. |

La evidencia privada de creación es `private-sheet-preparation.json` del directorio
operativo local `c-goal`; no almacenar credenciales ni datos productivos en este
informe. El complemento no ganó `allow_partial`: su consumo sigue exclusivamente
por API normal autenticada, separado de estas fórmulas existentes.

**Clasificación final previa a publicación, sin suite general verde:** fragmento
postOOM2860nodes:13failed/2838passed/9skipped en259.20s. Una regresión propia era
verificador15 frente a manifest14; corregidos únicamente `infra/deploy/sheets_rollback.py`
y `tests/test_deployment_preflight.py`, 35pruebas puras helper/provenance verdes0.24s.
Los otros12fallos son **preexistentes verificados** sobre HEAD13972ec:12failed/2.20s,
mismas funcionesAST y tres scripts byteidénticos, macOS `/bin/bash`3.2.57/BSDstat
(`read -t0.01`, `stat -c`, array vacío/nounset). No hay Bash5 instalado ni pruebaLinux
que los cierre; no ampliar este trabajo para corregirlos. Los ocho tests protegidos
stockrs0 **8passed/2.20s**, MONGOambiental unset y ZELER_RS0_TEST_URI literal
verificado propio27030/rs0; ya no quedan skipsMongo de ese guard. Rootgate sigue
no verde por12baselineMac; quedan8skipsbroker y1Caddy, no pruebaLinux. Evidencia
baseline privada en `cache/checks/shell-baseline-verification.json` y
`shell-baseline-pytest-baseline.log`. Preservar fragmentos
válidos sin repetirlos ni sumar lotes superpuestos.

### Checklist ejecutable por operador; resultado aún pendiente

| Evidencia requerida | Procedimiento y criterio; no basta200 |
| --- | --- |
| Disparador real | Sesión legítima de app + MercadoLibreHOPEMOB → callback aceptado → intención/plan durable conservando cutoff/consumed/checkpoints → adquisición/publicación → lector. No insertar plan para sustituir OAuth. |
| Alcance real | Claim82453304, cinco fuentes/Full0, inicial800/150/250/300/500 y mantenimiento500(≤300/fuente), total≤2,500GET físicos/90min mismo díaUTC. Contar retries/intentos causados por fórmulas/recovery, separando tráfico habitual. |
| Continuidad | Reanudar el mismo estado/leases/autoridad, sin duplicar receipts/jobs ni reabrir año; comparar hashes/counters antes/después y otros sellers intactos. |
| Períodos independientes | DEVOLUCIONESjunio y otro período realmente cubierto/certificado siguen legibles independientemente; rango sano y pruebas anteriores no se sustituyen. |
| Parcial API normal | Rango realmente pendiente: ORDENES opt-in booleantrue devuelve filas utilizables + avisoPARCIAL, coverageexactfalse/acquired_rows_only y pendiente conservado. Default y totales afectados permanecen cerrados; no fabricar9999/1 productivo. |
| Nativo exacto | Una hoja nueva privada, wrappers ya instalados/autorizados; fórmula y effectiveValue real, sin errores/PROCESSING persistente. Período afectado muestra no disponible, no parcial nativo. |
| Mantenimiento | Packs antiguos conocidos con orden sin cambio; dos eventos/cambios reales posteriores a cutoff: detección→persistencia→lector. Si faltan eventos, registrar pendiente, no dos ciclos vacíos ni transacciones ficticias. |
| Cierre | Prueba de restauración/joins/lectores, estado seguro de admisión/ejecución, recursos temporales limpiados conforme al goal y evidencia privada preservada. Ninguno acreditado por health/repo/tests solamente. |

### Intervención humana indispensable: disparador y Google propietario

1. Cuando el operador confirme gates/presupuesto, abrir **https://app.zeler.ai/**
   con la sesión propia legítima y pulsar **Connect MercadoLibre** del dashboard.
   Completar consentimiento normal con la cuenta **HOPEMOB82453304** y volver al
   producto. No confirmar otra cuenta, modificarquery/platform_user_id, usarforce,
   copiar OAuthcodes/tokens ni revocar para hacer aparecer un botón.
2. `/accounts` sirve para verificar HOPEMOBlinked; **Re-link solo aparece si revoked**.
   Para activa, dashboard genera el enlace normal desde el userID autenticado.
   Login/consent/2FA del proveedor, si aparecen, los realiza el usuario; no suplantar.
3. El usuario eligió **Cuenta Zeler**; perfil real y permisos owner-only ya
   comprobados para la hojaTEMP. Reutilizar esa conexión autenticada y ese Google
   usuario; la conexiónDrive no demuestra AppsScript autorizado.
4. En la hoja privada confirmar **ZelerData → Settings**, APIdefault
   `https://sheets.zeler.ai`, token existente autorizado para HOPEMOB en
   **UserProperties de ese Google usuario**. Si falta instalación/menú/token,
   intervención del operador por la ruta existente de `/sheets/config`; no crear,
   rotar/revocar credenciales ni publicar AppsScript/Marketplace como atajo.

**Tres auth distintas:** MercadoLibrelink dispara histórico; FormulaAPI valida
bearer de extensión/cuenta; OAuthGoogle del worker escribe Sheets por
GoogleTokenStore. Leer fórmula o usar conexiónDrive no demuestra renovación del
writer. `GET /oauth/google/authorize` **crea google_oauth_state y pideconsent**:
no usar `seller_id=test`/curl como inspección read-only ni modificar OAuth del goal.

### API normal: preparado para cliente legítimo; no ejecutado

Endpoint `POST https://sheets.zeler.ai/sheets/formulas:execute`; usar **cliente
ya autenticado con bearer de extensión** limitado a HOPEMOB, no module_admin ni
minting bypass. El snippet recibe el cliente ya autorizado: no obtiene/imprime
credenciales, no retries y devuelve solo resumen/hash, no compradores/cuerpos.
Fechas deben ser rango realmente pendiente o sano identificado por el operador,
no ampliar recuperación para fabricar prueba; toda adquisición inducida se mide.

```python
import hashlib
import json
import uuid


def comprobar_parcial_api(client, cuenta, desde, hasta):
    # client ya autenticado por flujo normal; jamás copiar OAuth ni loguear headers.
    args = {"fecha_inicial": desde, "fecha_final": hasta, "estado": "todos"}
    cases = [("default", "ZELERDATA_ORDENES", False),
             ("parcial", "ZELERDATA_ORDENES", True),
             ("total", "ZELERDATA_VENTASTOTALES", False)]
    out = []
    for name, formula, partial in cases:
        payload = {"formula": formula, "cuenta": cuenta, "args": args,
                   "request_id": str(uuid.uuid4())}
        if partial:
            payload["allow_partial"] = True  # boolean, no string ni _allow_partial
        response = client.post("/sheets/formulas:execute", json=payload)
        body = response.json()
        values = body.get("values", [])
        meta = body.get("meta", {})
        notice = any(isinstance(row, list) and row and
                     isinstance(row[0], str) and row[0].startswith("PARCIAL")
                     for row in values)
        out.append({"case": name, "http": response.status_code,
                    "ok": body.get("ok"), "error": body.get("error", {}).get("code"),
                    "orders_count": meta.get("orders_count"), "notice": notice,
                    "coverage": meta.get("coverage"),
                    "values_sha256": hashlib.sha256(json.dumps(
                        values, sort_keys=True, default=str).encode()).hexdigest()})
        if response.status_code in (401, 403, 429) or response.status_code >= 500:
            break  # no retry ni expansión; conservar evidencia de fallo
    return out
```

Resumen se conserva privado; publicar solo campos sanitizados aprobados de
coverage(rango/exact/scope/motivo), nunca body/headers. No exigir9999filas real:
ese caso ya está demostrado localmente en `test_partial_history_api.py`; producción
necesita un parcial real útil. Exacttrue en rango sano no demuestra parcial;
PROCESSING/DATA_UNAVAILABLE sin filas no satisface el opt-in. No insertar pendientes.

### Hoja privada: herramientas disponibles, no sesión ni add-on comprobados

No se encontró `gws`/`clasp` en PATH. Sí hay herramientas nativas de conexiónDrive:
`get_profile`→`import_spreadsheet`(xlsx, `native_google_sheets`)→metadata/permisos→`batch_update_spreadsheet`
con formulaValue→`get_spreadsheet_cells`(userEnteredValue/effectiveValue).
Así se puede preparar/escribir/leer sin browser ni copiar OAuth; **no permite
instalar/autorizar add-on ni demostrar que customfunction corre en ese usuario**.
No crear otra UI, script vinculado, fórmula nueva ni versiónMarketplace.

Preparación ya realizada: ArtifactTool generó el xlsx local inactivo; se importó
**una** hojaTEMP nativa bajo Cuenta Zeler y se comprobaron permisos owner-only.
Ocho tabs: Control y siete salidas independientes, sin fórmulas activas; fuera del
placeholderA1 las salidas quedan vacías para no bloquear spill. Antes de activar,
revalidar perfil/permisos y leer `sheetId` de metadata; no crear otra hoja.
Escribir únicamente A1 de cada tab con updateCells/fields:userEnteredValue,
`include_spreadsheet_in_response:false`; no tocar hojas preexistentes.

```json
{"updateCells":{"start":{"sheetId":123,"rowIndex":0,"columnIndex":0},
 "rows":[{"values":[{"userEnteredValue":{"formulaValue":
 "=ZELERDATA_ORDENES(\"HOPEMOB\",\"<DESDE_SANO>\",\"<HASTA_SANO>\",\"todos\",\"\",\"si\")"}}]}],
 "fields":"userEnteredValue"}}
```

`123`/fechas son placeholders: reemplazar por tab recién creada y rango cubierto,
respetando locale/separador real. Leer solo rangos acotados de la hojaTEMP y
emitir counts/errores/hashes sanitizados; no PII. No interpretar write200 como
recalc. Leer como máximo A1:D4 por cada una de las siete salidas: **28 filas en
total**, no todos los resultados. Espera/relectura limitada por piloto; sin polling indefinido.

| Tab / fórmula existente A1 | Qué demostrar |
| --- | --- |
| OrdenesSanas: `ZELERDATA_ORDENES("HOPEMOB",desde,hasta,"todos","","si")` | Filas reales y comisión/costoNA cuando falta; rango sano mantiene prueba. |
| OrdenesPendientes y TotalPendiente: ORDENES(default)/`ZELERDATA_VENTASTOTALES("HOPEMOB",desde,hasta,"todos")` | No vendidas como exactas ni parcial nativo; DATA_UNAVAILABLE esperado en rango pendiente. |
| Preguntas: `ZELERDATA_PREGUNTAS("HOPEMOB",desde,hasta,"00:00","23:59","si")` | Preguntas/respuestas realmente cubiertas. |
| DevolucionesJunio y DevolucionesOtro: `ZELERDATA_DEVOLUCIONES("HOPEMOB",desde,hasta,"todos","si")` | Períodos independientes, junio preservado. |
| CostoEnvio: `ZELERDATA_COSTOENVIOVENDEDOR("HOPEMOB",skuReal,itemReal)` | Costo vigente/NA verificable, no afirmar histórico anual por ese valor. |

No hay wrapper nativo MENSAJES/RECLAMOS separado: no inventarlo. Mensajes/packs
se validan con adquisición/publicación/lector existente, DEVOLUCIONES cubre su
propia tabla de reclamos de devolución. `#NAME?`, TOKEN_MISSING/REVOKED,
SELLER_FORBIDDEN o consent faltante se reportan como bloqueo real; no mockear ni
pegar datos de API en celdas como supuesto resultado de customfunction.

Referencias: [source add-on](../../modules/sheets/apps_script/sheetseller/README.md),
[wrappers](../../modules/sheets/apps_script/sheetseller/Formulas.gs),
[publicación Marketplace](zelerdata-marketplace-publication.md),
[fórmulas](zelerdata-formulas.md),
[API parcial local](../../modules/sheets/tests/test_partial_history_api.py).

## Qué se integra y qué no se promete

| Fuente | Camino local | Límite de interpretación |
| --- | --- | --- |
| Órdenes/comisiones | Plan fijo, jobs históricos y escritores existentes; fallback parcial por identidad. | `sale_fee` no es facturación. Un rango sin prueba no es un total exacto; canceladas nunca enumerables no quedan certificadas. |
| Preguntas/respuestas | Adquisición histórica y escritor canónico; respuesta incompleta queda pendiente. | No inventar respuesta ni KPI por un estado `ANSWERED` insuficiente. |
| Envíos/costos | Dependencias deduplicadas de órdenes adquiridas. | Orden ausente o costo ausente afecta su dependencia; costo desconocido no es cero. |
| Reclamos/devoluciones | Autoridad de onboarding sobre runs exactos existentes, ventanas acotadas y mantenimiento. | Certificados conjuntos siguen fail-closed; otro período no invalida uno independiente ya sano. |
| Mensajes | Enumeración por packs, paginación, checkpoints y modelo canónico. | Solo lectura con `mark_as_read=false`; no enviar, responder ni marcar leído. |
| Full | Operaciones reales por vendedor/fechas y scroll, con progreso separado. | No certifica el contrato de RETIROS mientras falte el mapeo auténtico requerido. |

No se agregan visitas, facturación, liquidaciones, nuevas fórmulas, otro frontend,
reconstrucción retroactiva de snapshots ni adquisiciones productivas implícitas.

## Autoridad, disponibilidad y visibilidad

La política conserva vendedor, versión, corte, intervalo, fuentes y presupuesto.
Cada intento remoto se cobra antes del envío. La adquisición comprueba identidad,
pertenencia, elegibilidad y ámbito; una revocación no permite seguir usando el
plan como una autorización independiente de la cuenta.

Orden de transporte del fix actual: **reserva/cobro durable y validación persistida
→ pacing único → guard síncrono de deadline/día UTC → RPC**, sin awaitMongo entre
pacer y envío. El gateway conserva la comprobación persistida tardía después de
broker/KMS. No pacear antes del cobro: puede agrupar RPC tras esperas de Mongo.
Reserva expirada durante pacing conserva consumed1 pero hace HTTP0; no reembolsar
ni reiniciar cuotas. [Lecciones L-029/L-030](../lessons/README.md) registran parserNano
host y orden de transporte; tests locales no acreditan despliegue.

La carga inicial conserva su presupuesto y corte originales. El mantenimiento
usa una política diaria aparte; renovar esa cuota no reinicia jobs anuales.
Onboarding y recovery existente comparten el pacer de adquisición. Los jobs
admitidos por la política llevan una autoridad que los workers legacy excluyen:
compartir colas no autoriza ejecutarlos por otra ruta ni eludir su contabilidad.
Los jobs legacy previos pueden drenar bajo su autoridad anterior, sin takeover.

Los estados y observaciones se exponen mediante la ruta autenticada existente
`GET /sheets/backfill/progress?seller_id=...`. La respuesta añade estado de
onboarding, fuentes, presupuesto e intervalo solicitado. Su `exact_coverage=false`
declara que este resumen no certifica toda la incorporación. La aplicación y
Apps Script no deben inferir exactitud del estado agregado ni de un conteo de filas.

Un fallo de detalle puede producir filas canónicas útiles y un pendiente durable.
El lector exacto sigue rechazando el intervalo afectado sin su prueba. No se
cambia silenciosamente el contrato de tablas/agrupaciones ni se presenta una suma
parcial como total. Esta entrega no demuestra consumo parcial nativo en Sheets.

### Consulta real de los parciales mediante el API normal

La petición autenticada a `POST /sheets/formulas:execute` admite opt-in estricto
`allow_partial: true` **solo para `ZELERDATA_ORDENES`**. Reutiliza el handler,
proyección y autorización por cuenta actuales; no añade otra fórmula/frontend.

```json
{
  "formula": "ZELERDATA_ORDENES",
  "cuenta": "PILOT",
  "allow_partial": true,
  "args": {"fecha_inicial": "2026-06-01", "fecha_final": "2026-06-30"}
}
```

Ejemplo de contrato, no ejecución ni datos de una cuenta real. La prueba
[API parcial](../../modules/sheets/tests/test_partial_history_api.py) adquiere
10,000 identidades con validadores reales y un detalle fallido. Consulta el
endpoint con token normal de extensión, limitado a la cuenta del fixture:
**9,999 líneas reales**, cantidad/precio/comisión, costos ausentes `NA`, más una
fila de aviso `PARCIAL` del ancho de la tabla. `meta.coverage` indica `exact=false`,
`scope=acquired_rows_only`, rango y motivo; pendiente desconocido queda `null`,
no cero inventado. Aviso visible aunque un consumidor descarte metadatos.

Default y `ZELERDATA_VENTASTOTALES` afectados siguen `DATA_UNAVAILABLE`; pedir
opt-in para un agregado devuelve `BAD_ARGUMENT`. Un argumento interno falsificado
no habilita parciales; token ajeno/inválido no consulta los datos. Rango sano
independiente permanece legible y su certificado intacto. Incluso vacío sin
prueba devuelve aviso, no el significado falso de "cero ventas". Con prueba válida,
el opt-in conserva el resultado exacto existente.

**Límite:** no se modificó la firma del add-on; no solicita este opt-in. Esta
entrega demuestra API normal, no consumo parcial nativo ni nueva UI de Sheets.

### Mensajes antiguos: continuidad acotada y reinicio

La [prueba de coordinador](../../modules/sheets/tests/test_history_old_messages.py)
cubre una orden de 200 días sin cambios, con mensaje posterior al cutoff. Se
recupera por pack conocido, no por selección exclusiva de órdenes recientes.
Cursor separado `message_periodic_recovery`, batches de **40 packs** deduplicados,
**dos páginas máximas por turno**, alternancia con el histórico inicial y cuota
incremental/pacer/lease comunes. No se reinician ni reemplazan jobs anuales.

Cada sweep congela fin y filtra por creación **del mensaje**: primer intervalo
cutoff−5 minutos→inicio del sweep; posteriores solapan cinco minutos. Terminado
el sweep, espera al menos 15 minutos. Offset/cursor reanudan; agotar cuota tras
una página exitosa conserva ese avance para el siguiente día, en lugar de repetir
eternamente la primera página. CAS impide publicar checkpoint bajo lease reemplazado.
Progreso sanitizado aparece en `/sheets/backfill/progress`, sin IDs ni texto.

La API de packs no acredita orden incremental/filtrado remoto por fecha. Visitar
un pack puede requerir páginas antiguas; no se afirma catch-up de una llamada,
latencia fija ni descubrimiento de packs desconocidos. La carga está acotada por
turno/cuota y no vuelve a admitir el año; el volumen anual remoto sigue por medir.

El piloto dispone de scope opcional `ZELERDATA_HISTORY_ON_LINK_SELLERS`: restringe
el **claim real**, antes de renovación/adquisición. Ausente conserva producto
multicuenta normal; lista explícita vacía/wildcard/ID no canónico falla startup.
[Test de scope](../../modules/sheets/tests/test_history_pilot_scope.py) confirma que
otra cuenta/plan queda completamente intacta. El allowlist de recovery ajeno no
se usa como prueba de este límite.

### Full: evidencia y bloqueo preciso

La documentación oficial consultada el 2 de octubre de 2026 describe
`/stock/fulfillment/operations/search`, rango máximo de 60 días, páginas de hasta
1000 operaciones y scroll de cinco minutos, terminado por `scroll=null`. La
fecha final de consulta excluye ese día. Distingue reserva/cancelación de retiro
físico y de descarte/remoción.
[Fuente oficial](https://developers.mercadolibre.com.mx/es_mx/envios-fulfillment).

Ese contrato público no demuestra todos los identificadores/detalles y la
cantidad solicitada exigidos por el contrato actual de RETIROS. No se deduce de
ello que ningún recurso legítimo pueda proporcionarlos: queda por acreditar el
recurso/mapeo compatible. Mientras tanto, no se fabrica `withdrawal_id`, no se
usa el ID de operación como si fuera el de retiro, no se rellena una cantidad
desconocida y no se publica cobertura de `sheets_full_withdrawals`.

La [protección normal](../../modules/sheets/tests/test_full_onboarding_handler.py)
prueba colector real→operaciones en Mongo→dispatcher/handler RETIROS/lector normal:
**dos casos** rechazan rango no certificado, incluso con delta y referencia
candidata sintética. Es prueba negativa de protección, **no mapeo positivo**.
Faltan evidencia real de campos/semántica y un retiro conocido para contrastarlos;
la [propuesta exacta](zelerdata-full-validacion-acotada.md) fija presupuesto/rutas,
plazo y criterio de parada. No se copió la derivación legacy por siete dígitos ni
se abrió facturación fuera del alcance.

Un 403 es restricción de acceso, no evidencia de "no aplica". Una enumeración
vacía tampoco prueba que el vendedor carezca de Full. Se conservan datos legacy
y su procedencia; no se los reetiqueta como adquiridos por API.

### Contratos de fuente y horizonte

Consulta de referencias oficiales: 2 de octubre de 2026, mediante contenido
indexado; algunos accesos directos devolvieron 403. No fue una consulta autenticada
de API ni comprobación de permisos del vendedor. El corte se guarda en UTC y la
resta es de meses calendario, no de 365 días; el filtro de cada fuente se adapta
sin confundir límites de consulta con retención.

| Fuente y referencia oficial | Contrato usado / límite que debe seguir visible |
| --- | --- |
| [Órdenes](https://developers.mercadolibre.com.mx/gestiona-ventas), actualización 21/09/2026 | Búsqueda por creación/modificación y detalle; horizonte documentado de 12 meses. El buscador de vendedor puede omitir canceladas; conocer una cancelada y revalidarla no prueba descubrimiento de todas las desconocidas. |
| [Preguntas](https://developers.mercadolibre.com.mx/en_us/listing-types-item-upgrades-tutorial/manage-questions-and-answers), actualización 15/01/2026 | `api_version=4`, orden por `date_created` ASC/DESC. El incremental verifica monotonicidad antes de detenerse en el borde antiguo. La eliminación de preguntas sin respuesta mayores a siete meses no acredita un horizonte universal para respondidas ni recuperación anual completa. |
| [Mensajes](https://developers.mercadolibre.com.mx/es_ar/manejo-de-pagos/mensajeria-post-venta), actualización 27/04/2026 | `limit/offset`, total y `mark_as_read=false`. No se encontró garantía de orden cronológico, filtro de fecha ni retención anual universal. El incremental limita packs a órdenes recientes/cambiadas; cambios de packs antiguos inactivos sin evento/cambio de orden **no quedan demostrados**. |
| [Reclamos](https://developers.mercadolibre.com.mx/que-es-un-reclamo), actualización 20/08/2026 | Vendedor mediante `players.user_id`/rol; rangos de creación/actualización con milisegundos, `limit≤100` y `offset+limit<10000`. Ventanas densas se subdividen acotadamente; una ventana irreducible queda pendiente, no completa. No se garantiza retención anual universal. |
| [Devoluciones](https://developers.mercadolibre.com.mx/en_us/introduction-services/ml-returns), actualización 25/03/2024 | Detalle `/post-purchase/v2/claims/{id}/returns`, relacionado con reclamos/órdenes. No es una fuente independiente de totalidad anual ni movimientos financieros. |
| Full, referencia anterior | Solicitud máxima de 60 días, partición del coordinador de 59 días. La nota de stock de 12 meses no demuestra retención de operaciones. El contrato completo de RETIROS permanece pendiente. |

Se reutilizan adquiridores de envíos/costos y se valida pertenencia/relación.
El ensayo productivo todavía debe confirmar acceso y datos reales por fuente;
ninguna referencia pública sustituye esa aceptación.

## Evidencia aislada y sus límites

### Capacidad compartida de la continuación histórica C3

[Prueba representativa](../../modules/sheets/tests/test_history_onboarding_shared_capacity.py),
**1 passed, 12.94 s**, Mongo rs0 real y validadores/índices canónicos. Dos
instancias de `HistoryOnboardingWorker.process_once` y pacer compartido, sin
reemplazar scheduler ni llamar colectores directamente como aceptación.

| Medición | Resultado local |
| --- | --- |
| Cuentas / turnos reales | Dos / 168. |
| Certificados poblados | 12 × 1,000 membresías; 12,000 reclamos y 12,000 órdenes. |
| Fuentes no vacías | 2,000 mensajes (pasos de 200) y 50 preguntas (0→20→45→50), adquisición/publicación con workers reales. |
| Intentos físicos | 158; 79 por cuenta, igualdad física/cobro por fuente y total inicial/diario dentro de límites. |
| Adquisición inicial | 3.425 s, proveedor simulado. |
| Pacer compartido | 52.333 s de espera **simulada**, no tiempo HTTP real. |
| Renovación | A 15/30/45/60 minutos, pendientes 12→0 por ciclo; seis certificados/cuenta en el batch, chequeo individual <5 s, vigencia restante >28 minutos. |
| Ciclo de seis turnos, renovación + fuentes | Máximo 0.807 s; ambas fuentes continúan efectuando solicitudes. |
| Mongo vivo concurrente | 707 operaciones, latencia máxima 38.6 ms. |

El lector normal de proof valida 1,000 reclamos/órdenes por certificado y
conserva membresía/hash; renovar no certifica actualización remota. Preguntas y
mensajes no vacíos comparten coordinador con las renovaciones. Órdenes/reclamos
están en backoff de fixture y Full usa respuesta vacía: **no** benchmark remoto
anual de esas adquisiciones, Mongo RSS, HTTP/broker vivo ni Sheets nativo. Esto
cierra capacidad **representativa local**, no perfección ni SLA.

### Capacidad de la primera entrega

[Prueba ejecutable](../../modules/sheets/tests/test_history_onboarding_capacity.py):
Mongo real, replica set desechable, validadores/índices de mensajes y certificados.

| Medición | Resultado local |
| --- | --- |
| Mensajes anuales | 20,000; 10,000 por vendedor, dos vendedores. |
| Llamadas de fuente | 400; límite físico de 200 por cuenta. |
| Adquisición | 39.642 s; backlog 20,000 → 0, publicación progresiva y checkpoint persistido/readback. |
| Memoria Python | Máximo 659,154 bytes con `tracemalloc`; no es RSS de Mongo. |
| Trabajo Mongo concurrente | 3,156 operaciones; latencia máxima observada 0.0108 s. |
| Certificados anuales | 74; 37 por cuenta, 74 reclamos y 74 órdenes relacionadas, no vacíos. |
| Renovación | Scheduler real, minutos 15/30/45/60 con reloj controlado; pendientes 74 → 0 por ciclo. |
| Verificación local | Lote de dos cuentas máximo 0.417 s; memoria Python máxima 325,090 bytes. |
| Justicia | Las seis fuentes reciben turnos para ambas cuentas aunque una adquisición simulada falle. |

Comando de capacidad: `uv run pytest modules/sheets/tests/test_history_onboarding_capacity.py -s`:
**3 passed, 44.03 s**. Medición adicional de renovación: **1 passed, 2 deselected,
4.82 s**. Estos tiempos son mediciones, no SLA.

La carga de mensajes usa un harness round-robin y la renovación usa scheduler
real con adquisición simulada fallida. **No** demuestra adquisición remota anual
de 10,000 órdenes/reclamos, tráfico vivo HTTP/Meli/broker, memoria Mongo,
ausencia universal de hambre ni fórmulas nativas. T-22 tiene evidencia relevante,
pero su aceptación integral por todas las fuentes permanece pendiente.

### Backup/restauración local

Se comprobó `mongodump`/`mongorestore` de un fixture quiescente en bases
desechables distintas: **10,000 filas, ocho colecciones, 16 índices**, igualdad de
hashes de BSON canónico antes/después y conservación en el origen de un hecho
posterior y un sentinel de versión de cuenta. Archivo comprimido de 48,496 bytes,
permisos `0600`, eliminado después del ensayo; dump/restauración 0.501 s.

Esto verifica transporte/integridad de un respaldo sintético aislado. No acredita
consistencia entre colecciones productivas con writers concurrentes, restauración
de todos los nuevos contratos ni rollback de tokens/datos reales. Nunca se
restauró sobre el origen ni sobre producción.

### Controles finales de esta continuación

Código/configuración/tests congelados: **36 archivos**, hashes estables durante
la suite; documentos actualizados aparte. Mismo destino desechable explícito,
Mongo rs0 PRIMARY/sesiones, Rabbit loopback, Linux Python 3.11/Node18/`--init`,
checkout solo lectura y caches fuera del checkout; aceptación secuencial, sin OOM.

| Control | Resultado final |
| --- | --- |
| `uv run pytest` completo, sin exclusiones | **5,808 passed, 9 skipped, 402.77 s**; cero fallos. |
| Ocho tests protegidos stock-time, `MONGO_URI` ausente y rs0 explícito | **8 passed, 0 skipped, 2.10 s**; adquisición, commit/abort y rollback con Mongo real. |
| Ruff | Aprobado. |
| Format | Aprobado; 643 archivos. |
| Mypy completo | Aprobado; 643 archivos, no selección reducida de CI. |
| Direct Meli lint y schema export `--check` | Aprobados. |
| Cinco controles estáticos nativos macOS | Aprobados sobre el mismo snapshot final. |
| Diff check, enlaces locales de los tres reportes y preservación de HEAD ajeno | Aprobados. |

Los ocho skips de la suite completa son la protección de URI ambiente y quedaron
cubiertos por la corrida separada. El restante es Caddy sin claves requeridas;
no acredita TLS/ingress real. No se repitió la suite completa nativa de macOS:
las doce incompatibilidades Bash3.2 anteriores siguen documentadas como baseline,
no se modificaron scripts ajenos ni se las ocultó para declarar aceptación.

TDD de los cierres: API normal no permitía parciales antes del cambio; coordinador
no encontraba mensaje de orden antigua; guard de piloto ausente; pérdida de
checkpoint al agotarse cuota a mitad de turno. Se observaron fallos, se corrigió
la causa y se repitieron checks. Capacidad no requería cambio ejecutable de
producto: fixture y aserciones se fortalecieron con ambas fuentes no vacías.
Protección Full ya existía: caracterización negativa, no red artificial ni mapeo.

Cierre de recursos: retirados únicamente los tres contenedores propios de esta
continuación y sus volúmenes desechables; imágenes preexistentes preservadas,
profile dedicado detenido y contexto Docker original `colima` conservado.
Al cerrar las pruebas locales no hubo commit/push, build de imágenes, consulta
autenticada ni mutación productiva. La autorización posterior de publicación y
el intento de búsqueda UI de solo lectura se distinguen en el recibo; no
autorizan builds, API reales ni operación productiva.

### Controles del repositorio — primera entrega

Snapshot final congelado: 30 archivos de código/configuración/tests con hash
estable durante la aceptación; reporte documental separado. Checkout montado
solo lectura en contenedor Linux Python 3.11, Node 18, PID 1 con `--init`, caches
fuera del checkout; **sin build de imágenes**. Mongo rs0 desechable y RabbitMQ
solo loopback, sin credenciales ni datos productivos. Profile de pruebas separado,
default Colima conservado detenido. Al finalizar se retiraron exclusivamente
los cinco contenedores propios y sus volúmenes desechables, se eliminó la imagen
Mongo adicional descargada para este ensayo (sin builds/prune) y se detuvo el
profile de pruebas. Contexto Docker original `colima` conservado; ambos profiles
quedaron detenidos, como al inicio. Las imágenes preexistentes no se retiraron.

| Control final | Resultado |
| --- | --- |
| `uv run pytest` completo, sin exclusiones | **5,777 passed, 9 skipped, 356.62 s**; cero fallos. |
| `uv run ruff check .` | Aprobado. |
| `uv run ruff format --check .` | Aprobado; 638 archivos. |
| `uv run mypy .` | Aprobado; 638 archivos, no solo selección de CI. |
| `uv run python -m infra.lint.check_direct_meli .` | Aprobado. |
| `uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check` | Aprobado. |

Los cinco controles estáticos se repitieron también en macOS sobre el snapshot
final: aprobados. `git diff --check` y enlaces locales del reporte: aprobados.

Ocho skips de la suite completa corresponden a la protección explícita de tests
stock-time contra `MONGO_URI` ambiente. Se ejecutan aparte con URI rs0 loopback y
sin esa variable: **8 passed, 0 skipped** (adquisición, commit/abort transaccional
y rollback con Mongo real, **1.92 s**). El noveno es un contrato Caddy
sin claves requeridas; no acredita TLS/ingress vivo.

Un intento previo de ejecutar dos suites en paralelo agotó memoria del Mongo
desechable (OOM). Se interrumpieron exclusivamente procesos propios: **ese intento
no cuenta como evidencia**. Se recreó la base de pruebas, limitó caché WiredTiger
y corrió aceptación secuencial; Mongo permaneció vivo sin OOM. Un primer Linux
carecía de Node, caches escribibles y PID 1 que recolectara descendientes; se
corrigió el entorno, no se ocultaron tests. Las cuatro regresiones propias de ese
primer gate (fixture OAuth, dos expectativas de scopes y verificador de rollback)
se corrigieron y volvieron a incluirse en la suite completa verde.
El diagnóstico inicial de macOS encontró 12 fallos de wrappers que invocan
`/bin/bash`. Se reprodujeron los mismos 12 contra una exportación inmutable del
commit inicial `84e5df2a46bfc5d8bcbf2f61c6f7a54653f9c9b6` (**148 passed, 12 failed**
en los dos archivos afectados), sin cambiar scripts ajenos. En un contenedor
Linux Python 3.11 preexistente, ambos archivos dieron **160 passed, 3.66 s**.

Reproducción de tests protegidos (con rs0 desechable ya verificado):

```sh
# URI privada de desarrollo/test, explícitamente loopback; nunca producción.
unset MONGO_URI
export ZELER_RS0_TEST_URI='<URI del rs0 local desechable>'
uv run pytest tests/integration/test_stock_time_forward_acquisition_rs0.py \
  tests/integration/test_stock_time_forward_execution_rs0.py \
  tests/integration/test_stock_time_forward_rollback_rs0.py
```

No se resume el resultado como «todos los tests sin skips»: permanece un skip de
contrato Caddy que no tiene claves requeridas.

### Matriz T-01–T-22: dónde se comprueba y qué queda fuera

Pruebas nuevas: [coordinador](../../modules/sheets/tests/test_history_onboarding.py),
[fuentes](../../modules/sheets/tests/test_onboarding_sources.py),
[parciales](../../modules/sheets/tests/test_partial_history.py),
[autoridad DEVOLUCIONES](../../modules/sheets/tests/test_devoluciones_onboarding.py),
[integración DEVOLUCIONES](../../tests/integration/test_devoluciones_onboarding.py),
[capacidad](../../modules/sheets/tests/test_history_onboarding_capacity.py) e
[índices](../../modules/sheets/tests/test_onboarding_indexes.py).

Regresiones reutilizadas: [órdenes](../../modules/sheets/tests/test_history_orders.py),
[preguntas](../../modules/sheets/tests/test_history_questions.py),
[recovery](../../modules/sheets/tests/test_formula_recovery.py) y
[proyección concurrente](../../modules/sheets/tests/test_formula_recovery_history_projection.py).

| Caso | Evidencia local | Límite / pendiente |
| --- | --- | --- |
| T-01 | Coordinador: OAuth/relink admite plan; año automático con workers reales y fuente simulada. | No prueba OAuth remoto ni despliegue del consumidor. |
| T-02 | Coordinador/reclamos: cutoff, progreso, junio y rango nuevo preservados. | Baseline real del vendedor sigue pendiente. |
| T-03 | Mongo concurrente: carrera de admisión, lease único y separación de workers legacy/policy. | El worker antiguo sin esa frontera no es rollback compatible. |
| T-04 | Calendario bisiesto, fin de mes, UTC y rangos ordinarios. | No se realizó revisión visual de zona en UI nativa. |
| T-05 | Recovery histórico: páginas, total cambiante, vacíos, subdivisión; Full scroll repetido/expirado. | Proveedor simulado; volumen anual remoto no acreditado. |
| T-06 | API normal autenticada: 9,999 líneas canónicas útiles + un pendiente, aviso/NA/cobertura explícita; máximo tres intentos. | Opt-in solo tabla ORDENES; rango exacto/totales afectados siguen no disponibles. |
| T-07 | Dependencias/estado agregado no dan disponibilidad si solo hay bloqueos o enumeración desconocida. | No se inventa porcentaje/denominador. |
| T-08 | Recovery existente: listado con detalle 404 y pregunta local omitida revalidada. | Sin prueba de respuestas remotas actuales. |
| T-09 | Cancelada conocida ausente de search, actualización y conservación. | Las desconocidas no enumerables siguen siendo un límite explícito. |
| T-10 | Packs deduplicados, dependencias pendientes y costos ausentes como NA. | No hubo escenario remoto integral orden faltante + envío. |
| T-11 | Pregunta sin respuesta válida permanece pendiente; otra respuesta válida se conserva. | No se fabrica KPI. |
| T-12 | Reinicio por lease/checkpoint, hidratación interrumpida, scroll expirado y CAS tras respuesta tardía. | No se mató el proceso OS exactamente en todas las fases. |
| T-13 | Dos cuentas, checkpoints scoped y hechos recientes protegidos frente a adquisición vieja/ajena. | Sin cuentas productivas. |
| T-14 | Revocación/pausa, 429/503, backoff, límites y relink preservando avance. | Renovación OAuth remota no ejecutada. |
| T-15 | Full: tipos, scroll, permisos/empty no equivalen a no aplica; lector RETIROS permanece cerrado. | **Mapeo auténtico obligatorio pendiente (H-13).** |
| T-16 | Workers reales + Mongo: orden paid → cancelled; preguntas/claims incrementales; mensaje nuevo en orden antigua sin cambios mediante cursor periódico real. | Solo packs conocidos, latencia/volumen remotos no acreditados. |
| T-17 | Certificados/rangos independientes, gap entre períodos rechazado, renovación más allá de dos vigencias. | No se probó un nuevo escenario dedicado de fórmula con certificado expirado; se conserva fail-closed existente. |
| T-18 | Endpoint normal de fórmula con opt-in y 9,999 filas, aviso visible, meta.coverage y default/agregados cerrados; período sano conservado. | Add-on no solicita opt-in; API no prueba consumo nativo. |
| T-19 | Importadores GET/read-only, `mark_as_read=false`, timestamps de lectura conservados. | No operaciones reales de comunicación o tokens. |
| T-20 | Dump/restauración sintética aislada y hashes; origen posterior intacto. | Backup concurrente productivo y rollback de imágenes pendientes. |
| T-21 | Política persistida, cuotas/rangos, autoridad diaria y scope opcional en claim real; otra cuenta/plan intacta. | Aplicación/activación productiva requiere autorización. |
| T-22 | Nueva prueba: coordinador real compartido, preguntas/mensajes no vacíos y 12 certificados×1,000 miembros renovados60min; volumen anterior conservado. | Representativa local; no benchmark anual remoto de todas las fuentes/HTTP/broker/RSS. |

Focused final del escritor: **171 passed, 1 deselected, 20.96 s**. El deselect fue
solo la prueba volumétrica de 10,000 órdenes, ya ejecutada por separado en
**50.92 s** y que vuelve a incluirse en la suite completa final. No se interpreta
esta matriz como 22 pruebas de aceptación productiva aprobadas.

## Artefactos y propietarios de runtime

| Área | Archivos relevantes | Propietario operativo |
| --- | --- | --- |
| Intención OAuth | `gateway/src/zeler_gateway/oauth/events.py`, `core/src/zeler_platform_core/history_onboarding.py` | Gateway. |
| Coordinación y fuentes | `modules/sheets/src/zeler_sheets/history_onboarding.py`, `onboarding_sources.py`, `partial_history.py`, `consumer.py` | Sheets worker. |
| Exactitud, convivencia y renovación | `devoluciones_runner.py`, `formulas/recovery.py`, `formulas/recovery_worker.py`, `pilot_history_backfill.py` | Sheets worker; lectura compatible en Sheets API. |
| Progreso, tabla parcial y registro | `modules/sheets/src/zeler_sheets/api.py`, `formulas/handlers_orders_questions.py`, manifest y seed de registro | Sheets API. |
| Índices | `infra/mongo/indexes/sheets_history_receipts.json`, `sheets_history_backfill_plans.json`, `sheets_history_pending_records.json`, `sheets_full_operations.json` | Aplicación separadamente autorizada desde VM/VPC. |
| Verificador de rollback | `infra/deploy/sheets_rollback.py` | Herramienta operativa; actualizarla en el destino solo con autorización. |

El plan, jobs de recovery y metadatos nuevos usan colecciones internas sin
validador core existente; las guardas de runtime no son un validador Mongo nuevo.
Se reutilizan los esquemas de adquisiciones, recibos, rangos y certificados exactos.
La exportación debe comprobarse sin afirmar que certifica colecciones dinámicas.

El registro objetivo del nuevo goal necesita lectura de packs de mensajes,
**sin búsqueda ni otro scope Full**. Seed y manifest deben coincidir: aplicar solo
el seed no basta si el registro al iniciar la API vuelve a retirar los permisos.
Verificar el fingerprint completo y clientes de descubrimiento/detalle por
separado. No se amplían scopes de comunicación ni se conceden permisos reales
por editar estos archivos localmente.

El contrato **histórico C3** quedó en **15 scopes**; se actualizó también su verificador
de rollback, no solo los fixtures. Fingerprint de registro completo:
`bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d`.
Ese fingerprint15 no es el objetivo del nuevo goal: **14 = 13 + mensajes**, seis
keys/sinFull, fingerprint `453bf9eb6014d8055fe6cd372e98b1e2d0190a0241b519417fe5f5397e2c1525`.
El verificador canónico corregido no acredita compatibilidadC1 ni autoriza usar
el rollback clásico. Antes de activar permisos/policy, comprobar el registro completo de
la nueva fuente publicada y recuperación compatible con `policy_authority`;
un tag, una imagen antigua de13 o el fingerprint histórico15 no basta.

No hubo cambios al ejecutor bootstrap ni evidencia que obligue a reconstruir su
imagen por una modificación de comportamiento; revisar dependencias finales en
la propuesta exacta, sin desplegar servicios ajenos por copiar el mismo workspace.

## Qué falta antes de producción

[Propuesta preparada](zelerdata-historico-publicacion-piloto-propuesta.md): separa
publicación, probe Full, backup/restore, builds, despliegue y piloto; una cuenta,
90 minutos/día UTC, máximos 2,000 GET iniciales + 500 de mantenimiento,
**Full excluido con 0 GET** (investigación cerrada). El piloto está **autorizado por
el nuevo goal pero no ejecutado**, condicionado a gates de pausa/respaldo/deploy. El
descubrimiento Full posterior tuvo alcance separado y siete GET consumidos;
el usuario cerró esa investigación: no quedan consultas/retries programados;
no convierte estos límites generales en autorización productiva.
El SHA fuente C3 publicado/verificado se registra en el recibo; no se fija un digest
sin build real. RETIROS Full permanece pendiente sin bloquear las otras fuentes.
La [adaptación mínima del complemento](zelerdata-ordenes-parciales-complemento-propuesta.md)
es documental: opt-in final opcional, aviso visible y default exacto sin cambios;
**no implementada ni disponible en Sheets**.

1. Mantener RETIROS Full pendiente y excluido del piloto, sin bloquear las otras
   cinco fuentes; investigación cerrada por el usuario, no consultas restantes
   ni mapeo supuesto. No presentar ese pendiente como implementación completa.
2. Commit/push propios autorizados: comprobar su resultado en el recibo y usar
   el commit fuente exacto publicado en `main`; el checkout local no es autoridad
   de build. Builds afectados y despliegue seleccionado están autorizados por
   el goal: d78 y tres builds verifican fuente/procedencia, no aceptación runtime.
3. Preparar baseline sanitizado por fuente, junio/otros períodos sanos, salud y
   capacidad; identificar imágenes anteriores inmutables y rollback compatible.
4. Completar backup autorizado consistente desde VM/VPC y restauración aislada. Proteger y
   delimitar el respaldo, preservar OAuth/hechos posteriores y no restaurar toda
   la base a ciegas. El fixture local no sustituye este paso.
5. Ejecutar cambios mínimos autorizados de registro/índices requeridos, builds separados y
   despliegue acotado. Una autorización no implica la otra. Activar el flag solo
   después de comprobar consumidores, permisos y compatibilidad.
6. Ejecutar piloto autorizado con vendedor, fuentes/fechas, máximo de consultas, concurrencia,
   pausas y criterios de parada concretos. OAuth/relink auténtico, sin force,
   tokens copiados ni limpieza para simular una cuenta vacía.
7. Verificar digest en ejecución, readiness, progreso persistido y lectores por
   fuente. Observar capacidad/salud después del asentamiento y medir carga anual
   representativa con el pacing real, no extrapolar los tiempos sintéticos.
8. Activar solo celdas/rangos autorizados de la hojaTEMP y verificar fórmulas nativas. Observar dos
   ciclos con cambios reales posteriores al corte; ciclos vacíos y renovación
   local de pruebas no demuestran procesamiento incremental remoto.

Seguir [runbook](../deploy.md) y la propuesta de piloto de la especificación:
destino documentado `zeler-platform-dev`, `platform-vm`, `us-central1-a`, sujeto a
confirmación actual. El cierre local original no consultó Mongo productivo ni accedió a la VM.
Las lecturas VM y el permiso individual posteriormente autorizados se distinguen
en la actualización Full siguiente; nunca se consultó Mongo productivo desde
el asistente local.

## Actualización Full — 3 de octubre de 2026 UTC

Esta sección añade hechos posteriores al cierre local y a su publicación.
**Conserva los hechos del recibo C1/C2 y no convierte código publicado en
imágenes construidas/desplegadas.** Fuente original `4216e18b62da289c1e67acd1ac8d6db4ba0c9217`;
La corrección de inventario, sus pruebas y los reportes propios fueron
posteriormente autorizados y publicados como C3 `aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d`;
no se construyó ni desplegó imagen por esa publicación. La corrección/pruebas fueron locales;
la búsqueda real posterior se autorizó por separado y se detuvo tras cuatro GET
adicionales por 429, sin activar el piloto. Las otras cinco fuentes permanecen
sin bloqueo por el mapeo Full; Full sigue excluido de su piloto.

### Evidencia real autorizada y alcance exacto

- Se verificó HOPEMOB `82453304` linked activo desde VM. La lectura Mongo
  acotada allí no encontró referencia de retiro; encontró tres inventarios Full
  propios: `IMWU47589`/`FQIO47832` en `MLM2030082766`, variaciones
  `177603522045`/`177603522043`, y `SWMK39536` en `MLM2371963856`.
  Son inventarios, no retirados/bultos ni prueba de retiro existente.
- Solo se habilitó `GET /stock/fulfillment/operations/search`: registro runtime
  **13→14 scopes**, demás campos preservados. Respaldo VM privado 0600:
  `/var/tmp/zelerdata-full-search-scope-before-20261003T0259.json`, SHA-256
  `c7414dee18e54502552c03706b41b8bf58f09f20131a3c5ec25f27305f034d50`.
  No se desplegó el contrato local de 15 scopes por esta modificación individual.
- **Primera etapa: 3/10 GET upstream atestiguados**, sin retries: reserva sin inventario → 400
  (`inventory_id` requerido); reserva `IMWU47589` → 200/cero resultados;
  entrega del mismo inventario → 429/`over_quota`. Selección consultada:
  `[2026-08-05,2026-10-03)` UTC. Se detuvo; la ventana
  `[2026-06-07,2026-08-05)` UTC sigue sin consultar.
- Cuerpo 429 retenido:
  `Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota`.
  Solo `error`/`message`, no headers conservados. El filtro local
  `_response_headers` de `gateway/src/zeler_gateway/proxy/router.py` no reenvía `Retry-After`; ausencia en el proxy no
  acredita ausencia upstream. No hay plazo de espera contractual conocido ni
  evidencia de cuota diaria. Inspección de código desplegado, solo lectura y sin
  GET Mercado Libre: forwarder conserva `Content-Type`, intentos upstream y
  content-missing, **no `Retry-After`**; audit no almacena headers/Retry-After.
  Espera no recuperable con evidencia retenida. No se modifica el gateway ni
  se prueba otra llamada para averiguar si ya liberó la cuota.

### Corrección local requerida y frontera de la validación

La respuesta 400 confirmó que el adquiridor publicado omitía `inventory_id`.
Corregir ese contrato, no ampliar los permisos: seleccionar inventarios
auténticos de `items`/variaciones del vendedor y mantener estado por inventario,
conservando avance útil ante paginación, cuota, fallo y reinicio. No usar
candidatos ajenos, convertir vacío en "no aplica", ni inventar ID de retiro,
cantidad solicitada o coverage. Este cambio local no solventa el mapeo RETIROS.

**Corrección local implementada y publicada en C3; no desplegada:**
`collect_full_operations` selecciona publicaciones Full propias por páginas de
32 más un registro de lookahead, obtiene inventarios de producto/variaciones,
deduplica entre páginas y limita el conjunto a 4,096 identidades. Superar el límite
queda pendiente/no exacto, no se inventa cobertura. Cada GET lleva `inventory_id`
y revalida que ese inventario todavía pertenece al vendedor. Checkpoint persiste
inventario/tipo/scroll y rango congelado; el cursor legacy sin inventario se
invalida conservando intervalo y hechos previamente persistidos.

**TDD y prueba de reanudación:** primero RED (1 fallo porque faltaba el filtro),
después **28/28 focused aprobadas**: 25 de collector, 2 con Mongo rs0 aislado y
el dispatcher/lector RETIROS real fail-closed, y 1 del coordinador compartido.
Esta última conserva assertions y añade únicamente inventario Full sintético
propio de cada seller al fixture; sin candidato propio el collector correctamente
no hace GET, por lo que el fixture anterior sin esa semilla no probaba el caso. Caso 429: dos GET consumidos en
primer turno, parada y checkpoint útil conservado; reanudación usa exactamente
inventario/tipo/scroll pendiente en un GET. Ruff/formato/mypy iniciales de los
3 archivos del fix y `diff --check`: aprobados; el gate general siguiente incluye
también el cuarto archivo de fixture corregido. Son pruebas locales con respuesta
controlada, **no GET nuevos a Mercado Libre ni prueba positiva del mapeo**.

**Gates finales de esta corrección local:** snapshot de 4 archivos ejecutables,
hashes congelados y revalidados sin cambios al finalizar:

| Control | Resultado final |
| --- | --- |
| Suite completa aislada Linux | **5,820 aprobadas, 0 fallos, 9 skips; 381.04 s**. |
| rs0 protegido, sin `MONGO_URI` ambiental | **8 aprobadas, 0 skips**: cubre los 8 skips de guard de la suite; queda solo Caddy sin claves requeridas. |
| `uv run ruff check .` | Aprobado. |
| `uv run ruff format --check .` | Aprobado, 643 archivos. |
| `uv run mypy .` | Aprobado completo, 643 archivos. |
| direct-Meli lint y schema-export `--check` | Ambos aprobados. |

Un primer run detectó únicamente el fixture compartido sin inventario propio;
se corrigieron 9 líneas de semilla sintética sin debilitar assertions ni modificar
el comportamiento del collector, se repitieron 28 focused y la suite completa.
Ese run fallido no se presenta como evidencia final verde. Las cifras 5,808+8
anteriores acreditan el snapshot original publicado; 5,820+8 acredita este
snapshot corregido publicado en C3 **sin builds/despliegue**. No hubo otra investigación general,
consulta remota ni ronda de perfección; se cerró la regresión de fixture del cambio.

### Reanudación única autorizada y ejecutada; cerrada por 429

El [plan histórico de siete restantes](zelerdata-full-validacion-acotada.md#4-una-reanudación-preparada--siete-restantes-sin-ejecutar)
se conserva sin ampliar selecciones ni permisos. Tras intentos previos de acceso
sin nuevos GET, el usuario autorizó una fase de preparación read-only de diez
minutos, 04:40:05→ 04:50:05 UTC. A 04:41:14.567475 se verificaron dentro de la VM
contenedores/app correctos, imports con `/app/.venv/bin/python` en gateway y
worker, camino single-attempt, auditoría de exactamente tres GET previos,
HOPEMOB único activo/token válido sin refresh, 14 scopes y tres inventarios propios.
No se instaló nada, reinició servicio ni modificó confianza/credenciales.

| Hito | UTC 2026-10-03 |
| --- | --- |
| Inicio real Full | **04:41:54.498744** |
| Deadline global | **04:44:54.498744** |
| Fin/parada | **04:41:58.125021**, 3.626277 s transcurridos. |

Secuencia única contra search, limit=50, ventana reciente `[2026-08-05,2026-10-03)`:
1) IMWU entrega → 200/cero filas/sin scroll; 2) FQIO reserva → 200/cero filas;
3) FQIO entrega → 200/cero filas; 4) SWMK reserva → 429/`over_quota` y parada
inmediata. Cada request atestigua un GET upstream, sin reintentos/paginación.
**Cuatro nuevos + tres previos = siete acumulados de diez.** Selecciones 5–7 no
se ejecutaron; la ventana antigua `[2026-06-07,2026-08-05)` quedó sin consultar.
No hubo referencia de retiro/bulto ni cantidad/fecha de solicitud. Un 200 vacío
no prueba ausencia global de retiros ni cobertura anual.

**Espera contractual no acreditada:** el 429 repite
`Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota`.
Proxy no reenvía `Retry-After`; ausencia en su respuesta no acredita ausencia
upstream, reset diario o cuota liberada. No se vuelve a consultar ni se programa
retry para averiguarlo. Escrituras de negocio: 0; se conservan auditoría/counters
normales del gateway. Sin scopes nuevos, refresh, cambios de identidad/confianza,
instalación/restart, commit/push/build/deploy. El saldo aritmético de **tres GET
sin usar no autoriza continuar**. Ninguna adquisición/reanudación automática
queda aprobada por esta ejecución ya detenida.

**Clasificación actual:** defecto de filtro/checkpoints corregido y validado
localmente y publicado en C3, sin desplegar; mapeo auténtico RETIROS bloqueado externamente;
ejecución acotada cerrada por 429 sin referencia; validación productiva de
backend, nativo Sheets y piloto sigue pendiente. Full continúa fuera del piloto
y no bloquea las otras cinco fuentes. El complemento parcial sigue exclusivamente
propuesto, no disponible en Sheets. El postcheck read-only de **04:43:02.086342 UTC** confirmó auditoría de
**siete GET totales** y cuatro nuevos statuses 200/200/200/429 a 04:41:55.408,
04:41:56.163, 04:41:57.099 y 04:41:58.113 UTC; registro 14 scopes sin cambios.
Sin GET nuevos; hashes SSH config/ambos knownhosts y cuatro archivos ejecutables
locales validados permanecieron iguales. Ejecución y verificación cerradas,
sin más llamadas VM necesarias ni permiso pendiente de reanudación.
El usuario cerró la investigación Full: no ejecutar ni programar los tres GET
sin usar; no se propone otra consulta. Imágenes/fuente/digests actuales **no
atestiguados**: SSH e imports correctos no prueban procedencia, por lo que se
requiere inspección de drift aparte antes de un rollout. Runtime observado: 14
scopes no acredita el contrato local de 15 desplegado.

## Git, conservación y reversibilidad

En el cierre local previo a la autorización, la implementación permanecía sin
commit; la publicación posterior se documenta en el recibo. Durante el trabajo,
otro actor publicó
`124fd236fea600ead8c1436560a22b1909d7c3c8` (diagnóstico OAuth), avanzando desde el
HEAD inicial anterior. No pertenece a esta implementación; se preservó su estado
y no se hizo stash, reset, cambio de rama ni worktree.

La retirada local debe limitarse a archivos/hunks propios y sus tests/documentación,
nunca usar `git reset --hard` sobre el checkout compartido. En runtime, desactivar
el poller detiene admisión/ejecución futura, no borra planes, hechos ni certificados.
Un rollback de imágenes exige compatibilidad de scopes y datos nuevos antes de
arrancar writers antiguos. Un worker anterior que desconozca `policy_authority`
no es rollback compatible con jobs onboarding pendientes: detener/drenar esas
unidades o conservar una imagen que respete la misma frontera de claim; no borrar
los jobs ni su evidencia. No hay aprobación/recibo de review fabricado:
entrega `disabled/unmanaged` conforme a política opt-in.
