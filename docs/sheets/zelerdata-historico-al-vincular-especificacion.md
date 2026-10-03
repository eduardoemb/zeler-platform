# ZelerData: histórico automático al vincular una cuenta

**Documento de trabajo para implementar, probar y validar el flujo completo.**
Fecha de preparación: 2 de octubre de 2026.
Estado: especificación de entrega; **no acredita implementación ni aceptación productiva**.

## 1. Resultado esperado y lectura rápida

Cuando una cuenta se vincule mediante OAuth normal, ZelerData debe iniciar en
segundo plano la carga del histórico recuperable de las fuentes incluidas aquí,
conservar lo adquirido y mantenerlo actualizado. El objetivo inicial es cubrir
los últimos **12 meses calendario cuando la fuente lo permita**, no obligar al
usuario a solicitar mes por mes ni prometer el mismo horizonte para toda API.

El sistema debe ser útil aunque existan excepciones puntuales. Si falta el detalle
de 1 de 10 000 registros, no debe bloquear indefinidamente toda la incorporación,
reiniciar el año completo ni fingir que ese registro se adquirió.

### Ruta de lectura para el agente

1. Leer alcance y autoridad (§2), inventario real (§3) y reglas de completitud (§5).
2. Trazar OAuth, bootstrap y actualización actual antes de elegir qué modificar.
3. Implementar por partes con TDD, aprovechando adquiridores existentes (§6–8).
4. Ejecutar la matriz local aislada y los controles del repositorio (§9).
5. Preparar un piloto y un rollout acotados; solicitar solo autorizaciones faltantes (§10–11).
6. Entregar evidencia por fuente, datos pendientes y limitaciones honestas (§12–13).

**No es necesario rehacer ZelerData ni construir un nuevo producto.** El trabajo
central es integrar correctamente adquisición inicial, dependencias, progreso,
excepciones y actualización continua para todas las cuentas elegibles.

## 2. Alcance, autoridad y exclusiones

### 2.1 Fuentes incluidas

| Fuente histórica | Resultado útil |
| --- | --- |
| Órdenes y ventas | Órdenes, líneas, fechas, estados y datos necesarios para las fórmulas existentes. |
| Comisiones de venta | `sale_fee` de cada línea, con su procedencia; no sustituirlo por una tarifa actual. |
| Preguntas y respuestas | Preguntas recuperables, respuestas y fechas necesarias para tablas y KPI. |
| Envíos vinculados y costos | Detalle, relación con órdenes, costo real y campos necesarios para fórmulas existentes. |
| Reclamos y devoluciones | Adquisición conjunta de reclamos, devoluciones y órdenes relacionadas. |
| Mensajes posventa | Histórico recuperable por órdenes/packs, persistido sin efectos de lectura ni envío. |
| Retiros Full | Adquisidor API y mapeo verificable hacia la fórmula `ZELERDATA_RETIROS` existente. |

Las métricas de ventas, unidades, rankings, compradores, días desde última venta
u órdenes por SKU son **consumidores derivados**, no nuevas fuentes históricas.
Cancelaciones y estados de reembolso pertenecen a órdenes/reclamos, con las
limitaciones de descubrimiento y detalle descritas más adelante.

### 2.2 Fuera de alcance

- Reconstruir retroactivamente precios, stock, estados o competencia observados.
- Visitas, facturación, cargos contables, liquidaciones o una integración Mercado Pago.
- Nuevas fórmulas/productos o una interfaz paralela a `zeler-app`.
- Integrar todos los movimientos Full: incluir solo los necesarios para retiros.
- Reemplazar retiros Full por cualquier movimiento de inventario con nombre parecido.
- Historial completo de tracking/estados de envío si no lo requiere el contrato actual.
- Obtener datos restringidos mediante scraping, OAuth alternativo o permisos ajenos.
- Adquirir ahora todo el histórico de HOPEMOB por el solo hecho de escribir este documento.

Que una API ofrezca visitas, facturación o movimientos Full no los convierte en
fallos de las 52 fórmulas actuales ni los incorpora implícitamente a esta entrega.
Los movimientos Full recuperables son eventos de fuente: no confundirlos con
inventar una cronología de stock a partir del stock actual.

### 2.3 Autoridad operativa

La autorización inmediata es **crear este documento**. No se ejecutan adquisiciones,
backups, pruebas contra producción ni modificaciones de código por redactarlo.
El agente receptor debe confirmar que su encargo autoriza implementación local;
una vez autorizada, completará código y pruebas sin pedir permisos innecesarios.

Este documento no autoriza por sí mismo:

- Commit, push, ramas, worktrees o PR.
- Cloud Builds, despliegues, cambios de validadores/índices o reinicios.
- Vincular/revincular una cuenta real, forzar bootstrap o manipular tokens.
- Backups productivos, restauraciones, cambios de colas o adquisiciones pagadas.
- Escribir fórmulas/celdas en Google Sheets o repetir pilotos fallidos automáticamente.

Antes de ejecutar cualquiera de esas acciones, verificar el alcance autorizado
en la conversación vigente. Una autorización histórica de otra entrega no basta.
No heredar un presupuesto de consultas ni un permiso de un diagnóstico anterior.

**La autorización operativa del agente no es una interacción mensual del producto.**
En el producto terminado, OAuth más la política de incorporación aceptada debe
activar automáticamente un plan acotado: no pedir permiso humano por cada cuenta,
mes o ventana normal. Si un adquiridor exige hoy autorización por run, adaptar
esa frontera a una autoridad de plan persistida, con vendedor, fuentes, corte,
presupuesto y estado de elegibilidad; no eliminar ni saltar sus controles.

### 2.4 Política de trabajo

