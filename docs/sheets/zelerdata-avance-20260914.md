# Avance de ZelerData — 14 de septiembre de 2026

Corte: 18:40 UTC. Reporte de avance; no declara terminada la validación
final ni reparadas todas las fórmulas.

## Implementado

- Adquisición base del inventario separada de calidad, promociones y costes.
- Tres colas de recuperación independientes, con 180 solicitudes por minuto
  compartidas y admisiones distribuidas para evitar ráfagas.
- Reserva de capacidad para inventario, admisión acotada y distinción entre
  espera de cuota y fallo real del proveedor.
- Lectura de catálogo mediante una única captura de fuentes verificadas por
  consulta, conservando integridad, vigencia y asociaciones de variantes.
- Consultas de ventas limitadas a periodos cuya cobertura permite mostrar datos.

Código publicado en `main`: `bead0c48bd35449ae5553eb0d695b893fcb653b0`.

## Evidencia obtenida

- Suite completa: **4.626 pruebas aprobadas, 9 omisiones explicadas**.
- Prueba adicional con Mongo real: aprobada; se añadió después de recopilar la
  suite completa y se ejecutó dentro del conjunto enfocado de 230 pruebas.
- Ocho pruebas protegidas de Mongo: aprobadas por separado.
- Ruff, formato y mypy completo: aprobados; revisión independiente sin defectos
  nuevos en las unidades inspeccionadas.
- Dos ciclos productivos consecutivos de 1.900 publicaciones: **10:17** y
  **13:47**. Al terminar cada uno, las 1.900 fuentes estaban recientes y había
  cero proyecciones base faltantes, sin ampliar los 15 minutos de vigencia.
- Se recalcularon las 35 fórmulas originales. Los controles de calculadora,
  historial, códigos, preguntas y ausencia de ventas volvieron a dar resultados.

## Entrega y pendientes

Las imágenes nuevas de worker y API están construidas y su procedencia fue
verificada contra el commit exacto. El worker nuevo quedó saludable, con cero
reinicios y sin eventos OOM; el control posterior registró 27 GiB libres en la
partición raíz. La API nueva también quedó saludable, sin reinicios/OOM, con
26 GiB libres después de la entrega. Los digests de ambos servicios coinciden
con las imágenes verificadas. Sin embargo, en el control posterior la API pasó
a `unhealthy`: `/health` devolvió 503 dos veces por RabbitMQ y por el control de
la cola de descartes; Mongo y registro sí pasan. El gateway también devolvió
503 en `/ready`: RabbitMQ falla, mientras Mongo, registro y scheduler pasan.
El retest final quedó detenido tras
recalcular cinco grupos (23 de los 35 casos); no se declara validado.

En los 23 casos recalculados con la API nueva, calculadora, supermercado,
historial y dimensiones devolvieron resultados o sus controles negativos
esperados. Calidad, catálogo y buybox todavía devolvieron `PROCESANDO`;
`OBTENERCATALOGO` devolvió `DATA_UNAVAILABLE`. Las otras 12 anclas se leyeron
sin recalcularlas en esta ronda y no constituyen validación de la versión nueva.

Falta recuperar disponibilidad del broker, repetir las comprobaciones de salud
y completar los 35 casos con lectura de sus matrices, no solo encabezados.
DEVOLUCIONES y las métricas sin una fuente histórica válida permanecen abiertas
y fuera del alcance de la adquisición base.

Los dos ciclos aprobados no prueban disponibilidad continua: el tercer barrido
duró **20:12**, incluyendo el periodo de despliegue del worker. A las 18:16:43 UTC
había 1.420 de 1.900 fuentes recientes y 480 proyecciones base pendientes. Las
filas vencidas o en actualización siguen marcadas como pendientes; no se
alteraron sus fechas para ocultarlo.

La API y el gateway comparten el fallo de broker; la causa no está determinada.
No se modificó el broker ni se reiniciaron otros servicios. Las imágenes nuevas
siguen ejecutándose; su disponibilidad productiva no se da por validada. El
plan conserva la reversión compatible documentada si resulta necesaria.

No hay código nuevo pendiente de imagen: ambos servicios ejecutan el commit
`bead0c4`; los cambios locales posteriores son documentación.

Evidencia técnica y digests: [reporte detallado](zelerdata-layered-recovery-20260914.md).
