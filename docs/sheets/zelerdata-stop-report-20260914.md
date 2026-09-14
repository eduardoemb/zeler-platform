# Reporte de avance y parada — 14 de septiembre de 2026

Cierre solicitado a las 21:58 UTC (15:58 Monterrey): servicios operativos y
saludables; fiabilidad integral de las 35 fórmulas todavía no certificada.
Se detuvieron las pruebas y no se iniciarán nuevos cambios desde esta sesión.

## Entregado

Está desplegada la fuente `8fdf20c63c38d456a80fff8613b5bdb5c213d6d4` en Sheets:
lecturas simultáneas compartidas mientras están en curso, comparación correcta
de etiquetas económicas, proyección de adquisiciones parciales válidas y
conciliación por fechas UTC con conteos reales. No se ampliaron cuota, TTL,
vendedores ni esquemas. Gateway conserva la corrección anterior de conexiones.

Pasaron 4709 pruebas, Ruff, formato y mypy completo (551 archivos), más ocho
pruebas protegidas de transacciones en Mongo local verificado. Una aserción cambió
después del inicio de la suite; sus tres parámetros y controles estáticos pasaron
después. Las correcciones tuvieron revisión independiente.

| Servicio | Build verificado | Digest desplegado |
| --- | --- | --- |
| Sheets worker | `ec0d947a-a514-4b14-b320-4e6a4907eed2` | `sha256:081ef4b92474452b228309c9b8a28cc8f0633fb9952c395144728ba8b8f361a9` |
| Sheets API | `42f8eeea-01b9-4a14-af93-352f2caea839` | `sha256:9b34a2869c65c545d4a2b6cd744fb265432a78cdcc6bdb0b5ef23996347a086d` |
| Gateway retenido | `e767e707-274f-4ec4-b2e4-6632cd654803` | `sha256:4b10da0f1ade34d4c88a0b3b2b7a9ca3f55da633e10f33e90d0550f57425435c` |

Las referencias completas usan
`us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/<servicio>@<digest>`.
Gateway conserva fuente `f30f33d3bedb90cd816a7c80eb34564b6b81a53b`; sus archivos,
core y lockfile no cambiaron entre f30 y 8f. Las imágenes anteriores de Sheets
quedaron disponibles para rollback. Este cierre documental no requiere otra imagen.
Otros servicios no fueron desplegados: evaluar por separado cualquier desfase de
sus imágenes antes de proponer builds o despliegues adicionales.

## Estado operativo comprobado

Gateway `/ready` y Sheets API `/health` devolvieron 200 con dependencias listas.
El worker reportó listos RabbitMQ, sincronizaciones, recuperación de fórmulas y
actualización de datos. Los tres contenedores están saludables, sin reinicios ni
OOM. El último muestreo mantuvo cuatro conexiones y cuatro consumidores del broker,
147 mensajes listos y cero sin confirmar. No hubo limpieza de colas.

La auditoría midió 25.078.108.160 bytes libres en `/`, 48.566.091.776 en el volumen
Mongo montado y 2.084.655.104 bytes de memoria disponible.

## Pendientes que impiden declarar fiabilidad

- **Frescura:** muestra de 21:54 UTC: 1644 publicaciones frescas y 256 vencidas de
  1900; edad máxima 1346,8 segundos y cero discrepancias de proyección. El intervalo
  incluyó despliegues/calentamiento y no prueba estabilidad sostenida ni dos ciclos
  completos posteriores al despliegue.
- **Capacidad:** mínimo optimista de 4233 adquisiciones por ventana de 15 minutos,
  frente a 2700 permitidas por 180/min, incluso suponiendo reutilización adicional.
  Esa cota no demuestra que una tasa mayor sea segura. Reintentos internos pueden
  producir más HTTP upstream que admisiones. Ver el
  [análisis de capacidad](zelerdata-capacity-decision-20260914.md).
- **Calidad:** 1459 fuentes no tienen una proyección reconocida/ligada de calidad;
  esto no prueba ausencia legítima. Tráfico existente registró calidad USER_PRODUCT
  con 4 respuestas 200 y 133 respuestas 404; ofertas con 12 respuestas 200 y 48
  respuestas 404. No se atribuye un significado definitivo a esos 404.
- **Devoluciones:** siguen nueve registros bloqueantes. Las once lecturas diarias
  terminaron correctamente. El 14 de mayo se verificó con tres esperadas, tres
  persistidas, tres completas y una candidata fuera del intervalo. Siete fechas
  conservan datos reparables pendientes. Su intento de reparación terminó con
  `wrapper_refused_or_failed`, sin recibo de ejecución por fecha. La auditoría
  posterior validó las entradas/contexto y confirmó nueve bloqueos; no se afirma
  ninguna reparación adicional por ese intento ni se reintentó tras la parada.
  La causa exacta del fallo operativo queda pendiente.
- La candidata fuera de la búsqueda del 11 de junio pertenece al **12 de junio**,
  no a un día anterior, y no coincide con el registro legado bloqueante. Necesita
  diagnóstico adicional. La cuarentena propuesta para un registro del 23 de junio
  no se ejecutó; requiere evidencia vinculada fresca y autorización de alcance.
- **Aceptación:** no se recalcularon las 35 fórmulas sobre las nuevas imágenes ni
  comenzó la certificación de 90 minutos. La ronda anterior falló tres minutos y
  terminó con ocho resultados PROCESANDO. Los 24 diagnósticos de la hoja conservan
  esa última evidencia real, no un resultado inferido del despliegue.

## Parada y continuidad

El monitor fue cancelado mediante SIGINT dirigido al proceso identificado por
script exacto y argumentos. Cerró sus recursos; el envoltorio terminó con código 1
por la cancelación deliberada. Los despliegues y lecturas auxiliares terminaron.
La operación normal de producción continúa; las pruebas de esta sesión quedan
detenidas. El objetivo SDD permanece incompleto, sin verificación final ni archivo.

Al retomar: resolver capacidad/fuentes y devoluciones; después verificar las 35
fórmulas en las imágenes vigentes y ejecutar los 90 minutos completos.

Evidencia sanitizada en `/tmp/zeler-closure-release/`: `final-closeout-audit.jsonl`,
`second-field-census.jsonl`, `second-returns-source-proofs.jsonl`,
`second-returns-writes.jsonl`, `jun11-outside-legacy-mapping.jsonl`,
`gateway-traffic-evidence-fullwindow.jsonl`, `stop-owned-monitor.jsonl`, y builds
y despliegues bajo `8fdf20c63c38/`. Véase también el
[informe cronológico](zelerdata-closure-20260914.md).
