# Cierre de avance de ZelerData — 10 de septiembre de 2026

Estado: entrega de avance solicitada por el usuario. La aceptación final del Goal
sigue abierta. Corte de observación: 2026-09-10, con API y worker verificados en
las imágenes del commit `4209304` y el conteo de catálogo corregido en `43e4a29`.

## Resumen antes/ahora

Línea base documentada el 2026-09-07 sobre `main` en
`c5a2e097`: la API de fórmulas devolvía `DATA_UNAVAILABLE` sin programar
recuperación; la ejecución productiva de la reconciliación no aparecía en
`systemd` y la procedencia de las imágenes seguía sin resolver; las lecturas de
artículos, SKU y órdenes truncaban silenciosamente en 500/500/1,000 filas; el
estado del read model del piloto 82453304 era `degraded` (7 modelos faltantes, 9
reconciliados, 1 vencido) y las 17 entradas de inventario fallaban la ventana
productiva. Gateway, API/worker de Sheets y Mongo estaban saludables, pero la
salud de los contenedores no probaba disponibilidad ni exactitud de datos.

Estado actual: 219 commits después, la ruta de recuperación asíncrona existe y
está conectada a la API y al worker; las lecturas ya no truncan en los casos
cubiertos por sus pruebas; se corrigieron recuperación de órdenes, envíos,
catálogo, precios, atributos de variación, preguntas y calidad de publicación; y
las 52 fórmulas se ejecutaron en una pestaña real con 52 respuestas HTTP 200.
Esa ejecución prueba que las fórmulas responden, no que todos sus valores sean
correctos: el recibo declara `correctness_verified=false`.

| Dimensión | Antes (2026-09-07) | Ahora (2026-09-10) |
| --- | --- | --- |
| Recuperación asíncrona | Ausente en la ruta de fórmulas | Conectada a API/worker, con continuidad de artículos y reintentos acotados |
| Lecturas de datos | Truncadas en 500/500/1,000 filas | Corregidas en los casos cubiertos por pruebas; revisión global pendiente |
| Reconciliación del piloto | No ejecutada con veredicto autoritativo | Dry-run diagnóstico autoritativo para reclamos; conteos de catálogo en revisión |
| 52 fórmulas | Sin smoke productivo | 52 HTTP 200 en Google Sheet real; exactitud sin verificar |
| Imágenes desplegadas | Procedencia sin resolver | API y worker saludables en las imágenes de `4209304` |
| Seguridad y ciclo de datos | Gate abierto | Gate abierto; aislamiento de auditoría corregido, eliminación sin prueba |
| Conteo de catálogo | Sin criterio de participación | Corrección `43e4a29` probada (197 casos); requiere imagen |
| Simplificación | Sin inventario de consumidores | Pendiente de cierre explícito |

El avance es material, pero no equivale a cierre: falta demostrar que los datos
reconciliados son completos y correctos, que la recuperación automática produce
lecturas posteriores confiables y que se cumplen los gates de seguridad, latencia,
simplificación y aceptación en superficies reales.

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

Consulta de solo lectura a la VM el 2026-09-10: API y worker de Sheets llevan
más de 7 horas saludables en las imágenes de `4209304`.

| Servicio | Digest activo y saludable | Commit de origen |
| --- | --- | --- |
| Sheets worker | `sha256:4585407aca40d78d3eaa5da41a1371f5d5d0704127acc779ff0a21c60b068656` | `4209304` |
| Sheets API | `sha256:38b5b6ee19b8b1a19b9f05eca6547bdc1a4420b126f79a1fbd86d711281da7c5` | `4209304` |

El despliegue worker → API terminó con código 0, con respaldos Compose por
servicio (`pre-<servicio>-4209304`) y más de 5 GiB libres. La corrección de
conteo de catálogo (`43e4a29`) todavía no tiene imagen: usa la ruta de
recuperación de metadatos de catálogo del backfill y exige participación
explícita más identidad de producto. Hasta construir y desplegar esa imagen, la
reconciliación sobre el runtime actual sigue reportando los 389 snapshots
buybox contra expectativas que incluyen 529 publicaciones no participantes; esos
números no son evidencia de cobertura real.

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

Actualización posterior de despliegue: ambos builds finalizaron SUCCESS con la
revisión exacta `42093046fac89de00869e85ca0c1c713d8fa3d9e`. El despliegue
worker → API terminó con código 0 y verificó ambos contenedores saludables.
Los digests activos verificados por el despliegue son:

- Worker: `sha256:4585407aca40d78d3eaa5da41a1371f5d5d0704127acc779ff0a21c60b068656`.
- API: `sha256:38b5b6ee19b8b1a19b9f05eca6547bdc1a4420b126f79a1fbd86d711281da7c5`.

Ambos preflights superaron 5 GiB libres (22 GiB observados). Los respaldos Compose
por servicio tienen sufijo `pre-<servicio>-4209304`. Los digests anteriores de
`849b290` quedan en la tabla para referencia. El cambio posterior `9409ff0` es
solo documentación y no requiere nueva imagen. Se inició un nuevo dry-run
diagnóstico (sesión local 8497), limitado a clases de excepción, estado HTTP,
funciones/líneas y conteos; todavía falta su resultado. No hubo escrituras de
reconciliación ni se afirma aceptación funcional por la salud del despliegue.

Resultado posterior del diagnóstico 8497: finalizó con código 0 y comprobación
de fuente de reclamos `authoritative=true`, sin códigos de incidencia. La fuente
histórica ahora reporta 103 órdenes, 100 envíos, 57 artículos, 3 preguntas y 3
reclamos; sus conteos de referencias faltantes son cero. El conteo de órdenes
persistidas en el intervalo es 100, por lo que aún debe explicarse la diferencia
de alcance temporal frente a las 103 referencias fuente antes de afirmar igualdad.

Se encontró otro defecto en la evaluación de catálogo:
`_collect_catalog_expected_counts` considera cada artículo con producto asociado
como candidato buybox, sin consultar `catalog_listing`, y omite productos de
variaciones. Una consulta de solo conteo desde Mongo en el worker devolvió
938 asociaciones con participación true, 529 false y cero desconocidas; además
hay siete participantes true sin producto. Los 1,467 candidatos del informe
incluyen los 529 no participantes. Por tanto, los 389 supuestos faltantes no
son evidencia suficiente para adquirir o marcar cobertura masivamente. Próximo
trabajo: corregir las expectativas con participación explícita y fuentes de
variaciones, conservar desconocido separado de false, probar ese contrato y
volver a validar los conteos. No se ejecutó escritura de reconciliación.

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