Seguir [AGENTS.md](../../AGENTS.md), las [lecciones](../lessons/README.md) y el
[runbook de despliegue](../deploy.md). Leer especialmente L-009, L-015, L-016,
L-021, L-022, L-023, L-027 y L-028; contrastar notas antiguas con código actual.
Aplicar también L-010: distinguir los clientes de descubrimiento y detalle con
sus permisos reales, especialmente al incorporar Full.
Trabajar en checkout/rama seleccionados, preservando cambios ajenos y secretos.
Aplicar la ruta de implementación vigente; este documento no crea un ciclo SDD
ni activa revisiones automáticas o herramientas opt-in en nombre del usuario.

## 3. Inventario de código: reutilizar antes de sustituir

Las referencias se verificaron en el checkout durante la preparación. Las líneas
pueden desplazarse: usar los símbolos indicados. Código y documentos históricos
no prueban qué flags, vendedores o imágenes están activos hoy en producción.

### 3.1 Flujo de entrada y actualización

| Pieza | Evidencia local | Comportamiento actual relevante |
| --- | --- | --- |
| OAuth → evento | [oauth/events.py](../../gateway/src/zeler_gateway/oauth/events.py), `emit_accounts_linked`, líneas 19–65 | Crea trabajo bootstrap y publica `accounts.linked`; omite relink si ya existe pending/running/succeeded salvo force. |
| Despacho | [dispatcher.py](../../bootstrap/src/zeler_bootstrap/dispatcher.py), `handle_accounts_linked`, 33–81 | Reclama trabajo pendiente y lanza job por vendedor. |
| Stages iniciales | [runner.py](../../bootstrap/src/zeler_bootstrap/runner.py), `build_default_stages`, 196–207 | Accounts, items, orders, questions, messages, shipments, claims. |
| Cliente bootstrap | [runtime.py](../../bootstrap/src/zeler_bootstrap/runtime.py), `RuntimeGatewayClient.get`, 285–297 | Una solicitud; no agrega paginación automáticamente. |
| Plan histórico | [pilot_history_backfill.py](../../modules/sheets/src/zeler_sheets/pilot_history_backfill.py), 72–99 | Planifica 12 meses, pero solo encola órdenes/preguntas. Items/shipments quedan sin ruta histórica en ese plan. |
| Refresh | [consumer.py](../../modules/sheets/src/zeler_sheets/consumer.py), `build_zelerdata_refresh_supervisor`, 1598–1685 | Exige flags y vendedores explícitos; no es onboarding universal. |
| Incremental órdenes | [modification_recovery.py](../../modules/sheets/src/zeler_sheets/modification_recovery.py), `fetch_modification_page`, 52–87 | Búsqueda por `order.date_last_updated`, reutilizable; trabajador actual es opt-in. |

No se encontró un consumidor Sheets de `bootstrap.completed` que convierta por
sí solo cualquier cuenta nueva en un plan anual completo. No asumir que dicho
evento resuelve el enlace faltante sin verificar su consumo efectivo.

### 3.2 Adquisidores y brechas por fuente

| Familia | Implementación reutilizable | Falta para incorporación automática |
| --- | --- | --- |
| Órdenes/comisiones | [historical_meli_backfill.py](../../modules/sheets/src/zeler_sheets/historical_meli_backfill.py), `_search_orders`, `_build_order_search_path`; [history_orders.py](../../modules/sheets/src/zeler_sheets/history_orders.py) | Conectar plan durable a cada cuenta elegible; completar dependencias y excepciones sin limitarse al bootstrap de 90 días/una página. |
| Preguntas/respuestas | [history_questions.py](../../modules/sheets/src/zeler_sheets/history_questions.py), adquisición por search/detail; [event_persistence.py](../../modules/sheets/src/zeler_sheets/event_persistence.py), `_canonical_question_document` | Usar el escritor completo que preserva respuestas, no solo el stage básico de una página que las omite. |
| Envíos/costos | [historical_meli_backfill.py](../../modules/sheets/src/zeler_sheets/historical_meli_backfill.py), `_fetch_shipments`; [recovery_worker.py](../../modules/sheets/src/zeler_sheets/formulas/recovery_worker.py), `_shipments` | Encadenar IDs de todas las órdenes adquiridas; deduplicar y completar por campo. |
| Reclamos/devoluciones | [devoluciones_reconciliation.py](../../modules/sheets/src/zeler_sheets/devoluciones_reconciliation.py), `GatewayDevolucionesSource`, `collect_devoluciones_snapshot` | Generar plan inicial e incremental automático autorizado por incorporación; el runner actual solo avanza runs ya autorizados. |
| Mensajes posventa | [stages.py](../../bootstrap/src/zeler_bootstrap/stages.py), `MessagesStage`, 498–548 | Descubrimiento completo por packs, paginación, checkpoints, cobertura y actualización canónica. |
| Retiros Full | [source_gated_read_model_writers.py](../../modules/sheets/src/zeler_sheets/source_gated_read_model_writers.py), `run_source_gated_read_model_import`, `_full_withdrawal_documents` | Hoy transforma `withdrawal_records` locales; falta adquiridor ML y mapeo explícito API → contrato. |

La fórmula RETIROS ya lee `sheets_full_withdrawals` y exige rango reconciliado:
[handlers_remaining_phase4.py](../../modules/sheets/src/zeler_sheets/formulas/handlers_remaining_phase4.py),
`sheetseller_retiros`, líneas 526–547. El importador legacy no demuestra que se
estén descargando operaciones Full desde Mercado Libre.

### 3.3 Endpoints de fuente usados o por integrar

