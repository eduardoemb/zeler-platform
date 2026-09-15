# ZelerData: piloto útil, actualización continua e historial disponible de 12 meses

Estado: plan propuesto el 14 de septiembre de 2026. Alcance inicial: vendedor
piloto `82453304`, interfaz existente de ZelerData y sus 52 fórmulas activas.
Este documento no cambia producción ni acredita una nueva prueba de estabilidad.

Alcance ampliado por instrucción del usuario: las 52 fórmulas deben resultar
suficientemente buenas para el piloto. El catálogo documentado y las funciones
del add-on contienen los mismos 52 nombres. Los 35 casos de la prueba anterior
cubrían 24 fórmulas distintas, no 35; se conservan como regresión y no delimitan
la aceptación del catálogo completo. Véanse el
[catálogo de fórmulas](zelerdata-formulas.md) y el
[reporte de aquellos casos](zelerdata-live-retest-20260914.md).

La entrega debe permitir trabajar con publicaciones y operaciones reales,
incorporar novedades automáticamente y consultar el historial recuperable de los
últimos 12 meses. Los datos secundarios pueden actualizarse con menor frecuencia;
la exactitud, la identificación del vendedor y la visibilidad de los faltantes
siguen siendo obligatorias.

## Punto de partida y decisión

El [reporte de parada](zelerdata-stop-report-20260914.md) documenta servicios
operativos al detener la sesión, pero la aceptación integral quedó pendiente.
El [análisis de capacidad](zelerdata-capacity-decision-20260914.md) estima como
mínimo optimista 4233 adquisiciones para renovar todo cada 15 minutos, frente a
2700 admisiones con el presupuesto local de 180/min. Este último no acredita la
cuota real de MercadoLibre. Hay nueve registros bloqueantes de devoluciones.

La decisión propuesta es separar novedades, adquisición básica, historial y
enriquecimiento. Conservar inicialmente el presupuesto de 180/min y medir también
los intentos HTTP reales, incluidos reintentos. Aumentar frecuencia o cuota solo
con evidencia posterior de capacidad y beneficio para el piloto.

La implementación requiere un cambio SDD que explicite qué requisitos reemplaza
de `zelerdata-live-formula-repairs`, especialmente la frescura uniforme. El cambio
anterior continúa incompleto; este plan no lo convierte en aprobado.

## 1. Fijar el contrato del piloto

Crear una matriz de las 52 fórmulas: recursos necesarios, campos obligatorios,
antigüedad permitida, cobertura histórica y resultado esperado cuando falta una
fuente. Conservar nombres, parámetros, aliases y estructuras públicas existentes.
Separar las dependencias de cada campo para que una adquisición secundaria fallida
no impida presentar información básica válida.

Cada fórmula tendrá casos representativos con datos, ausencia legítima, filtros
y rangos aplicables; registrar fuente esperada, salida real y evidencia pendiente.
Si el piloto carece de un caso positivo, comprobar esa rama con datos de prueba
controlados y documentar la limitación de la evidencia productiva. Una salida
vacía por sí sola no demuestra que la fórmula funciona. Ninguna fórmula queda
fuera por ser secundaria: las prioridades ordenan la implementación y el consumo
de API, pero todas forman parte de la entrega final.

Estos son objetivos propuestos, pendientes de implementación y medición:

| Información | Objetivo inicial | Regla de presentación |
| --- | --- | --- |
| Ventas nuevas, cambios de operaciones y cambios notificados de precio/stock | 95% de eventos disponibles reflejados en hasta 5 minutos; recuperación de omisiones mediante conciliación cada 15 minutos | Medir llegada al sistema, persistencia y visibilidad en la hoja por separado |
| Inventario básico completo | Barrido en hasta 30 minutos después de la carga inicial | Mostrar fecha de adquisición real y advertir cobertura incompleta |
| Cálculos económicos y competencia solicitados por el usuario | Datos sensibles de hasta 15 minutos, adquisición priorizada por publicaciones solicitadas | Si falta un componente imprescindible, indicar actualización pendiente o indisponibilidad; nunca presentar un neto incompleto como definitivo |
| Calidad y enriquecimiento general del catálogo | Ciclo inicial de hasta 6 horas | Conservar la antigüedad de cada fuente y señalar información vencida |
| Historial | Carga inicial progresiva, después mantenimiento incremental | Mostrar intervalo cubierto y pendientes por recurso |

Las notificaciones se procesan al llegar, sin esperar cinco ni quince minutos.
Los cinco minutos son un objetivo de latencia, no un intervalo de ejecución; los
quince minutos de conciliación son un respaldo ante omisiones. Registrar el aviso
en `webhook_events`, persistir los datos consultables y recalcular las celdas son
pasos distintos que deben medirse por separado.

Cambiar solo el programador no basta: los lectores actuales de calidad y
calculadora tienen comprobaciones de 15 minutos. Deben adaptarse las políticas de
campo, pruebas y presentación juntas. No renovar fechas de enriquecimiento por
haber actualizado únicamente la publicación básica. El objetivo económico de
15 minutos no promete enriquecer las 1900 publicaciones simultáneamente.

