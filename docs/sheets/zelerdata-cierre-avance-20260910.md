# Cierre de avance de ZelerData — 10 de septiembre de 2026

Estado: entrega de avance solicitada por el usuario. La aceptación final del Goal
sigue abierta. Corte de observación: 2026-09-10, tras finalizar el despliegue de `849b290`.

## Avance demostrado

- Hay evidencia de ejecución de las 52 fórmulas desde la pestaña real autorizada
  `Goal_Pruebas_20260909`: 52 eventos HTTP 200 y lectura de tres filas por ancla.
  El recibo declara `correctness_verified=false`: prueba ejecución y una muestra
  de resultados, pero no integridad ni exactitud de todos los campos.
- La corrección de recuperación de solicitudes de artículos mayores de 20 IDs
  está implementada en `208decf`, con continuidad persistida y pruebas de
  reinicio/fallo. Su despliegue anterior está registrado; falta el ejercicio
  productivo específico con lectura posterior del trabajo persistido.
- Las correcciones `2e7fdd5`, `bb0cb4d` y `849b290` permiten que la reconciliación
  contabilice metadatos de catálogo ausentes y respuestas individuales 404 sin
  impedir obtener los demás recursos válidos. Las pruebas enfocadas están
  registradas en el informe de avance.
- La consulta actual a la VM confirma API y worker de Sheets saludables.
- La evidencia histórica registra la corrección y despliegue del aislamiento
  de identidad de auditoría. No debe presentarse ese defecto como todavía abierto.

## Estado actual del despliegue

| Servicio | Digest anterior | Digest de `849b290` actualmente saludable |
| --- | --- | --- |
| Sheets worker | `13c01609314745a95cb6dead2a166622b0b518191f8fc886e308e1273a1cfe7d` | `4f06bc873f7fc206b488593023f8c14c9f1cbba7c8c876b72bc26224b5023aa3` |
| Sheets API | `3268f014d476456305e9f18459500e77a6f1ab16a79a82913ad62842dfbe2190` | `6ca039bd8b02974064c21916fcf03972824c5708c3693843332deccc4a42246e` |

El proceso remoto `bash /tmp/zeler-deploy-reconcile-sheets.sh` terminó con código
0. Una consulta posterior e independiente a Docker Compose confirmó los dos
digests finales activos y ambos servicios saludables. Ya no existe esta
diferencia entre las imágenes previstas y ejecutadas; no se requiere otro build
por este cambio. Falta comprobar el comportamiento funcional posterior.

## Pendientes para aceptación final

| Requisito | Evidencia que falta o acción siguiente |
| --- | --- |
| Última versión operativa | Activación y salud comprobadas; falta aceptación funcional posterior. |
| Datos completos y confiables | Repetir reconciliación `--dry-run` para el piloto 82453304 y rango 2026-08-08 a 2026-09-06 con la versión corregida; resolver discrepancias antes de escribir y verificar después la persistencia/lectura. |
| Recuperación automática | Demostrar solicitud faltante → trabajo asíncrono → adquisición Mercado Libre → Mongo → consulta posterior, incluida la continuación de artículos mayores de 20 IDs. |
| Ausencias honestas | Verificar razones persistidas y visibles de los recursos no recuperables. Seis artículos devolvieron 404 en la prueba previa; eso no demuestra que toda ausencia histórica sea irrecuperable. No convertir errores temporales en ausencia definitiva. |
| 52 fórmulas y superficies actuales | Completar comparación de valores/contratos contra datos fuente, y aceptación representativa en la Sheet real y superficies existentes de zeler-app. HTTP 200 no basta para probar valores correctos. |
| Latencia | Medir ejecución completa de Apps Script/Sheets y demostrar el límite de 30 segundos; fijar el presupuesto p95 a partir de esa medición. Los tiempos del endpoint excluyen sobrecarga de Google. |
| Contrato actual de órdenes | Consolidar evidencia de adquisición, normalización y lectura con el contrato nuevo, incluidas asociaciones de envíos; no extrapolar una prueba parcial a toda la migración. |
| Seguridad mínima y ciclo de datos | Completar evidencia de cifrado, aislamiento, roles, auditoría, logs sanitizados y eliminación. La eliminación de credenciales no prueba eliminación de datos de negocio; sigue pendiente un ciclo verificable de eliminación dentro del alcance. |
| Simplificación | Cerrar inventario de consumidores y justificar qué mecanismos, compatibilidades, documentación o pruebas se conservaron o retiraron. No eliminar controles críticos para reducir volumen. |
| Capacidad y entrega | Verificar capacidad final frente a la referencia previa y explicar cualquier diferencia permanente; consolidar regresión final, evidencia, correspondencia código/imágenes y pendientes. |

No se asigna porcentaje global: las 52 ejecuciones no equivalen a 52 fórmulas
aceptadas y todavía faltan controles obligatorios. El estado verificable es
implementación avanzada con aceptación funcional y operativa incompleta.

## Fuentes y continuación

Actualización posterior (13:30 UTC): el dry-run sobre `849b290` terminó con
código 1 y `mandatory_source_gate.authoritative=false`. Siguen sin fuente
esperada válida los conteos históricos de órdenes, envíos, artículos, preguntas
y reclamos; no se ejecutó escritura. Reportó 5 filas de fórmulas y 11 entradas
SKU faltantes, y 389 snapshots buybox faltantes respecto de sus expectativas.
Estos conteos no prueban por sí solos el origen ni la recuperabilidad de cada
ausencia.

Una consulta de solo conteo en Mongo desde el worker confirmó siete artículos
del piloto con `catalog_listing=true` sin ID de producto. El commit `4209304`
corrige ese caso reproducido por prueba, está en GitHub y tiene builds en curso:
worker `9928ace9-e389-482b-aedb-9ce72b8658e7`, API
`57f2cd9f-27cc-478e-9a37-edf68b918f84`. Ambos registros de Cloud Build señalan
la revisión exacta `42093046fac89de00869e85ca0c1c713d8fa3d9e` y estado WORKING
en la última observación. No se ha desplegado esa corrección ni se ha demostrado
que explique por completo la excepción histórica. Observar estos builds;
no repetirlos. El runtime observado sigue en `849b290`.

- [Recibo de las 52 ejecuciones](zelerdata-goal-smoke-20260910.json).
- [Registro de avance y pruebas](../zelerdata-goal-progress.md), incluidas las
  secciones de identidad de auditoría, controles mínimos y últimos despliegues.
- Objetivo original: archivo adjunto `pasted-text-1.txt` de esta misión.
- Consulta actual: `docker compose ps sheets-worker sheets-api` y árbol de
  procesos remoto, desde la VM autorizada, con salida limitada a servicio,
  imagen, salud y proceso de despliegue.

La siguiente acción técnica es el dry-run de reconciliación con la versión
desplegada, seguido de validación funcional y lectura persistida. Este informe no
autoriza ni recomienda borrar datos productivos como parte del cierre.