| Familia | Fuente técnica | Precaución |
| --- | --- | --- |
| Órdenes | `/orders/search`, `/orders/{id}` | Búsqueda paginada y detalle; `sale_fee` no es factura/liquidación. |
| Preguntas | `/questions/search`, `/questions/{id}?api_version=4` | Preservar respuesta/estado; reconciliar omisiones y 404 conocidos. |
| Envíos | `/shipments/{id}/orders`, `/shipments/{id}`, `/shipments/{id}/costs` | Validar vendedor, relación y costo del vendedor correcto. |
| Reclamos | `/post-purchase/v1/claims/search`, `/post-purchase/v1/claims/{id}` | No suponer que cada reclamo es una devolución. |
| Devoluciones | `/post-purchase/v2/claims/{id}/returns` | Confirmar relaciones y órdenes; mantener prueba conjunta. |
| Mensajes | `/messages/packs/{pack}/sellers/{seller}` | Lectura con `mark_as_read=false`; nunca enviar mensajes al importar. |
| Retiros Full | API de operaciones de stock Full por fechas/scroll y detalles pertinentes | Fijar ruta, filtros y contrato con documentación oficial antes de implementar; no adaptar por similitud de nombres. |

El buscador histórico de órdenes actual no impone `paid`. Sin embargo, las órdenes
canceladas omitidas por search solo se revisitan por ID cuando ya son conocidas
localmente. Véase `history_orders.py:343–355` y
[test_history_orders.py](../../modules/sheets/tests/test_history_orders.py),
`test_known_cancelled_is_staged_once_without_excluding_history`.
No declarar completo el universo de cancelaciones desconocidas si la fuente no
ofrece cómo descubrirlas. Un estado `partially_refunded` tampoco certifica todos
los movimientos monetarios del reembolso.

## 4. Requisitos verificables

Los IDs siguientes son trazabilidad de esta especificación, no nombres de API
ni un protocolo nuevo. Los esquemas/nombres definitivos deben respetar el dominio
existente y documentarse en la entrega técnica.

| ID | Requisito | Evidencia mínima |
| --- | --- | --- |
| H-01 | La vinculación normal inicia un plan histórico durable por cuenta elegible, fuera del request OAuth. | Evento → plan/trabajos en cuenta vacía; OAuth no espera toda la descarga. |
| H-02 | Repetición de evento/relink no duplica ni destruye avance; completa faltantes cuando corresponde. | Duplicados, carrera y relink con plan existente. |
| H-03 | Corte inicial estable y 12 meses calendario donde la API lo permita; límites por fuente explícitos. | Fechas de calendario, zona, retención y huecos. |
| H-04 | Paginación/scroll exhaustivos o limitación explícita; nunca “primera página = histórico completo”. | Varias páginas, límites grandes, truncamiento y fuente cambiante. |
| H-05 | Reanudar desde progreso confirmado; deduplicar identidad/fuente y proteger escrituras concurrentes. | Reinicio en distintas fases y dos vendedores simultáneos. |
| H-06 | Preservar hechos y cobertura previos; no sobrescribir junio al adquirir otro rango. | Baseline y consultas anteriores/después. |
| H-07 | Estados independientes por fuente y dependencias mínimas por registro. | Caída de una fuente no inutiliza las demás. |
| H-08 | Excepciones puntuales producen utilidad con observaciones y pendientes durables, no bloqueo eterno. | Caso 9 999 disponibles + 1 faltante. |
| H-09 | No inventar ceros, filas, exactitud, respuestas ni cobertura para tolerar fallos. | Lectores/agregados parciales y rango sin prueba. |
| H-10 | Contratos exactos, incluidos certificados DEVOLUCIONES, no se degradan silenciosamente. | Consulta exacta sigue fallando cerrada donde falte prueba. |
| H-11 | Actualización por notificaciones e incrementales/catch-up; no repetir el año en cada ciclo. | Dos ciclos reales con novedades/cambios después del corte. |
| H-12 | Cuotas, concurrencia y reintentos acotados; pausa/revocación detienen nuevas adquisiciones. | 429/5xx/auth, presupuestos y cambio de elegibilidad. |
| H-13 | Retiros Full usan fuente auténtica, mapeo y cobertura propios compatibles con RETIROS. | Fixtures API, paginación, cantidades/IDs/fechas y prueba de lector. |
| H-14 | No efectos secundarios de comunicación, lectura de mensajes o autorización. | No enviar/responder/marcar leído ni cambiar tokens/permisos manualmente. |
| H-15 | Estado y excepciones visibles sin datos sensibles; muestras no equivalen a cobertura. | Estado backend/consumidor y reporte sanitizado. |
| H-16 | Piloto y despliegue reversibles dentro de autorización explícita, preservando datos nuevos. | Backup/restauración aislada, procedencia y rollback compatible. |
| H-17 | El producto admite automáticamente planes bajo política de onboarding, sin autorización manual por ventana. | Plan acotado válido avanza; vendedor/fuente/presupuesto fuera de plan se rechazan. |
| H-18 | El volumen anual progresa y su cobertura se mantiene dentro de los presupuestos reales, sin bloquear tráfico vivo. | Prueba de volumen, duraciones y renovación a escala; disponibilidad progresiva y justicia entre cuentas. |

## 5. Completitud útil sin fingir perfección

### 5.1 Tres situaciones diferentes

| Situación | Tratamiento requerido | Qué no hacer |
| --- | --- | --- |
| Falló enumeración/paginación y no sabemos cuántos registros faltan | Marcar cobertura del tramo/fuente desconocida o pendiente; reanudar acotadamente. | Reportar 99.9% o “solo falta uno” sin denominador fiable. |
| Enumeración fiable, pero falta detalle de IDs concretos | Conservar IDs/excepciones, publicar lo independiente y ofrecer estado parcial explícito. | Repetir todo el año o bloquear todo el onboarding por un detalle. |
| Campo opcional ausente en registro adquirido | Conservar registro y disponibilidad por campo; usar NA/ausencia documentada. | Invalidar ventas porque falta dirección opcional o sustituir costo ausente por cero. |

