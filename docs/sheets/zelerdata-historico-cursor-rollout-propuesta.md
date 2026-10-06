# ZelerData — rollout cerrado y continuación de Questions

## Decisión pendiente, sin permisos repetidos

Los permisos condicionales existentes de publicación/build/despliegue seleccionado
se conservan. **No hay nueva ventana productiva:**08:17:23 UTC expiró. La excepción
a solicitar cuando el operador de cadena esté verificado es únicamente una nueva
pasada de Questions, preservando el checkpoint original inmutable, y hasta dos
horas adicionales desde la recepción de esa aprobación. No ampliar seller,
fuentes, cuotas, día UTC, cutoff ni IDs. Full sigue excluido.

## Alcance exacto

- Proyecto `zeler-platform-dev`; VM `platform-vm`; zona `us-central1-a`.
- Seller único `82453304`, ejecución `868b413e20184befb7e8358e0051924f`.
- Fuente worker `c1da1ee389d14cf8719f07c0179289eb3a2c61ba` en main/remoto.
- Build `1cb205ef-d78c-4d07-acd2-0a1626224d39`: SUCCESS, connected repository
  exacto, VERIFIED, verificador de procedencia PASS.
- Target único:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:de632a0a8fff5f1adf1a4dded7a24fd40b48c2a914fcc0fbef7815f99608a28c`.
- Imagen anterior/rollback:
  `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform/sheets-worker@sha256:0df26cd905e49ae7e1d0185e967d1f0090491881aba237de86a3fa61a17610bc`.
- API `3f7ac7c…` y Gateway `4f90ba7…` no se reconstruyen ni reemplazan.

## Orden y límites

1. Preflight readonly sobre **nueve overlays reales**, no script antiguo de tres
   capas. Revalidar inmediatamente antes de pull:>=5 GiB libres en `/`, capacidad
   para imagen/rollback, inodos, memoria, Mongo mount y estado de contenedores.
   Sin prune, limpieza, descargas de imágenes no afectadas ni cambios a Mongo disk.
2. Añadir override cerrado con dos diferencias únicas: worker image target y
   `ZELERDATA_HISTORY_ON_LINK_ENABLED=false`. Mantener HOLD=true, recovery/refresh
   OFF, demás env/servicios exactamente iguales. Pull solo target; comprobar
   capacidad después. Recreate únicamente `sheets-worker`, no dependencias.
3. Verificar digest ejecutándose, salud/restarts0/OOMfalse, readiness de componentes,
   API/Gateway preservados y repetir tras60s. No atribuir cobertura a esos checks.
4. Mutación Mongo separada y limitada a la nueva colección
   `sheets_history_checkpoint_versions`: crear si está ausente con el validator e
   índice único publicados; si existe, comparar definición/documentos y STOP ante
   drift. No reparar validators ajenos, borrar archivos/versiones ni consultar Mongo
   productivo desde local. Todo desde runtime/VM aprobado, salida sanitizada.
5. Solo con aprobación temporal realmente recibida: obtener pausa actual/counters
   y pins **wire** frescos, atestar la extensión padre aplicada y cadena nueva.
   Prórroga cambia únicamente `execution_until`; no prepare/UUID/día/cuota nuevos.
6. Readmisión opt-in canónica DB-only: snapshot/majority, archive original head+job
   byteigual y CAS completo, misma identidad/generación/fechas, pass/revision nuevos
   y secuencia global que no retrocede. Plan solo añade fence de metadata; no
   reembolso. Capturar nuevo planhash/consumption/pause auténticos después.
7. Armar HISTORY y resumir la misma ejecución solamente con recibos pinados y
   monitor propio. Dos manifests completos concordantes para Questions; payloads
   verificados se materializan con procedencia explícita, missing fields usan solo
   fallback acotado. No volver a enviar el cursor vencido ni repetir el original
   CLAIMS ya completado. STOP/pause inmediata al primer error/429/timeout/conflicto,
   inconsistencia, límite, día/deadline; sin consumir saldo restante por diagnóstico.

## Preservación y aceptación

Baseline observado81 cargos/79 envíos (57 iniciales,24 mantenimiento), sin reembolso.
Preservar caps iniciales800/150/250/300/500, total2000, diario500/source300 y total
físico2500 incluyendo retries. Registro14 sin Full, seis routing keys, datos,
13 bootstrap jobs, checkpoints/leases/cutoff y otros sellers no se modifican.

Local verificado:6571 PASS/20 SKIP,19 protectores PASS/0 SKIP, ocho gates PASS,
readmisión Mongo real aislada PASS. Producción todavía debe probar cinco fuentes
recuperables/calendario12 meses y lectura independiente, API normal y Sheet nativa,
más dos ciclos con cambios genuinos; sin inventar evidencia de eventos o negocio.

Rollback después de readmisión es **cerrado**: imagen anterior, HISTORY OFF,
HOLD=true/PAUSED; conservar nuevo head, archive, trabajos y contadores. Nunca
restaurar el checkpoint anterior para simular un reset compatible.

## Medición de preparación

Preflight09:47:49.240101 UTC PASS/9.492s/SSH0/0writes/0Meli: root34,402,926,592
bytes libres; Mongo47,453,102,080 libres en mount `/dev/sdb`, ext4; memoria disponible
1,742,300 KiB. Tres contenedores saludables/restart0/OOMfalse; Gateway dependencies2
OK, worker components3 OK; API solo container-health (no afirmar comportamiento).
Son mediciones fechadas, no sustituyen recheck antes de pull/despliegue.

Ledger único: [zelerdata-historico-paralelo.md](zelerdata-historico-paralelo.md).
