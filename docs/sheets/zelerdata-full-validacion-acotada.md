# RETIROS Full: contrato faltante y comprobación acotada

Fecha: 2 de octubre de 2026. Estado: **bloqueado por evidencia de fuente concreta**,
no por un fallo global de onboarding. Esta propuesta **no autoriza ni ejecuta**
consultas autenticadas, cambios de permisos, escritura de datos ni producción.

## 1. Resultado de la investigación local

Se inspeccionaron el adquiridor existente, el importador legacy, el esquema
canónico y el handler normal `ZELERDATA_RETIROS`. La investigación externa se
limitó a cuatro lotes de búsqueda en documentación oficial; los accesos directos
a algunas páginas devolvieron 403. No hubo llamadas autenticadas a Mercado Libre.
No se prolongará esta investigación sin una muestra concreta o un contrato nuevo.

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

## 3. Autorización propuesta: una muestra real, máximo diez GET

### Datos mínimos que necesita el operador

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

## 4. Ubicaciones relevantes

- `modules/sheets/src/zeler_sheets/onboarding_sources.py`: adquisición de operaciones.
- `modules/sheets/src/zeler_sheets/source_gated_read_model_writers.py`: importación
  legacy; no es prueba del contrato API.
- `modules/sheets/src/zeler_sheets/formulas/handlers_remaining_phase4.py`:
  `sheetseller_retiros`, handler normal y protección exacta de rango.
- `modules/sheets/src/zeler_sheets/formulas/read_models.py`: lector de filas y cobertura.
- `core/src/zeler_platform_core/cli/export_schemas.py`: validador canónico.