La distinción se aplica por fuente, tramo, registro y campo según corresponda.
Un fallo de relación que impide atribuir una devolución no es “campo opcional”.
Un fallo de autorización entre vendedores es crítico: detener la operación
insegura y evitar publicación afectada; no es candidato a tolerancia estadística.

### 5.2 Estado agregado y pendientes

Adoptar un estado conceptual **`ready_with_observations`** para una incorporación
útil con excepciones identificadas. El nombre es conceptual hasta comprobar los
contratos existentes; no añadir valores incompatibles a estados compartidos.

Separar al menos estos significados:

- Trabajo en curso o pendiente de capacidad/reintento.
- Disponible con cobertura comprobada.
- Disponible con observaciones/parcialidad explícita.
- Temporalmente inaccesible por fuente o autorización.
- No aplica a esa cuenta, confirmado por una condición válida.
- Horizonte no recuperable o restricción documentada de la fuente.
- Error permanente concreto que requiere intervención.

No clasificar un 403 como “no aplica” sin evidencia; puede ser falta de permiso.
No clasificar un período vacío como “terminó el histórico”. Una búsqueda vacía
completa puede acreditar cero resultados en ese período, no en períodos vecinos.

Los pendientes conservan causa, identidad segura, alcance, último intento,
próximo intento o acción necesaria y presupuesto consumido. Después del límite,
quedan visibles sin bucle automático infinito ni reinicio global del plan.
No usar un porcentaje mágico universal —por ejemplo, 99.9%— como criterio de éxito.

### 5.3 Lecturas, fórmulas y agregados

- Una suma de filas disponibles no debe etiquetarse como total exacto del período.
- Exponer parcialidad de forma visible y compatible, no solo en logs privados.
- Si la fórmula exacta no admite parciales, mantener su resultado no disponible
  para el rango afectado y permitir las consultas independientes sí cubiertas.
- Antes de introducir una salida parcial, definir cómo la reconocerán API,
  Apps Script y usuario; probar la compatibilidad y no cambiar tablas silenciosamente.
- Mantener separados registros adquiridos, enumerados, verificados, omitidos,
  pendientes y fuera del horizonte. No confundir respuestas HTTP con hechos persistidos.
- Los rangos totalmente cubiertos siguen funcionando aunque exista un hueco fuera.
- No retirar cobertura previa sana por un intento nuevo incompleto.

DEVOLUCIONES exige prueba conjunta de fuentes y relaciones. **No reducir la
exigencia de sus certificados para poner el onboarding en verde.** El onboarding
puede quedar útil con observaciones mientras un rango de DEVOLUCIONES conserva
su respuesta exacta no disponible hasta tener prueba suficiente.

**Aceptación funcional de H-08:** no basta cambiar el estado a “con observaciones”
si los 9 999 registros válidos siguen siendo inutilizables. Probar su consumo real
mediante lectores compatibles y limitar el bloqueo a la métrica/rango dependiente
del faltante. Cuando se necesite lectura parcial, definirla explícitamente en los
contratos existentes, sin crear nuevas fórmulas ni presentar su agregado como
exacto. Si un contrato exacto obliga a bloquear un rango amplio, justificar ese
límite y demostrar qué consultas independientes permanecen útiles.

## 6. Diseño mínimo de incorporación

### 6.1 Disparador normal e idempotencia

1. Conservar OAuth legítimo y la identidad canónica de cuenta/vendedor.
2. Emitir/admitir de manera durable la intención de incorporación al vincular.
3. Crear o recuperar un plan por vendedor, versión de contrato y corte estable.
4. Hacer la adquisición en workers/jobs; devolver control al usuario sin esperar meses.
5. Separar “vinculación correcta” de “carga histórica terminada”.

El comportamiento actual de `emit_accounts_linked` omite un bootstrap succeeded;
el camino force reemplaza el documento del job y sus checkpoints. **No usar force
como solución de relink ni resetear el job para rellenar faltantes.** Diseñar una
admisión idempotente que consulte progreso/cobertura y preserve los registros previos.

Probar cuentas vacías, cuentas ya usadas y cuentas con historial parcial antes de
vincular. Una revinculación puede recuperar acceso o plan pendiente, pero no debe
borrar historia, duplicar cuentas, reasignar vendedores ni cambiar credenciales a mano.

### 6.2 Plan por fuente y límites de tiempo

Fijar un corte inicial reproducible y restar 12 meses **calendario**, no 365 días.
Guardar zona relevante y convertir límites a intervalos internos inequívocos.
Probar años bisiestos, fin de mes, cambio de año y límites inclusivos/exclusivos.
No hacer depender identidades de trabajo de la hora de cada reintento.

Cada fuente define su horizonte comprobado, filtros y máximo por solicitud.
El máximo de días por petición no es necesariamente retención total. Partir por
ventanas internas adaptadas a paginación/cuota; no exponer meses como obligación
manual. Priorizar utilidad reciente y el borde antiguo en riesgo de dejar de estar disponible.

Para cuentas creadas hace menos de un año, no inventar doce meses de actividad.
Para una fuente con menor retención, mostrar ese límite y conservar lo que sí
se pudo recuperar. No prometer recuperar cancelaciones nunca enumerables.

### 6.3 Dependencias que no bloquean todo

Órdenes alimentan IDs de envíos y packs de mensajes. Reclamos pueden descubrir
órdenes vinculadas fuera de una ventana ordinaria: hidratarlas por necesidad,
sin ampliar arbitrariamente el histórico de todas las fuentes.