## 2. Mantener las novedades al día

Reutilizar las notificaciones, gateway y workers existentes. Consumir cambios de
órdenes, publicaciones, envíos, preguntas y reclamos según sus tópicos y permisos
reales. Consultar el estado actual de la fuente, procesar de forma idempotente y
evitar que mensajes antiguos sobrescriban observaciones más recientes.

Añadir o completar conciliación por última modificación, con un solapamiento
acotado y deduplicación. Buscar solo por creación no recupera cambios recientes de
ventas antiguas. Guardar el progreso únicamente después de persistir con éxito y
recuperar interrupciones sin empezar de cero. Verificar renovación legítima de
OAuth y reintentos limitados ante fallos de red, 401 y 429.

Asignar prioridad a novedades y consultas activas, reservando capacidad para que
el historial avance. Reducir el trabajo secundario cuando aumente el retraso;
una cola de errores repetidos no debe monopolizar el worker. La reserva exacta se
dimensionará con el primer tramo histórico y el tráfico real del piloto.

## 3. Recuperar los últimos 12 meses por tramos reanudables

MercadoLibre documenta órdenes creadas hasta 12 meses atrás y filtros por última
modificación. También advierte exclusiones de órdenes canceladas en búsquedas de
vendedor: validar los estados recuperables y registrar las exclusiones reales.
Fuente: [documentación de órdenes](https://developers.mercadolibre.com.ar/es_ar/publica-productos/gestiona-ventas).

La cobertura de otros recursos debe comprobarse individualmente. Por ejemplo,
MercadoLibre elimina preguntas sin responder de más de siete meses; no se puede
prometer reconstruirlas. Fuente:
[documentación de preguntas](https://developers.mercadolibre.com.ar/es_ar/saldo-de-la-cuenta/gestiona-preguntas-respuestas).
Las páginas oficiales se consultaron mediante su contenido indexado; su apertura
directa devolvió 403. La disponibilidad para el piloto se comprobará en el runtime.

| Recurso | Tratamiento del historial |
| --- | --- |
| Órdenes/ventas | Recuperar el intervalo de 12 meses accesible, conciliar páginas, IDs, estados y totales |
| Envíos, reclamos y devoluciones | Recuperar recursos vinculados y búsquedas permitidas; acreditar cobertura de cada fuente sin suponer la misma retención que órdenes |
| Preguntas y respuestas | Cargar lo que la API conserve y documentar sus límites |
| Precios, stock, calidad y competencia históricos | Usar únicamente historia ya registrada o endpoints históricos comprobados; un valor actual no reconstruye los meses anteriores |

Fijar una fecha de corte inicial y restar 12 meses calendario. Por ejemplo, si
iniciara el 14/09/2026, el inicio sería el 14/09/2025 a la hora de corte acordada.
Convertir los límites a UTC con intervalos sin solapamientos contables. Registrar
eventos posteriores al corte desde el comienzo para evitar un hueco de activación.

Orquestar tramos mensuales, subdivisibles si la paginación lo exige, usando los
trabajos existentes de máximo 90 días. No ampliar indiscriminadamente ese límite.
Dar acceso rápido a los días recientes y proteger desde el arranque el extremo
más antiguo que está próximo a salir de la retención de la API; después completar
los tramos restantes. No perder ese extremo por posponerlo hasta el final.

Persistir por recurso y tramo: límites, cursor, IDs descubiertos, conteos
recuperados, registros completos, errores, última comprobación y estado de
cobertura. Un HTTP 200 o una página vacía aislada no acredita integridad. Reanudar
desde un punto seguro; conciliar de nuevo las páginas afectadas por cambios.
Estimar duración tras medir el primer tramo, sin prometer una fecha basada solo
en el número de meses. No borrar historia adquirida cuando avance la ventana.

El piloto puede usar el presente mientras se completa la carga. La entrega final
de 12 meses exige todos los tramos terminados o una limitación de fuente concreta
y demostrada; un error pendiente propio no cuenta como limitación de MercadoLibre.

## 4. Resolver los bloqueos que afectan la confianza

Reparar las devoluciones con datos recuperables y verificar su persistencia y
proyección. Diagnosticar el fallo operativo del intento anterior antes de repetir
escrituras. Resolver los nueve registros bloqueantes con evidencia individual;
para casos irreconstruibles, preparar una disposición auditable con alcance
explícito. Algunos registros antiguos pueden bloquear consultas actuales aunque
estén fuera de los 12 meses: no basta con ignorarlos por fecha.

No desactivar protecciones globales, convertir ausencia desconocida en cero ni
atribuir todos los 404 a falta legítima de información. Distinguir datos completos,
actualización pendiente, cobertura parcial, ausencia acreditada y fallo reparable.
Un estado parcial debe permitir usar los campos independientes que sean correctos.

## 5. Hacer visible la sincronización en la experiencia real

Reutilizar `/sheets/config` en `../zeler-app` y el add-on de
`modules/sheets/apps_script/sheetseller/`. Mostrar última sincronización correcta,
intervalo histórico cubierto, progreso y una acción de reintento que reutilice
trabajos en curso. Las fórmulas deben conservar su compatibilidad.

El cliente Apps Script revisado solicita recalcular cuando recibe `PROCESANDO`;
los archivos examinados no contienen un mecanismo de actualización periódica.
Diseñar y probar el mecanismo compatible con Apps Script para actualizar las
celdas sin editar fórmulas manualmente, con permisos legítimos, límites de cuota,
concurrencia acotada y sin modificar otras celdas del usuario. Verificar hoja
abierta y reapertura después de un período cerrada; no prometer actualización
visible continua en segundo plano sin demostrar que el mecanismo la soporta.

La versión del add-on que use el piloto debe corresponder a la fuente verificada.
Su publicación tiene un procedimiento independiente del despliegue del backend.

## 6. Entregar con una aceptación finita

Implementar por unidades SDD: políticas de frescura y prioridades; adquisición
incremental; orquestación histórica; reparación de integridad; experiencia de
sincronización; verificación. Cada comportamiento no trivial empieza con una
prueba fallida. Usar Mongo de desarrollo verificado para pruebas locales.

Al finalizar código, ejecutar pytest, Ruff, formato y mypy completos, más controles
de acceso Meli o esquemas cuando correspondan. Para runtime, identificar servicios
afectados, fuente exacta, imágenes inmutables y rollback compatible. Builds,
despliegues, migraciones y publicación del add-on conservan sus autorizaciones
separadas; este plan no ejecuta esas operaciones.

La aceptación del piloto requiere:

- Las 52 fórmulas ejecutadas en Google Sheets real, tanto individualmente como
  en una ronda simultánea del catálogo completo con entradas representativas del
  piloto y matriz previa de resultados esperados. Conservar también los 35 casos
  previos como regresión. Los casos con fuente válida devuelven datos
  correctos; una indisponibilidad solo pasa si su causa está acreditada. No se
  acepta `PROCESANDO` indefinido ni reetiquetar fallos propios como no disponibles.
  El reporte final tendrá 52 entradas con resultado, cobertura, frescura y
  limitaciones. La existencia de un handler o una respuesta sin error no acredita
  utilidad. Una fórmula sin su resultado principal por un fallo reparable sigue
  pendiente; no se acepta simplemente porque muestre `DATA_UNAVAILABLE`.
- Los 12 meses accesibles terminados y conciliados por tramo y recurso, con las
  exclusiones visibles. Comparar agregados y una muestra de detalles con la API;
  acreditar paginación completa y ausencia de duplicados en todo el intervalo.
- Novedades y modificaciones de registros antiguos verificadas de extremo a
  extremo, hasta las celdas, mientras corre carga histórica. Usar actividad real
  o reproducción controlada de eventos existentes sin crear operaciones comerciales.
  Identificar qué evidencia corresponde a cada modalidad.
- Recuperación demostrada frente a eventos repetidos/desordenados, interrupción
  de trabajos y fallos transitorios, mediante pruebas controladas. No provocar
  indisponibilidad productiva para probar recuperación.
- Una observación de 90 minutos después del calentamiento, con rondas simultáneas
  de las 52 fórmulas al inicio, a los 30 y a los 60 minutos; comprobar los objetivos de frescura,
  progreso de colas, errores, capacidad y ausencia de intervención manual. Una
  muestra pequeña de eventos no permite afirmar un percentil representativo:
  reportar tamaño de muestra, máximos y ensayos controlados por separado.

Errores de vendedor, resultados económicos incorrectos, novedades perdidas,
historia recuperable omitida o trabajos bloqueados impiden cerrar. Los límites
demostrados de la API, la menor frecuencia pactada de calidad y detalles visuales
menores pueden quedar documentados sin impedir uso.

Si pasa la aceptación, entregar reporte con cobertura, tiempos medidos, versión,
limitaciones, alertas y procedimiento de recuperación, y detener cambios activos.
Dejar la sincronización normal funcionando. Recomendar revisar sus métricas
pasivamente durante las siguientes 24 horas; cualquier nuevo monitor requiere
quedar configurado y comprobado, no asumido. Los 90 minutos acreditan esa ventana,
no una garantía indefinida.

Si falla, registrar el defecto concreto y corregir la etapa afectada. Repetir los
controles que la corrección invalide; reiniciar los 90 minutos solo si cambia el
comportamiento cuya estabilidad se estaba midiendo. No abrir mejoras secundarias
durante el cierre del piloto.

## Siguiente paso

Convertir este plan en especificación y tareas del cambio SDD del piloto,
empezando por la matriz de las 52 fórmulas y las políticas de adquisición. La
primera evidencia de entrega será el flujo de novedades hasta la hoja; la
aceptación final incluye el historial accesible y la ventana de observación.
