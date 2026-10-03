# RETIROS Full: contrato faltante y comprobación acotada

Actualización: 3 de octubre de 2026 UTC. Estado: **RETIROS bloqueado por evidencia
de fuente concreta**; Full queda excluido del piloto y no bloquea las otras cinco
fuentes. La única reanudación autorizada de siete selecciones **se ejecutó y se
detuvo en la cuarta por 429**: cuatro GET adicionales, **siete acumulados** y tres
sin usar. Ese saldo **no autoriza otra ejecución**. No se encontró referencia
de retiro; no se cambiaron permisos ni se hicieron builds/despliegues.

## 1. Resultado de la investigación local

Se inspeccionaron el adquiridor existente, el importador legacy, el esquema
canónico y el handler normal `ZELERDATA_RETIROS`. La investigación externa se
limitó a cuatro lotes de búsqueda en documentación oficial; los accesos directos
a algunas páginas devolvieron 403. En ese cierre local del 2 de octubre no hubo
llamadas autenticadas a Mercado Libre. Las llamadas posteriores autorizadas (tres iniciales y cuatro
de una reanudación) se describen abajo; no se prolonga investigación pública ni se repite automáticamente
una petición fallida para buscar una cuota disponible.

La [documentación mexicana de Full](https://developers.mercadolibre.com.mx/es_mx/envios-fulfillment),
actualizada el 18/09/2026, distingue stock, operación, reserva, cancelación,
entrega física, retiro abandonado y descarte. Documenta los recursos de búsqueda
y detalle de operaciones. El `id` de su ejemplo identifica una **operación de
stock**; no acredita identidad de retiro o bulto. La respuesta mostrada contiene
`detail` con movimientos y `result` con saldo de stock: ninguno demuestra por sí
solo la cantidad originalmente solicitada. `date_created` fecha la operación,
no necesariamente la solicitud de retiro. Las referencias ilustradas enlazan
envíos/ingresos; no se publica un ejemplo que establezca la jerarquía retiro/bulto.

La [referencia oficial de detalle de operaciones](https://developers.mercadolibre.com.mx/es_ar/servicios-consulta-usuarios/envios-fulfillment)
corrobora `GET /stock/fulfillment/operations/{operation_id}` y sus errores. Es una
ruta documentada, pero su ejemplo es una venta: no resuelve la semántica faltante.
La búsqueda admite hasta 60 días, páginas de hasta 1000 registros, scroll de cinco
minutos y terminal `scroll=null`; el día `date_to` no se incluye. Nada de ello
acredita una cobertura anual de retiros por sí mismo.

La [documentación de provisiones](https://developers.mercadolibre.com.mx/es_ar/manejo-de-pagos/provisiones)
menciona `fulfillment_info.withdrawal_id` en cargos por retiro. Es una pista,
**no un mapeo válido**: `charge_info.detail_id` identifica el cargo y la cantidad
se describe como almacenada/recolectada, no solicitud original ni bulto. No se
incorpora facturación, que está fuera del alcance autorizado de este histórico.

### Hallazgo legacy que no debe copiarse

`../sheetsellerappindividual/Docs/docs/SheetsellerApp/compute_engine.md`, sección
`api2mongo`, relata que una referencia llamada `withdrawal_id` representaría el
bulto y que sus primeros siete dígitos producirían el retiro principal. Esa regla
no está acreditada en documentación oficial. **No usar prefijos, posiciones de
página, ID de operación ni ID de cargo como identidad auténtica de retiro.** El
lector legacy consume `withdrawal_records` ya almacenados; no demuestra adquisición
API actual ni conservación de esa regla entre países/cuentas/épocas.

## 2. Mapeo que sí y que todavía no está acreditado

| Campo de RETIROS | Evidencia actual | Falta concreta |
| --- | --- | --- |
| Vendedor | `seller_id` de operación y cliente ligado al vendedor. | Verificar pertenencia en muestra real; rechazar discrepancias. |
| Inventario | `inventory_id` documentado en operación. | Confirmar vínculo a publicación/variación del vendedor cuando se muestre. |
| Publicación, SKU, título | `/items/{item_id}` e inventario pueden proporcionar contexto. | Un join auténtico, no asumir que SKU identifica un bulto. |
| ID principal retiro | No se acredita en el ejemplo de operación. | Identificador y semántica de solicitud principal, incluido vínculo explícito a bulto. |
| ID secundario retiro | No se acredita en el ejemplo de operación. | Identificador estable de detalle/bulto y su pertenencia al principal. |
| Unidades solicitadas | Cambios/saldos no equivalen a solicitud inicial. | Campo contractual de cantidad solicitada por producto/bulto; tratamiento de cancelación parcial. |
| Fecha de creación | Existe la fecha de operación. | Acreditar fecha de solicitud/bulto que define el rango del lector. |
| Fecha de entrega | El tipo entrega acredita un evento, no un join por sí solo. | Vincular su fecha al mismo retiro, detalle e inventario; reserva/cancelación/remoción no son entrega. |

El esquema actual admite `null` en algunos detalles/cantidades; eso **no autoriza**
cambiar el significado de las columnas o certificar un rango sin identidad y
cobertura. El handler exige primero `require_read_model_reconciled_range` y luego
lee `sheets_full_withdrawals`; guardar operaciones crudas no abre esa protección.

No se ha completado un mapeo ni una prueba positiva de adquisición API → lector.
La colección de operaciones y el lector fail-closed existente permanecen intactos;
no se reetiquetan filas legacy como API ni se certifica una muestra como año completo.

**Protección comprobada localmente:**
`modules/sheets/tests/test_full_onboarding_handler.py` ejecuta el adquiridor con
la forma documental de operaciones de reserva/entrega y una referencia candidata
explícitamente sintética, sin atribuirle autenticidad de proveedor. Dos casos
(con/sin referencia) persisten las operaciones en Mongo rs0 aislado y pasan por
el dispatcher, handler y lector Mongo reales de `ZELERDATA_RETIROS`: ambos
rechazan el rango con `FormulaDataUnavailableError`, sin filas de retiro ni
certificados fabricados, aunque exista cantidad de movimiento y un campo
plausible `withdrawal_id`. Resultado: **2 pruebas aprobadas**; Ruff, formato y
mypy enfocados aprobados. Es caracterización de la protección existente, no un
mapeo nuevo ni una muestra API real; se comprobó primero la prueba existente de
rango no reconciliado y no se alteró código ejecutable del producto.

## 3. Evidencia posterior autorizada — 3 de octubre UTC

### Identidad, búsqueda local y permiso acotado

El operador verificó HOPEMOB, vendedor `82453304`, linked activo, y consultó Mongo
**exclusivamente dentro de la VM**. No encontró filas canónicas/legacy de retiros
ni operaciones que aportaran referencias auténticas. Sí encontró inventarios
Full de esa cuenta en `items` y sus variaciones:

| Inventario auténtico observado | Publicación | Variación |
| --- | --- | --- |
| `IMWU47589` | `MLM2030082766` | `177603522045` |
| `FQIO47832` | `MLM2030082766` | `177603522043` |
| `SWMK39536` | `MLM2371963856` | — |

Son candidatos legítimos para **descubrir** referencias, no prueba de que hubo
retiro ni identidades de retiro/bulto. No se pide ahora al usuario un retiro
conocido: ya existe una búsqueda técnica acotada preparada con estos candidatos.

Con autorización específica se añadió al registro Sheets únicamente
`GET /stock/fulfillment/operations/search`: **13 → 14 scopes**. Los otros campos
permanecieron iguales. La configuración anterior está respaldada en la VM:

- Archivo privado `/var/tmp/zelerdata-full-search-scope-before-20261003T0259.json`;
  permiso `0600`.
- SHA-256: `c7414dee18e54502552c03706b41b8bf58f09f20131a3c5ec25f27305f034d50`.

El contrato local publicado de 15 scopes y su rollback **no se declaró desplegado**
por habilitar ese permiso individual. No se añadieron scopes de detalle,
inventario, mensajes o comunicación, ni se publicó imagen nueva.

### Tres intentos físicos atestiguados, luego parada

Cada llamada consumió un GET upstream (`X-Zeler-Upstream-Attempts: 1`), sin
reintentos automáticos. Los resultados preservados son:

| GET ya consumido | Selección | Resultado y límite |
| --- | --- | --- |
| 1 | Vendedor, reserva; sin inventario; `[2026-08-05, 2026-10-03)` UTC. | **400:** `inventory_id` requerido. Demuestra una omisión del adquiridor local publicado, no ausencia de retiros. |
| 2 | `IMWU47589`, `WITHDRAWAL_RESERVATION`, misma ventana. | **200, cero resultados:** no se encontró referencia en esa selección; no prueba ausencia de retiros ni cobertura anual. |
| 3 | `IMWU47589`, `WITHDRAWAL_DELIVERY`, misma ventana. | **429, over quota:** se detuvo inmediatamente. No se acredita qué cuota fue ni su período de renovación. |

La ventana más antigua `[2026-06-07, 2026-08-05)` UTC **no fue consultada**.
Al cerrar esa primera etapa se conservaban **tres de diez intentos consumidos**; no empieza una bolsa nueva de
diez. Ninguna respuesta aportó todavía una referencia útil de retiro/bulto.
Las lecturas HTTP no escribieron hechos de negocio; el gateway conserva su
contabilidad/auditoría normal. No prometer "cero escrituras internas".

### 429 y tiempo de espera: qué está y qué no está comprobado

El cuerpo retenido contiene `error="over_quota"` y
`message="Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota"`;
**no se conservaron los headers de la respuesta**. El código del filtro `_response_headers` de `gateway/src/zeler_gateway/proxy/router.py` no
reenvía `Retry-After`. Por tanto no se puede afirmar que el upstream careciera
de ese header ni deducir una espera concreta de su ausencia en el proxy.

La inspección de lectura del código desplegado confirmó el filtro: reenvía
`Content-Type`, `X-Zeler-Upstream-Attempts` y `X-Content-Missing`, **no**
`Retry-After`; el audit tampoco guarda response headers/Retry-After. No hubo GET
Mercado Libre en esa verificación. El plazo de espera no es recuperable de lo
retenido; no se cambia el comportamiento del gateway en este trabajo. No se hace otra llamada Mercado Libre para comprobar si ya se liberó
la cuota. **Tiempo de espera contractual conocido: ninguno acreditado.** Un
backoff genérico del cliente no demuestra la ventana de renovación de esta
respuesta; tampoco una fecha UTC nueva acredita una cuota diaria. La aprobación
siguiente debe nombrar cuándo se permite iniciar y sigue deteniéndose ante 429;
no es una autorización para esperar y reintentar indefinidamente.

### Corrección local: filtro auténtico y checkpoint por inventario

La omisión `inventory_id` requiere una corrección **local**, con inventarios
seleccionados desde datos canónicos de ese vendedor, paginación/cursor persistido
por inventario y conservación de páginas útiles al agotar cuota, fallar o
reiniciar. Inventario de otra cuenta o ausencia de inventarios no autoriza ampliar
alcance, inventar candidatos ni declarar Full no aplicable.

La corrección local ya incorpora selección paginada de publicaciones Full
propias (32+lookahead), inventarios de producto/variaciones deduplicados, límite
4,096 pendiente/no exacto y revalidación de pertenencia antes de cada GET.
Checkpoint inventario/tipo/scroll conserva avance; cursor legacy sin inventario
se invalida sin descartar rango/hechos. TDD: 1 RED por filtro ausente, luego
**28 focused aprobadas** (25 collector+2 lector real/Mongo fail-closed+1
coordinador compartido con inventarios propios sembrados en fixture);
Ruff/formato/mypy enfocados aprobados. Prueba 429 local conserva estado tras 2 GET
y reanuda ese inventario/tipo/scroll con 1 GET, no ejecutado contra Mercado Libre.
Gates generales finales: **5,820 aprobadas, 0 fallos**, más **8 rs0 protegidas
aprobadas**; Ruff/formato/mypy completos, direct-Meli lint y schema-export
aprobados. Los 9 skips de suite son 8 guards cubiertos separadamente y 1 Caddy sin
claves requeridas. Snapshot de 4 archivos ejecutables congelados/hash revalidados;
[informe de implementación](zelerdata-historico-al-vincular-implementacion.md)
separa este fix local del snapshot original publicado y de la evidencia real.
No es nuevo recurso de Mercado Libre, mapeo de RETIROS ni código desplegado.
No se modifica registro/permiso productivo para probarlo.

## 4. Una reanudación preparada — siete restantes, sin ejecutar

**Título y plan históricos conservados para mantener el enlace:** al prepararse
no estaban ejecutados. El resultado actual se registra abajo: reanudación
posteriormente autorizada, cuatro de siete GET ejecutados, parada por 429,
siete acumulados y **ninguna continuación automática autorizada**.

**Ruta única:** `GET /stock/fulfillment/operations/search` mediante el gateway
normal, JWT/autorización existentes y cuenta HOPEMOB linked verificada dentro
del runtime VM permitido. No exportar tokens/credenciales ni usar navegador,
cliente alternativo para evadir controles o Mongo productivo desde contexto local.

Cuenta `82453304`; `limit=50` en todas las llamadas. Fechas congeladas UTC, inicio
inclusivo y fin exclusivo. Solo los tres inventarios ya encontrados y dos tipos
existentes. Orden fijo, **una sola pasada**:

| GET restante | Inventario | Tipo | Ventana UTC |
| --- | --- | --- | --- |
| 1 | `IMWU47589` | `WITHDRAWAL_DELIVERY` | `[2026-08-05, 2026-10-03)` |
| 2 | `FQIO47832` | `WITHDRAWAL_RESERVATION` | `[2026-08-05, 2026-10-03)` |
| 3 | `FQIO47832` | `WITHDRAWAL_DELIVERY` | `[2026-08-05, 2026-10-03)` |
| 4 | `SWMK39536` | `WITHDRAWAL_RESERVATION` | `[2026-08-05, 2026-10-03)` |
| 5 | `SWMK39536` | `WITHDRAWAL_DELIVERY` | `[2026-08-05, 2026-10-03)` |
| 6 | `IMWU47589` | `WITHDRAWAL_RESERVATION` | `[2026-06-07, 2026-08-05)` |
| 7 | `IMWU47589` | `WITHDRAWAL_DELIVERY` | `[2026-06-07, 2026-08-05)` |

La primera llamada es la selección antes fallida con 429, pero solo se ejecutaría
**una vez bajo nueva aprobación expresa**, no como retry de la autorización anterior.
No incluye scroll/paginación, detalle de operaciones, inventarios, items ni
facturación. Aunque la respuesta proporcione rutas/IDs o scroll, no seguirlos con
esta aprobación. No ampliar ventanas o realizar más llamadas para gastar sobrante.

**Máximos:** siete GET físicos adicionales; **3 + 7 = 10 globales**. Deadline
global de tres minutos y techo de una solicitud por segundo; timeout de 10 s por
request. Deshabilitar/descontar reintentos implícitos y comprobar el atestado de
intentos del gateway. Detener en la primera referencia potencialmente útil de
retiro/bulto, primer429, otro HTTP fallido, timeout, respuesta inválida o cuenta
inconsistente. No garantizar que estas siete selecciones localicen un retiro.

**Sin escrituras de negocio ni scopes nuevos.** Contabilidad/auditoría normal del
proxy permanece; no evadirla, borrar registros, reparar tokens ni cambiar cuotas.
No certificar coverage ni persistir filas canónicas/retiros por este descubrimiento.
La evidencia visible se limita a status/GET consumidos, inventario seleccionado,
campos y semántica sanitizada; no cuerpos completos, compradores, direcciones,
mensajes, headers sensibles, tokens ni códigos OAuth. Si aparece una referencia,
conservar solo la evidencia mínima para proponer después su comprobación/mapeo.

### Texto original de aprobación — histórico, no nueva concesión

> Autorizo una sola reanudación de lectura desde el runtime aprobado para
> HOPEMOB `82453304`, comenzando `<FECHA_Y_HORA_UTC_AUTORIZADAS>`, con las siete
> selecciones de §4 en ese orden y `limit=50`. Hasta **siete GET upstream restantes**,
> **diez acumulados incluidos los tres anteriores**, tres minutos y una solicitud
> por segundo como máximos; sin paginación, retries, nuevas rutas ni scopes.
> Detener al primer resultado que aporte referencia útil, 429, otro HTTP fallido,
> timeout o inconsistencia. No autorizo escrituras de negocio, cambios de cuenta,
> cuotas/permisos, builds, deploys ni ejecutar automático al liberarse la cuota.

La entrega de ese texto, por sí sola, no era aprobación. La autorización
posterior y el resultado de acceso se registran a continuación; no hay una
reanudación automática pendiente.

### Recibo de la ejecución autorizada — parada antes de acceder a la VM

- Primera autorización recibida: inicio registrado **2026-10-03 04:24:41 UTC**,
  deadline **04:27:41 UTC**. La solicitud de permiso del entorno se interrumpió;
  esa ventana venció y no se prolongó automáticamente.
- Nueva confirmación explícita «Adelante continua, autorizo»: inicio registrado
  **04:28:43 UTC**, deadline **04:31:43 UTC**, manteniendo la misma secuencia y
  los siete GET restantes. El script preparado comprobaría primero auditoría
  previa, identidad, propiedad de los inventarios y permiso existente, antes de
  cualquier GET; no gestionaría claves SSH ni credenciales.
- El único intento SSH a `platform-vm`, proyecto `zeler-platform-dev`, zona
  `us-central1-a`, terminó con **`Host key verification failed` / exit 255**,
  antes de ejecutar el script en la VM. La parada se registró a **04:29:38 UTC**.
  No se reintentó ni se aceptó/reemplazó una clave de host. Este error no prueba
  que la clave haya cambiado: no se investigó su causa ni se eludió el control.
- **GET Mercado Libre adicionales iniciados por esta ejecución: 0**. La
  verificación remota de auditoría del intento interrumpido tampoco pudo
  ejecutarse; no se presenta como comprobada. El último acumulado atestiguado
  sigue siendo los **3 GET anteriores**. No se consumió una nueva bolsa de diez.
- No se obtuvieron referencias nuevas de retiro/bulto/cantidad/fecha. No hubo
  escrituras de negocio, permisos nuevos, reparación de tokens, commit/push,
  builds ni despliegues. La corrección local existente permanece sin publicar.

**Estado de ese intento: cerrado por bloqueo de acceso SSH; API no ejecutada.**
Para otra ejecución primero debe verificarse el contexto SSH legítimo y su
huella/configuración existente, sin aceptar claves nuevas automáticamente; el
alcance y el saldo deben confirmarse antes de una nueva autorización acotada.
No encadenar comprobaciones ni búsquedas con la autorización ya detenida.
Full continúa fuera del piloto y no bloquea las otras cinco fuentes.

### Diagnóstico IAP posterior autorizado — acceso recuperado, parada de diagnóstico

El usuario autorizó diagnosticar el acceso legítimo con IAP y, solo después de
recuperarlo, iniciar una ejecución Full de tres minutos. Esa nueva ventana debía
comenzar al iniciar Full, no al comenzar el diagnóstico SSH.

- La lectura de GCP confirmó `platform-vm` RUNNING, proyecto
  `zeler-platform-dev`, zona `us-central1-a`, ID `7989018496556289195`.
  Coincide con el alias ya configurado `compute.7989018496556289195` y su entrada
  ED25519 previamente confiada en `google_compute_known_hosts`.
- La invocación anterior `--plain` sin IAP no instaló las opciones Google de
  identidad/knownhosts/alias; la implementación SDK lo confirma. Eso explica la
  pérdida del contexto de confianza usado en el intento, **no una clave de host
  cambiada**. La recuperación usó `gcloud compute ssh --tunnel-through-iap` y
  opciones explícitas de la configuración existente: usuario/clave existentes,
  `IdentitiesOnly=yes`, `UserKnownHostsFile`, `HostKeyAlias`,
  `StrictHostKeyChecking=yes`, `UpdateHostKeys=no` y `BatchMode=yes`.
- Se conservó `--plain` con esas opciones estrictas explícitas para evitar
  registros/importaciones SSH en metadata u OSLogin. No se desactivó verificación,
  aceptó otra clave ni modificó confianza. Los hashes de `~/.ssh/config`,
  `known_hosts` y `google_compute_known_hosts` permanecieron iguales.
- **IAP SSH funcionó** y se verificó el hostname `platform-vm`. A continuación,
  el único comando de diagnóstico encontró `ModuleNotFoundError: No module named
  'zeler_gateway'` al inspeccionar el proxy mediante `python` en el contenedor.
  Se detuvo sin otro intento remoto; la parada se registró a
  **2026-10-03 04:36:36 UTC**.
- La inspección local posterior de `gateway/Dockerfile` muestra instalación con
  `uv sync` en `/app/.venv` y arranque con `.venv/bin/uvicorn`; el comando usado
  invocó `python`, no el intérprete de ese entorno. Es un defecto del comando de
  diagnóstico, **no evidencia de que el servicio gateway esté caído**. La ruta
  candidata a verificar en otro intento autorizado es `/app/.venv/bin/python`;
  su presencia efectiva no se comprobó con otra consulta a la VM.

**Estado de ese diagnóstico: acceso SSH recuperado sin cambiar confianza; ejecución detenida
por el intérprete del comando de diagnóstico.** El script Full y su verificación
Mongo de identidad/auditoría **no llegaron a iniciarse**. Por tanto no existe hora
de inicio de ejecución Full ni una ventana API consumida: **0 GET adicionales
iniciados**, último acumulado atestiguado **3/10**, ninguna referencia nueva.
No hubo permisos/rutas nuevos, escrituras de negocio, cambios de credenciales,
commit/push, builds o despliegues. El saldo no se presenta como auditado de nuevo.

Ese diagnóstico se cerró sin encadenar intentos. La preparación y ejecución
posteriores se hicieron con la **nueva autorización expresa** siguiente,
conservando las selecciones y paradas originales. No se reutilizó un permiso
agotado ni se repitió automáticamente una llamada después del 429.

### Preparación posterior autorizada — diez minutos, solo lectura

El usuario autorizó preparación con ajustes read-only de comandos dentro de la
VM antes de iniciar Full, sin nuevas llamadas a Mercado Libre. Ventana:
**2026-10-03 04:40:05 → 04:50:05 UTC**. Preparación verificada a
**04:41:14.567475 UTC**, tras 69.567475 s de preparación, dentro del límite:

- Gateway y worker correctos, ejecutándose con aplicación en `/app`.
  **`/app/.venv/bin/python`** existe y los imports del servicio funcionan en
  ambos contenedores. Se corrigió el comando, no se instaló nada ni reinició
  un servicio. Camino desplegado single-attempt/header de intentos verificado.
- Mongo dentro de VM: auditoría confirmó **exactamente tres GET anteriores**:
  400 a 03:01:03.479, 200 a 03:03:53.802 y 429 a 03:03:54.933 UTC. El saldo máximo
  inicial de la ejecución nueva era siete de diez, no diez nuevos.
- HOPEMOB `82453304` único/activo y validez de token comprobada **sin refresh**;
  14 scopes sin cambios, tres inventarios propios y variaciones confirmados.
  No se imprimieron/exportaron credenciales ni cambió la identidad de cuenta.

### Ejecución única Full autorizada — parada inmediata en 429

**Inicio real:** `2026-10-03T04:41:54.498744Z`.
**Deadline:** `2026-10-03T04:44:54.498744Z`.
**Fin/parada:** `2026-10-03T04:41:58.125021Z` (3.626277 s transcurridos).
Desde el runtime ya preparado, única ruta search existente, `limit=50`, selección
congelada, sin scroll/paginación ni reintentos. Resultado de esa pasada:

| Selección del plan | Inventario/tipo | Ventana UTC | Resultado |
| --- | --- | --- | --- |
| 1 | `IMWU47589`, `WITHDRAWAL_DELIVERY` | `[2026-08-05,2026-10-03)` | **200, 0 filas, sin scroll**. |
| 2 | `FQIO47832`, `WITHDRAWAL_RESERVATION` | misma reciente | **200, 0 filas**. |
| 3 | `FQIO47832`, `WITHDRAWAL_DELIVERY` | misma reciente | **200, 0 filas**. |
| 4 | `SWMK39536`, `WITHDRAWAL_RESERVATION` | misma reciente | **429/over_quota**; parada inmediata. |
| 5 | `SWMK39536`, `WITHDRAWAL_DELIVERY` | misma reciente | **No ejecutada**. |
| 6–7 | `IMWU47589`, reserva y entrega | `[2026-06-07,2026-08-05)` | **No ejecutadas**; ventana antigua íntegramente sin consultar. |

Los cuatro requests atestiguaron `X-Zeler-Upstream-Attempts: 1`, cada uno un intento
físico, sin retry automático. **Cuatro adicionales + tres previos = siete
acumulados de diez**; tres no utilizados. No se recibió referencia útil de
retiro/bulto ni cantidad/fecha de solicitud. Un 200 vacío solo describe esa
selección, no ausencia global de retiros ni cobertura completa.

Último error: `over_quota`,
`Entity operation_kvs_ds_v2__fbm_seller_stock_operations is over quota`.
`Retry-After` no aparece en el proxy que no lo reenvía: no prueba ausencia
upstream, cuota diaria, espera conocida ni que la cuota esté libre ahora.
No se consulta otra vez para comprobarlo ni se programa un retry.

**Sin escrituras de negocio**; contabilidad/auditoría normal aceptada del proxy
permanece. Sin scopes/rutas nuevas, refresh/cambio de cuenta, credenciales
exportadas, cambios de confianza SSH, instalaciones, restart, commit/push, build
o despliegue. El fix local de inventario sigue sin publicar/desplegar; recibos
C1/C2 y contrato de rollback se conservan. Evidencia operativa sanitizada en los
logs privados del operador `zeler-full-prepare-20261003.log` y
`zeler-full-seven-executed-20261003.log`; no son archivos de repositorio.

**Estado actual: ejecución autorizada cerrada por 429, mapeo auténtico pendiente.**
El saldo aritmético de tres GET **no es permiso para continuar**, no se prepara
otra búsqueda ni se pide automáticamente ampliar cuota/ventana. Full permanece
fuera del piloto; las otras cinco fuentes continúan independientes. La comprobación posterior de lectura, **04:43:02.086342 UTC**, confirmó
exactamente **siete GET totales**, los cuatro nuevos statuses 200/200/200/429 a
04:41:55.408, 04:41:56.163, 04:41:57.099 y 04:41:58.113 UTC, y registro de
**14 scopes sin cambios**. Sin GET Mercado Libre nuevos. Configuración SSH y
ambos archivos knownhosts conservaron hashes; los cuatro archivos ejecutables
validados del fix local también. No quedan comprobaciones VM pendientes para
cerrar esta ejecución y el postcheck no la reabre.

### Criterio de salida

- Si aparece referencia: documentar qué campo/nivel representa realmente y
  proponer su contraste acotado. Ningún nombre `withdrawal_id`, cantidad de
  movimiento ni fecha de operación prueba identidad principal/bulto, cantidad
  solicitada o fecha de solicitud. Detalle/otra ruta necesita aprobación propia.
- Si hay 429/error o no aparece referencia: conservar conteo y selección, marcar
  bloqueo/muestra insuficiente y detener. No prolongar búsqueda ni inferir
  "sin retiros", cuota diaria o cobertura completa por resultados vacíos.
- Para un mapeo positivo posterior: evidencia auténtica de jerarquía/cantidad/fecha,
  primero prueba fallida, adquisición→Mongo canónico→handler RETIROS con validador;
  cancelación parcial, dedup, vendedor ajeno y legacy preservados. Hasta entonces
  el lector sigue fail-closed y **Full queda fuera del piloto de las otras fuentes**.

## 5. Propuesta original de mapeo con muestra conocida — histórica/separada

**No es la autorización actual de descubrimiento.** La propuesta del 2 de octubre
se conserva para una fase posterior de contraste/mapeo, si existe una referencia
conocida y se aprueba su alcance propio. **No autoriza diez llamadas nuevas**, no
amplía los siete restantes de §4, ni exige al usuario conseguir el retiro como
requisito para que el agente ejecute la búsqueda técnica preparada. No se ejecuta
junto con esa búsqueda; detalle/inventario/items siguen fuera de su permiso.

### Datos de contraste para esa fase posterior, no para reanudar descubrimiento

1. Un vendedor legítimamente vinculado que **sí tenga** un retiro conocido. Puede
   ser el piloto `82453304` si el operador confirma ese retiro; no se supone Full.
2. Un inventario del vendedor implicado y, si se conoce, su publicación, usando
   evidencia legítima del vendedor; no enumerar toda su cuenta para encontrarlos.
3. Un intervalo cerrado de **hasta siete días UTC** con reserva y/o entrega de ese
   retiro. Si los eventos están más separados, escoger solo uno y declarar esa
   limitación; no ampliar fechas automáticamente.
4. Una referencia observada del retiro/bulto y las cantidades/fechas conocidas
   por el vendedor para contrastar su significado. Es comparación autorizada,
   no scraping ni una autorización para cambiar datos.
5. Un contexto runtime/VPC autorizado y cliente de lectura con permisos existentes.
   Secretos permanecen dentro del runtime. No extraer tokens ni consultar Mongo
   de producción desde el asistente local. Una denegación detiene la comprobación.

### Recursos y presupuesto explícitos

Solo HTTPS contra los recursos siguientes, mediante el cliente autorizado:

| Etapa | GET máximos | Selección |
| --- | ---: | --- |
| Operaciones reserva | 2 | `/stock/fulfillment/operations/search`, vendedor e inventario conocidos, fechas fijadas, `type=WITHDRAWAL_RESERVATION`, `limit=20`; segunda página solo con scroll recibido. |
| Operaciones entrega | 2 | Misma búsqueda, `type=WITHDRAWAL_DELIVERY`; mismas restricciones. |
| Detalle de operación | 4 | `/stock/fulfillment/operations/{operation_id}`: hasta dos IDs **recibidos** de cada tipo, distintos y del vendedor. |
| Inventario | 1 | `/inventories/{inventory_id}/stock/fulfillment`: solo inventario conocido/recibido. |
| Publicación | 1 | `/items/{item_id}`: solo publicación conocida o devuelta explícitamente por el inventario. |
| **Total máximo físico** | **10** | No retries automáticos, rutas adicionales, llamadas de facturación ni año completo. |

Máximo diez GET físicos, uno por segundo como techo, deadline global de tres
minutos y timeout por request de diez segundos. El límite **incluye** cualquier
reintento implícito: desactivarlos o descontarlos antes de ejecutar. El presupuesto
no gastado no autoriza otras rutas. Scroll no se imprime ni persiste como evidencia.

La cuenta, fechas y recursos se fijan antes de ejecutar. Un 401, 403, 429, 5xx,
timeout, vendedor inconsistente o respuesta inválida detiene la prueba sin reparar
permisos/configuración ni mutar cuentas. No seguir URLs arbitrarias de respuestas.
Si un recurso documentado no está permitido por el cliente actual, registrar
`bloqueado por permiso` y proponer autorización separada; no cambiar manifest/seed
ni intentar otro cliente para evadir la denegación.

Páginas vacías, scroll no terminal al agotar dos páginas o ausencia de referencias
significan **muestra insuficiente**, no "sin Full", no "sin retiros" y no cobertura.
No ampliar fechas, inventarios, tipos o presupuesto sin nueva aprobación.

### Evidencia y sanitización

- Dentro del contexto aprobado, conservar solo nombres/tipos de campos, tipos de
  operación, cantidades necesarias, fechas y consistencia de joins.
- La salida visible es un resumen de status, presupuesto consumido, presencia de
  campos y conclusiones. Sin cuerpos completos, tokens, cookies, headers, códigos
  OAuth, URLs con credenciales, PII, dirección, título sensible o identificadores
  reales innecesarios. No imprimir excepciones HTTP con request/header completos.
- Si se autoriza conservar una muestra para pruebas locales, anonimizar IDs con
  sustitución determinista consistente entre referencias (preservando tipos y
  relación, no inventando una relación ausente). Omitir PII y secretos. Distinguir
  claramente fixture derivado de muestra de fixture documental/sintético.
- Comprobar por separado que la referencia coincide con el retiro/bulto mostrado
  al operador. Encontrar un campo llamado `withdrawal_id` no prueba su nivel.

### Criterio de salida y siguiente cambio local

**Si aporta evidencia suficiente:** documentar paths y semántica de cada campo,
usar identidades explícitas sin derivación por prefijo, escribir primero prueba
fallida de mapeo y probar adquisición → Mongo canónico → handler real RETIROS con
validador. Incluir cancelación parcial, entrega del mismo detalle, deduplicación,
actualización, rechazo de vendedor ajeno y conservación de legacy. La muestra
permite el mapeo, **no** certificar doce meses sin escaneo y prueba de rango.

**Si no aporta la jerarquía o cantidad/fecha de solicitud:** detenerse y solicitar
al soporte de Mercado Libre el contrato/recurso público autorizado que expone
solicitud y bulto con sus relaciones; adjuntar únicamente diagnóstico sanitizado.
No crear una ruta `/withdrawals/...` por intuición. Mantener Full como bloqueado
por contrato y permitir avanzar al resto del onboarding.

Texto sugerido de aprobación: “Autorizo exclusivamente la comprobación Full de
este documento para [vendedor], [inventario] y [fechas UTC], desde el contexto
runtime acordado, máximo diez GET físicos de lectura. No autorizo cambios de
permisos, escrituras, descargas históricas amplias, builds ni despliegues”.

## 6. Ubicaciones relevantes

- `modules/sheets/src/zeler_sheets/onboarding_sources.py`: adquisición de operaciones.
- `modules/sheets/src/zeler_sheets/source_gated_read_model_writers.py`: importación
  legacy; no es prueba del contrato API.
- `modules/sheets/src/zeler_sheets/formulas/handlers_remaining_phase4.py`:
  `sheetseller_retiros`, handler normal y protección exacta de rango.
- `modules/sheets/src/zeler_sheets/formulas/read_models.py`: lector de filas y cobertura.
- `core/src/zeler_platform_core/cli/export_schemas.py`: validador canónico.