- Deduplicar envíos/packs compartidos entre varias órdenes.
- Persistir y completar relaciones de forma verificable, con propiedad del vendedor.
- Un pack sin mensajes no debe impedir órdenes o comisiones válidas.
- Un envío sin costo no convierte su costo en cero ni invalida datos ajenos.
- Una orden faltante deja pendientes sus dependencias, no todos los registros.
- Preguntas y retiros Full no deben esperar a que termine todo el año de órdenes.

### 6.4 Reutilización y límites de arquitectura

Reutilizar gateway/proxy, pacing, colas, leases, checkpoints y escritores canónicos.
No crear nuevos microservicios ni un framework de sincronización si las piezas
existentes permiten resolver esta entrega con adaptaciones acotadas.
Revisar [permisos del registro](../../infra/mongo/seeds/module_registry.admin_clients.json)
por endpoint y cliente; no compartir un cliente privilegiado para ocultar un 403.
Añadir modelos/esquemas solo donde la semántica nueva lo necesite.

Los adquiridores nuevos de mensajes/Full deben cumplir los mismos controles, no
crear un camino directo a ML ni saltarse límites por llamarse bootstrap.
No heredar supuestos `pilot` o IDs fijos en el comportamiento general de cuentas.
La adopción de nuevos vendedores sigue sus límites, permisos y elegibilidad.

## 7. Conservación y actualización después del corte

Conservar historia ya adquirida aunque deje de ser consultable en la fuente.
Registrar qué se adquirió y cuándo se verificó; no inventar frescura para datos
que ya no pueden volver a consultarse. Distinguir hecho histórico retenido de
estado mutable que necesita actualización.

### 7.1 Trabajo incremental

- Mantener las notificaciones existentes con persistencia/idempotencia verificadas.
- Usar el escaneo de modificación de órdenes existente cuando aplique.
- Guardar watermarks solo tras persistir/admitir de forma durable el trabajo cubierto.
- Aplicar solapamiento y deduplicación para cambios tardíos y bordes de precisión.
- Revisitar reclamos/devoluciones abiertos y cambios admitidos por su API.
- Incorporar nuevas órdenes, preguntas, mensajes y retiros tras el corte inicial.
- Hacer catch-up acotado tras una interrupción; no repetir automáticamente el año.

La renovación de un certificado local solo comprueba hechos almacenados: **no
prueba un incremental de fuente**. Dos ciclos de aceptación deben demostrar
trabajo real de actualización, además de que las pruebas de cobertura no expiren.

### 7.2 Reintentos, capacidad y elegibilidad

Presupuestar llamadas, concurrencia, trabajo por ciclo y pendientes por vendedor.
Dar espacio a tráfico vivo y otras cuentas. Evitar sweeps de vendedor completo
más frecuentes que su duración, conforme a L-021.

429 respeta la espera de fuente; 5xx/transporte tienen backoff y límites.
Errores de OAuth siguen el flujo normal de renovación, sin copiar tokens ni
cambiar permisos. Suspensión/revocación bloquea nuevas adquisiciones; reanudar
solo tras recuperar elegibilidad y conservar el avance previo.

No reabrir terminales ni reiniciar intentos indefinidamente en cada reinicio.
Mantener justicia entre fuentes y vendedores; una fuente caída no consume todo
el presupuesto de una cuenta ni bloquea otra cuenta.

### 7.3 Capacidad anual y disponibilidad progresiva

No extrapolar una prueba de pocos días a doce meses. En el código consultado,
`publish_quota_certificate` publica un certificado por **run completo**, no por
cada ventana interna. `renew_due_certificates` limita un lote a 20 certificados y
30 segundos, con timeout de 5 segundos por certificado; la vigencia es de 30
minutos y el intervalo predeterminado de refresh es de 900 segundos. Comprobar
estos valores y la configuración efectiva antes de diseñar la partición.

Un certificado anual grande puede ser caro de verificar; demasiados certificados
pequeños pueden agotar la renovación. No elegir una partición solo por comodidad
mensual ni subir límites sin medir. Probar volumen representativo de un año y
crecimiento de cuentas con Mongo aislado y fuente simulada, incluyendo:

- Tiempo/memoria por adquisición y verificación, backlog y tiempo entre renovaciones.
- Conservación de cobertura útil durante al menos dos ventanas de vigencia,
  con reloj controlado cuando corresponda, sin hambre de otras cuentas/fuentes.
- Publicación progresiva de tramos demostrados: no esperar al último detalle del
  año para ofrecer todo lo que ya puede usarse de forma segura.
- Deadlines de planes, runs y leases compatibles con pausas, pacing y reanudación;
  no estimar duración total sumando únicamente tiempos HTTP y omitiendo esperas.
- Ausencia de releer todo el histórico en cada ciclo incremental; mantener
  mediciones separadas para adquisición remota y verificación local.

Registrar volumen ensayado y límites medidos. No convertir esa prueba local en
una promesa universal de tiempo de carga ni en autorización de carga productiva.

## 8. Integración de retiros Full

Antes de implementar, documentar el contrato oficial exacto de operaciones Full,
sus filtros por vendedor/fecha, scroll, detalles y tipos que corresponden a retiros.
Verificar elegibilidad de cuenta, permisos y la diferencia entre operación,
retiro, bulto/detalle, inventario, publicación y SKU.

El mapeo debe acreditar al menos:

- Identidad estable del retiro y de su detalle, sin inventar IDs de proveedor.
- Producto/inventario y pertenencia al vendedor.
- Fecha relevante del contrato y zona, cantidad solicitada y fecha de entrega si existe.
- Tipos elegibles: no mezclar venta, devolución, descarte o retiro como equivalentes.
- Una reserva o cancelación de reserva de retiro no demuestra un retiro entregado.
- Deduplicación de páginas/scroll y actualizaciones de operaciones existentes.
- Tratamiento explícito de valores que la fuente no exponga.

Si la API no permite poblar algún campo obligatorio del contrato actual, registrar
la incompatibilidad y resolver el contrato/mapeo antes de certificar el rango.
No copiar la etiqueta `legacy_history_import` para datos adquiridos por API.
Preservar registros legacy existentes y su procedencia; definir su convivencia.

Probar las salidas contra el lector real de RETIROS y sus requisitos de cobertura,
no solo que un JSON de API se inserte en Mongo. Un resultado “no aplica” para una
cuenta sin Full requiere evidencia, no tratar todo error de acceso como ausencia.

## 9. TDD y verificación local aislada

### 9.1 Preparación

Verificar Git y preservar cambios ajenos antes de editar. Leer los tests vigentes
y demostrar primero el fallo que introduce cada cambio no trivial de comportamiento.
Usar exclusivamente Mongo de desarrollo/pruebas verificado y datos desechables.
`conftest.py` acepta `MONGO_URI`: **no ejecutar la suite heredando producción**.
Necesidades de replica set y puertos deben seguir L-012; no usar datos locales ajenos.

### 9.2 Matriz mínima trazable

| Prueba | Caso y aserción principal | Requisitos |
| --- | --- | --- |
| T-01 | Cuenta vacía + evento OAuth: plan automático, fuentes elegibles, request no bloqueado por adquisición. | H-01, H-03 |
| T-02 | Cuenta existente con junio y huecos: relink completa faltantes sin borrar certificados/hechos. | H-02, H-06 |
| T-03 | Evento duplicado, dos dispatchers y reinicio: un trabajo efectivo por unidad lógica. | H-02, H-05 |
| T-04 | Calendario, leap day, fin de mes, zonas y límites: sin duplicados ni día perdido. | H-03 |
| T-05 | Páginas grandes, subdivisión, scroll, total cambiante y página vacía prematura. | H-04, H-05 |
| T-06 | 9 999 detalles útiles + 1 fallo puntual: consumo real de los válidos, ready_with_observations y pendiente durable. | H-07–H-10 |
| T-07 | Enumeración desconocida: no denominador inventado ni total exacto; otras fuentes utilizables. | H-07, H-09 |
| T-08 | Pregunta enumerada con detalle 404 y pregunta local omitida: aplicar reglas comprobadas de reconciliación. | H-04, H-08 |
| T-09 | Cancelada conocida ausente de search y desconocidas no enumerables: evidencia/limitación correctas. | H-04, H-09 |
| T-10 | Envío/pack compartido, orden ausente y costo opcional faltante: dedup y dependencias puntuales. | H-05, H-07–H-09 |
| T-11 | Pregunta ANSWERED sin respuesta válida: no inventar KPI ni respuesta; conservar pendiente. | H-08, H-09 |
| T-12 | Reinicio después de fetch, escritura, checkpoint y publicación: reanudar sin perder/duplicar. | H-05 |
| T-13 | Dos vendedores, eventos concurrentes y adquisición vieja: no cruces ni pisar hechos recientes. | H-05, H-12 |
| T-14 | 429, 5xx, timeout, auth inválida, pausa y revocación: límites y suspensión comprobables. | H-08, H-12 |
| T-15 | Full: tipos, scroll, IDs, cantidades, fechas, actualizaciones, no aplica y errores de permisos. | H-13 |
| T-16 | Nuevos hechos/cambios después del corte: dos incrementales, watermark, solapamiento y catch-up. | H-11 |
| T-17 | Prueba expirada/hueco DEVOLUCIONES: fail-closed exacto; junio independiente sigue válido. | H-06, H-10 |
| T-18 | Parciales en handler y consumidor: visibles, sin cero falso ni exactitud falsa. | H-09, H-10, H-15 |
| T-19 | Mensajes no enviados/no marcados leídos; sin escrituras manuales de tokens o identidad. | H-14 |
| T-20 | Restauración en destino aislado conserva integridad; rollback no pisa tokens/hechos posteriores. | H-16 |
| T-21 | Plan automático autorizado por política: avanza sin prompts por ventana, pero rechaza trabajo fuera de alcance. | H-01, H-12, H-17 |
| T-22 | Volumen anual y varias cuentas: avance/publicación progresivos, renovación dentro de vigencia y presupuesto, sin bloquear tráfico vivo; medir tiempos/backlog con fuente simulada y Mongo aislado. | H-05, H-06, H-12, H-18 |

No exigir que un escenario local use una cuenta real. Simular fuente y usar Mongo
real aislado donde importen transacciones, validadores, carreras y persistencia.
No fabricar datos productivos para completar una matriz.

### 9.3 Controles finales del repositorio

Ejecutar y reportar los cuatro controles cuando termine el código:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

Además, según cambios efectivos:

```bash
uv run python -m infra.lint.check_direct_meli .
uv run python -m zeler_platform_core.cli.export_schemas infra/mongo/schemas --check
```

Reportar fallos preexistentes y regresiones por separado; no reducir el alcance
del control para declarar éxito. Repetir controles afectados después de corregir.
Para esta entrega documental, validar coherencia, enlaces y alcance, no ejecutar
pruebas de código como si se hubiera implementado ya.

## 10. Preparación y ejecución de un piloto real

### 10.1 Propuesta antes de tocar producción

La propuesta debe nombrar vendedor/cuenta, destino, fuente y fechas por fuente,
modo nuevo/relink, imágenes/commit si cambian, presupuesto máximo de consultas,
concurrencia, duración estimada, reglas de pausa, criterios de parada y evidencia.
Separar la autorización de backup, despliegue, OAuth/piloto y escrituras en Sheets.
Obtener autorización del alcance completo necesario, sin preguntas repetidas para
operaciones ya aprobadas y sin extender el alcance si aparece una dificultad.

Medir baseline sanitizado: coberturas, cantidades, pendientes, hashes seguros,
salud/capacidad y período de junio previamente válido cuando aplique. No asumir
que el resultado de una entrega anterior sigue siendo el estado actual.

### 10.2 Backup y restauración comprobada

Antes del ensayo productivo, preparar un respaldo consistente y recuperable del
alcance necesario, autorizado explícitamente, desde VM/VPC/contexto aprobado.
Documentar consistencia entre colecciones, instante/corte, cambios concurrentes,
protección/cifrado, permisos mínimos, ubicación y retención sin exponer secretos.
Verificar restauración **en un destino aislado**, no encima de producción.

Un backup existente no prueba que sea coherente ni restaurable. No restaurar
ciegamente toda la base después del piloto: podría borrar hechos nuevos o
sobrescribir tokens renovados legítimamente desde el respaldo. Diseñar una
recuperación por alcance que preserve OAuth, identidades y escrituras posteriores.
Si no hay recuperación segura demostrada, no iniciar la prueba productiva. El piloto no autoriza borrar datos.

### 10.3 Vinculación auténtica y observación

- Usar OAuth normal y la cuenta autorizada; ningún token copiado o reasignado.
- Para cuenta existente, ensayar relink idempotente; no borrar datos para simular nueva.
- Para cuenta nueva, confirmar que realmente está vacía en el alcance relevante.
- No usar force para reemplazar checkpoints; observar admisión y trabajos reales.
- Hacer preview de límites/presupuestos antes de empezar llamadas de adquisición.
- Observar avance útil por fuente y excepciones, no solo contenedor saludable.
- Comprobar conservación de junio y los datos anteriores durante y después.
- Si se agota presupuesto o falla un gate, parar/admitir pendientes; no encadenar runs sin permiso.

### 10.4 Aceptación de datos y fórmulas

Comparar reconciliación/recibos de cobertura con datos persistidos y lectores reales.
Tomar una muestra representativa de órdenes, preguntas con respuesta, envíos/costos,
devoluciones y retiros aplicables; declarar tamaño y selección de la muestra.
**Una muestra correcta no demuestra que todas las páginas o doce meses se adquirieron.**

Para Google Sheets, usar celdas/rangos autorizados y registrar fórmulas/resultados
sanitizados. El handler backend no sustituye prueba nativa; no escribir una hoja
real sin alcance autorizado. Verificar normales, vacíos auténticos, parciales
visibles, límites y conservación de períodos anteriores.

Observar **dos ciclos reales de actualización** posteriores al corte inicial.
Acreditar detección/admisión/persistencia de nuevos hechos o cambios mediante
fuente real disponible, sin fabricar pedidos o mensajes. Si no hubo novedades,
reportar la limitación: dos ciclos vacíos no prueban procesamiento de un cambio.
No fijar 35 minutos como sustituto de aceptación anual; la duración depende del
plan, volumen, cuotas y ciclos. Renovación local sola no cuenta como incremental.

## 11. Rollout separado de desarrollo y adquisición

Identificar propietarios de imágenes por archivos modificados; no asumir siempre
las mismas tres imágenes ni desplegar servicios ajenos. Publicar solo trabajo
autorizado y verificar SHA remoto exacto. Separar build de despliegue.

Cada Cloud Build autorizado usa repositorio conectado, commit exacto presente en
main, una imagen por build y `options.requestedVerifyOption: VERIFIED`.
Verificar fuente, build SUCCESS y digest inmutable; nunca construir Docker local.

Destino vigente documentado: `zeler-platform-dev`, VM `platform-vm`, zona
`us-central1-a`; job `zeler-bootstrap` en `us-central1` si es afectado.
Confirmar destinos y configuración real antes del rollout, sin imprimir secretos.

Orden general, ajustado a compatibilidad demostrada:

1. Registrar imágenes previas inmutables y rollback recuperable/compatible.
2. Aplicar únicamente esquemas/índices autorizados antes de writers que los necesitan.
3. Desplegar propietarios afectados de manera acotada, con dependencias verificadas.
4. Activar progresivamente elegibilidad/plan según alcance aprobado.
5. Verificar digest ejecutado, readiness de consumidores/dependencias y comportamiento.
6. Repetir salud/capacidad después de asentamiento y después de cualquier rollback.

Usar preflight del runbook. Exigir al menos 5 GiB libres en `/` antes de cada
pull —también rollback— y medir después; revisar Mongo, memoria e inodos por separado.
No limpiar Docker ni podar volúmenes sin autorización; no broad Compose restart.
Timeout externo superior al stop grace; un timeout no autoriza repetir el comando
sin inspeccionar primero el estado efectivo.

Rollback debe contemplar contratos de datos, jobs y certificados nuevos, no solo
un tag anterior. No arrancar writers antiguos incompatibles ni borrar recibos
para que el rollback parezca funcionar. Registrar reducción de disponibilidad
si restaurar un lector anterior la implica.

## 12. Fases de entrega y criterio de suficiente

### Fase A — Confirmar y diseñar lo mínimo

- [ ] Verificar referencias actuales, contratos y horizonte por fuente.
- [ ] Definir estados/parcialidad visibles y compatibilidad de lectores.
- [ ] Trazar ingreso normal y relink sin force destructivo.
- [ ] Determinar unidades de trabajo, dependencias, presupuestos y persistencia.

### Fase B — Implementar y probar localmente

- [ ] TDD de incorporación/idempotencia/progreso y fuentes reutilizadas.
- [ ] Completar mensajes y adquiridor/mapeo Full dentro del alcance.
- [ ] Conectar actualización continua sin barrido anual repetido.
- [ ] Ejecutar matriz y controles, incluida capacidad anual/renovación; documentar limitaciones reales.

### Fase C — Preparar y verificar operación autorizada

- [ ] Propuesta exacta, baseline, backup consistente y restauración aislada.
- [ ] Publicación/build/deploy solo con sus autorizaciones.
- [ ] Piloto OAuth real, conservación previa, lectura nativa autorizada y dos incrementales.
- [ ] Evidencia final por fuente y rollback compatible.

**Suficiente no significa perfecto:** terminar cuando la vinculación inicia el
flujo correcto, los datos útiles llegan y se mantienen, los límites son visibles,
los errores puntuales quedan recuperables y no se compromete integridad/aislamiento.
No prolongar por mejoras cosméticas, cero warnings irrelevantes o una excepción
externa ya identificada con tratamiento seguro y explícito.

Sí impiden declarar completa la entrega: adquisición que nunca arranca, pérdida
de datos previos, cruces de vendedores, totales falsos, bucles de reintento,
falta de progreso durable o una fuente obligatoria sin tratamiento implementado.
Un bloqueo externo puede dejar esa fuente pendiente; debe reportarse como tal,
no convertir “entrega local lista” en “producción validada”.

## 13. Plantilla de evidencia final

```text
Commit de código / estado Git:
Autoridad utilizada y acciones expresamente no ejecutadas:
Pruebas locales: resultados, aislamiento, fallos preexistentes y regresiones:
Esquemas/índices afectados y resultado de export/lint:
Builds: imagen, build ID, commit fuente y digest:
Runtime: destino, digest ejecutado, salud/capacidad y asentamiento:
Cuenta piloto: referencia sanitizada; modo nuevo/relink; corte y zona:
Backup: alcance, consistencia, protección y prueba de restauración aislada:
Por fuente:
  intervalo solicitado / horizonte accesible / intervalo comprobado;
  enumeración conocida o desconocida, persistidos y pendientes;
  campos opcionales ausentes, excepciones y próxima acción acotada;
  estado completo / con observaciones / pendiente / no aplica y fundamento.
Cobertura previa conservada: evidencia antes/después, incluido junio si aplica:
Capacidad: volumen ensayado, tiempos/backlog, vigencia de cobertura y límites medidos:
Incremental 1 y 2: tiempos, fuente, cambios reales y escrituras comprobadas:
Fórmulas: backend / nativas, muestra, rango, resultado y límites:
Qué quedó implementado / publicado / desplegado / validado / pendiente:
Rollback compatible y límites actuales:
```

Nunca incluir tokens, cadenas de conexión, secretos, contenido de mensajes,
direcciones o datos de compradores en reportes, capturas o memoria.
Presentar conteos/hashes seguros y referencias de evidencia con acceso adecuado.

## 14. Referencias de continuación

- [Plan histórico previo](zelerdata-pilot-plan-20260914.md): antecedente, no prueba de completitud actual.
- [Contratos de fórmulas](zelerdata-formulas.md) y [matriz ejecutable](../../modules/sheets/src/zeler_sheets/formulas/matrix_contracts.py).
- [Refresh](zelerdata-refresh.md) y [reconciliación](zelerdata-read-model-reconciliation.md).
- [Órdenes — documentación oficial ML](https://developers.mercadolibre.com.mx/gestiona-ventas): horizonte documentado de búsqueda de órdenes; confirmar cambios antes de implementar.
- [Reclamos — documentación oficial ML](https://developers.mercadolibre.com.mx/que-es-un-reclamo): filtros/recursos; no extender automáticamente a todas las familias el límite de órdenes.
- [Preguntas y respuestas](https://developers.mercadolibre.com.mx/es_ar/gestiona-preguntas-respuestas): estados, respuestas y texto restringido; no inventar contenido ausente.
- [Items y búsquedas](https://developers.mercadolibre.com.mx/es_ar/envio/items-y-busquedas): scan de preguntas de gran volumen; verificar parámetros por recurso, no generalizarlos.
- [Mensajería posventa](https://developers.mercadolibre.com.mx/es_ar/mensajeria-post-venta): paginación limit/offset y `mark_as_read=false` obligatorio para esta adquisición sin efectos secundarios.
- [Envíos](https://developers.mercadolibre.com.mx/envios): detalle, costos y recursos de historial; incluir solo lo requerido por este alcance.
- [Devoluciones](https://developers.mercadolibre.com.mx/en_us/introduction-services/ml-returns): recursos post-purchase v2 y relaciones.
- [Fulfillment](https://developers.mercadolibre.com.mx/es_mx/envios-fulfillment): operaciones por vendedor/inventario/fechas y scroll; comprobar qué tipos y detalles acreditan un retiro.

Estas referencias se revisaron el 2 de octubre de 2026 mediante contenido oficial
indexado; algunas páginas directas rechazaron acceso de la herramienta. No fue
una consulta autenticada de API ni una comprobación de permisos de la cuenta.
La documentación de órdenes consultada indica actualización del 21 de septiembre
de 2026. No inferir retención de operaciones Full a partir de una nota de stock:
su horizonte específico queda por confirmar. Reclamos exige precisión y límites
de paginación propios; incorporar sus filtros de fechas con milisegundos y el
límite documentado `offset + limit < 10000`, no extrapolar parámetros de órdenes.

Antes de cerrar diseño de cada adquiridor, dejar en la entrega su referencia
oficial exacta y fecha de revisión, horizonte garantizado o no documentado,
paginación, campos obligatorios y permisos. No usar un recuerdo de “12 meses”
como evidencia universal. Este documento no sustituye esa comprobación ni una
prueba productiva autorizada.
