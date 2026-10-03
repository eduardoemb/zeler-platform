# ZelerData: propuesta de publicación y piloto acotado

Fecha: 2 de octubre de 2026. **Trabajo propio publicado en `main`; fuente validada
`4216e18b62da289c1e67acd1ac8d6db4ba0c9217`, verificada contra el remoto.
Ejecución e identidad se registran en el
[recibo de publicación](zelerdata-historico-publicacion-20261002.md).**
El commit posterior del recibo es exclusivamente documental y no cambia esta
fuente. **Builds, despliegue, consulta API real, backup productivo, permisos/índices
y escrituras en Sheets siguen sin autorización ni ejecución.** La excepción
autorizada fue buscar un retiro por UI en solo lectura, un retiro/≤5 minutos:
se detuvo en 34 segundos ante una cuenta de prueba; no se abrió ningún retiro
ni se obtuvo una referencia real. Para continuar hace falta la pestaña de
Retiros Full de la cuenta legítima, sin cambiar/bypassear sesiones.

## 1. Qué se puede autorizar por separado

| Etapa | Alcance propuesto | No queda incluido |
| --- | --- | --- |
| Publicación — autorizada | Trabajo propio de histórico al vincular y cierres locales, con tests/reportes y propuestas; Conventional Commits, sin atribución IA. | Builds, deploys, pruebas reales, archivos ajenos. |
| Evidencia Full | Muestra de [comprobación acotada](zelerdata-full-validacion-acotada.md): hasta 10 GET, retiro conocido y ≤7 días UTC. | Mapeo supuesto, permisos nuevos, facturación, año completo. |
| Preparación runtime | Inspección actual, backup consistente y restauración aislada; índices/registro estrictamente seleccionados si se autorizan. | Limpieza, reparación por drift, restauración sobre producción. |
| Builds | Una imagen por Cloud Build verificado de commit exacto publicado en `main`. | Deploys, checkout local subido, otros servicios. |
| Despliegue | Gateway, Sheets API y Sheets worker con digests verificados, activación inicialmente apagada y rollback compatible. | Restart amplio, otras APIs/workers, bootstrap no afectado. |
| Piloto | Una cuenta legítima, límites y duración indicados abajo, OAuth/relink sin force. | Otros vendedores, reinicios anuales, ampliación automática. |
| Sheets nativo | Hoja/rangos de prueba expresamente seleccionados. | Publicar add-on, modificar hojas del usuario sin alcance. |

La autorización de publicación ya recibida no aprueba ninguna de las demás etapas. Si una etapa exige cambiar
su alcance, se presenta la diferencia y se espera autorización; no repetir ni
ampliar pruebas reales automáticamente.

## 2. Publicación: contenido y prueba antes de enviar

Checkout seleccionado en `main`. Base observada al preparar: commit externo
`124fd236fea600ead8c1436560a22b1909d7c3c8`, diagnóstico OAuth ajeno conservado.
**No es el commit fuente de esta entrega**. Usar el SHA completo de la entrega
publicada y verificada que registra el recibo de publicación, nunca esta base.

Contenido propio autorizado, conservando pruebas junto a su comportamiento:

1. **Histórico acotado y continuidad:** intención core/OAuth, coordinador, fuentes,
   parciales persistidos, convivencia con recovery, pacing, mantenimiento, packs
   antiguos y scope opcional del piloto; índices, registro y verificador de
   rollback; tests de esos comportamientos y documentación correspondiente.
2. **Consumo explícito de parciales:** API/handler existente, prueba autenticada
   9,999+1 y avisos/cobertura; sin cambiar totales, fórmula ni frontend.
3. **Evidencia y operación:** capacidad compartida y protección Full, informe,
   propuesta/probe; mantener tests junto al comportamiento cuando haya hunks
   dependientes. La partición real no debe dejar imports/tests rotos.

Para el envío autorizado, registrar inventario de archivos/hunks propios y
resultado de los checks ya completados; no abrir otra ronda general de perfección. Preservar todo lo ajeno; no usar stash/reset ni crear
rama/worktree. Stage explícito solo de esas unidades autorizadas,
verificar diff staged, publicar sin force y comprobar SHA remoto = HEAD local y
estado de checkout restante. Ningún dump, audio, token, credencial ni DB entra.
Review opt-in permanece `disabled/unmanaged`; no se fabrica un recibo.

## 3. Destino, imágenes y compatibilidad

Destino documentado, **a confirmar en inspección**: proyecto `zeler-platform-dev`,
VM `platform-vm`, zona `us-central1-a`, Docker Compose. No fue inspeccionado aquí.

| Propietario | Cambio | Imagen que debe compararse/construirse si se autoriza |
| --- | --- | --- |
| Gateway | Admisión durable al OAuth/relink. | `gateway` |
| Sheets API | Progreso, tabla parcial opt-in y manifest. | `sheets-api` |
| Sheets worker | Autoridad, fuentes, recuperación periódica, renovación y scope de piloto. | `sheets-worker` |
| Operaciones | Verificador `infra/deploy/sheets_rollback.py`; índices/seed. | Herramientas/contratos por rollout separado, no otra imagen por costumbre. |

Publicada la fuente, falta verificar drift entre SHA autorizado de `main` y fuente de
imágenes en ejecución. Si falta evidencia de runtime, no declarar actualizado.
Builds desde repositorio conectado, SHA completo presente en `main`, una imagen
por build, `options.requestedVerifyOption: VERIFIED`; registrar build ID, fuente,
SUCCESS y `repo@sha256:...`. **No builds Docker locales.**

El manifest, seed y verificador locales exigen **15 scopes / 6 routing keys**;
fingerprint completo:
`bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d`.
Los 13 scopes de la etapa anterior descrita en deploy no prueban este contrato.
No añadir permisos de envío/marcado como leído ni scope de detalle Full por
escribir una propuesta: el probe detiene una denegación.

## 4. Baseline, capacidad y respaldo antes del piloto

Inspección de lectura desde VM/VPC aprobados: raíz y Mongo (bytes e inodos), mount
Mongo, RAM disponible, uso Docker, salud, restart count y OOM; readiness gateway,
componentes/consumidores Sheets y backlog. Output seleccionado/sanitizado, nunca
`env`, cadena Mongo, headers o cuerpos de mensajes. `--dry-run` del preflight no
atestigua procedencia ni rollback. Medir ≥5 GiB libres en `/` antes de **cada**
pull, incluso rollback, y revalidar después. Mongo/RAM se miden aparte; no inventar
un umbral ni resize/prune. Limpieza requiere alcance explícito y no incluye volúmenes.

Baseline de la cuenta: identidad linked legítima/estado, plan y corte, presupuesto
consumido por fuente, intervalos exactos, certificados/hash/versiones, conteos y
pendientes. Conservar junio sano y otros intervalos independientes. Detectar
trabajo legacy activo/conflictivo: esperar/delimitarlo, no borrarlo ni coalescerlo
sin autorización. El presupuesto del plan no cuenta llamadas de otro worker.

### Respaldo propuesto y criterio obligatorio

- Autorizar una ventana de quiescencia de los **writers Sheets afectados** desde
  VM, con ACK/NACK y stop grace respetados; Rabbit conserva entregas, no purge.
  Confirmar que no haya otro escritor de las mismas colecciones antes de tomar
  respaldo lógico consistente. Si no puede garantizarse, detener esta etapa y
  proponer snapshot consistente aprobado; no asumir que un dump concurrente lo es.
- Alcance: hechos canónicos afectados (`orders`, `questions`, `shipments`, `claims`,
  devoluciones, `messages`), modelos/proyecciones consumidos, planes/pending,
  adquisiciones/receipts/ranges, recovery jobs/admission, runs/operaciones,
  certificados/cobertura/freshness e índices/validadores de ese conjunto. Generar
  inventario exacto del checkout y runtime antes del dump; incluir relaciones de
  prueba, no solo filas visibles. Capturar config Compose/registro por separado.
- OAuth, claves e identidades no se usan como material de restore del piloto.
  No imprimir/exportar tokens. Si un snapshot contiene secretos ajenos al alcance,
  protegerlos y restaurar únicamente namespaces aprobados, nunca cuentas/tokens.
- Crear desde contexto aprobado archivo protegido (`0600`) y destino privado
  cifrado **a elegir y autorizar**, con acceso mínimo, hash y manifiesto sin datos
  personales. Propuesta de retención: siete días tras aceptación/rollback, luego
  borrado expresamente autorizado; no inventar un bucket ni configurar uno ahora.
- Restaurar en rs0/base **aislada**, con destino distinto y sin app/product worker
  conectado. Comprobar conteos, hashes canónicos, índices/validadores, joins,
  certificados/lectores, y preservación en origen de un hecho posterior al corte.
  Un restore no se hace encima de producción para obtener esta evidencia.
- Reanudar solo writers autorizados, comprobar backlog y salud/capacidad después.
  Registrar corte/consistencia y resultado. Si restaura mal o no hay recuperación
  segura demostrada, **no iniciar el piloto**.

El ensayo sintético local anterior no sustituye este backup ni su validación.

## 5. Despliegue y rollback seleccionados

Guardar identidad inmutable **de contenedores ejecutados**, no solo tags de Compose,
y configuración previa. Conservar rollback recuperable que acepte scopes nuevos,
jobs `policy_authority`, datos/proofs y topología. Un worker antiguo que ignore
esa autoridad puede ejecutar jobs por otro camino: **no es rollback compatible**.

Orden propuesto, sujeto a verificación de compatibilidad exacta:

1. Registrar/atestiguar rollback compatible con 15 scopes y frontera de autoridad.
2. Aplicar solo índices/registro aprobados desde VM y comprobar dependencias,
   sin aplicar validadores como supuesto health check. Nuevas colecciones internas
   no tienen validador core nuevo; verificar los canónicos reutilizados.
3. Desplegar API/worker compatibles con flag onboarding apagado. Worker entiende
   la autoridad antes de que se admita más trabajo; API registra permisos nuevos.
4. Desplegar gateway cuando el camino `accounts.linked` esté listo; comprobar
   `/ready`, dependencias y publicación, no únicamente `/health`.
5. Verificar digests, readiness de consumidores, operación/progreso y asentamiento;
   repetir salud y capacidad. No usar broad Compose restart.
6. Configurar solo piloto/plan autorizado y habilitar flag en worker como abajo.

Retirada: desactivar onboarding mediante cambio/restart acotado autorizado y
esperar/graceful-stop de la unidad en ejecución; no borrar jobs/planes ni sus
hechos. Después, restaurar únicamente imágenes compatibles y config aprobada.
Si queda un job con lease, esperar vencimiento/protocolo, no forzar takeover.
La tabla partial API puede retirarse junto con opt-in/handler sin borrar filas.
No bajar scopes ni restaurar toda Mongo para que un rollback parezca verde.
Cualquier reparación de datos debe ser por alcance, comparar revisiones y preservar
OAuth/identidades/hechos posteriores; autorización separada, fail-closed mientras.

## 6. Piloto inicial: una cuenta, límites explícitos

**Candidato:** vendedor `82453304`, solo si legítimamente linked y operador acepta
la cuenta. Relink normal, sin force, tokens copiados, limpieza para simular vacío
ni reemplazo de cutoff/checkpoints. No asumir Full aplicable.

Configuración del worker dentro del despliegue autorizado:

```text
ZELERDATA_HISTORY_ON_LINK_ENABLED=true
ZELERDATA_HISTORY_ON_LINK_SELLERS=82453304
```

La lista opcional cerca el claim real **antes de renovar/adquirir**; ausente activa
el comportamiento normal multicuenta. Vacía/wildcard/IDs no canónicos fallan startup.
Para este piloto no dejarla ausente. Mantener pacing compartido existente (default
180/min, verificar valor efectivo), no elevarlo ni atribuirle justicia universal.

Antes de habilitar, obtener plan por OAuth auténtico con flag apagado y, bajo
**autorización explícita desde VM**, restringir autoridad persistida a cinco fuentes
(Full excluido hasta mapeo) y bajar límites remanentes. No reiniciar consumed,
corte, jobs, snapshots ni otras cuentas. Si el plan ya agotó una cuota, no elevarla
como "reset": declarar pendiente y pedir otro alcance.

| Fuente | GET iniciales adicionales máximos |
| --- | ---: |
| Órdenes/comisiones | 800 |
| Preguntas/respuestas | 150 |
| Envíos/costos dependientes | 250 |
| Mensajes | 300 |
| Reclamos/devoluciones | 500 |
| Full | 0; probe aparte, máximo 10 GET sin publicación de coverage. |
| **Total inicial** | **2,000** |

Mantenimiento: máximo **500 GET adicionales** durante el ensayo, ≤300 por fuente;
autoridad diaria separada, límite remanente sin subir cuotas originales. Ejecutar
**90 minutos máximo dentro de un mismo día UTC**, y detener a 2,500 GET físicos
adicionales del coordinador piloto. Medir tráfico habitual ajeno por separado;
no imponerle este presupuesto ni detener otros productos. Si los smokes admiten
recovery legacy adicional, delimitar/autorizar su presupuesto antes de ejecutarlos,
no ocultarlo en estos counters. Si no es posible medir/limitar todos los intentos
atribuibles al ensayo, no activar. Concurrencia de claim: una
unidad de cuenta/lease; fuente rota, cada collector mantiene sus límites. No
prometer acabar el año con este presupuesto; el corte sigue 12 meses calendario,
la prueba acredita solo intervalos/conjuntos efectivamente completados.

Stop: auth no válida/denegación relevante, revocación/pausa, presupuesto o tiempo,
429 persistente, error canónico/certificado, modificación ajena de lease/scope,
regresión de cobertura sana, restart/OOM, readiness caída, disco bajo piso o
backlog/latencia viva deteriorados frente al baseline. No ampliar ventana, fuentes,
cuotas ni efectuar repairs automáticamente; preservar pendientes y evidencia.
Pausar el coordinador no autoriza parar otros productos/workers.

## 7. Aceptación y límites de evidencia

- Plan/progreso persisten, dos visitas no reabren año, llamadas físicas ≤ cuotas,
  canonical publication útil independiente y datos previos/otros sellers intactos.
- Sample del lector/handler/API normal, no solo repositorio privado. ORDENES con
  `allow_partial:true` devuelve adquiridos + aviso, nunca un total exacto. Default
  y agregados afectados continúan no disponibles; intervalo sano sigue disponible.
- Mensaje nuevo en pack antiguo conocido: verificar orden sin cambios, fuente,
  fecha/ID consistente y publicación al completar visita natural del cursor.
  Rotación requiere páginas porque la API no acredita orden incremental: no hay
  garantía de latencia. Si cuota/tiempo impide llegar al pack, declarar pendiente;
  no mover cursor para fabricar aceptación.
- Certificados poblados siguen válidos con renovaciones y hash consistente; renovar
  localmente no acredita cambios de fuente.
- Dos incrementales con **cambios reales** posteriores al corte (órdenes,
  respuestas/mensajes/devoluciones aplicables), detección→persistencia→lector.
  Dos ciclos vacíos no satisfacen el criterio; no fabricar compras/mensajes.
- Sheets: hoja temporal privada y rango autorizado, muestra acotada de fórmulas
  existentes en período sano y afectado. Firma del add-on no expone `allow_partial`:
  comprobar API opt-in aparte, **no afirmar consumo parcial nativo**. Publicación
  del add-on o nuevo acceso nativo requiere otro desarrollo/alcance autorizado.
  La [adaptación mínima propuesta](zelerdata-ordenes-parciales-complemento-propuesta.md)
  conserva la firma existente y default exacto con un opt-in final; **no está
  implementada ni disponible en Sheets**.
- Evidencia sanitizada: conteos/rangos/hash/tipos/status/budget/digest; no compradores,
  texto de mensajes, cuerpos, credenciales o cadenas de conexión.

Resultado final clasificado por fuente: completado local, bloqueo externo preciso,
validación productiva aprobada/no comprobada. No convertir 90 minutos, HTTP200,
container running, una muestra correcta o tests verdes en cobertura anual.

## 8. Autorizaciones concretas listas para completar

Son permisos **independientes**. Ningún texto es una instrucción ejecutada.
SHA fuente ya publicado y verificado: `4216e18b62da289c1e67acd1ac8d6db4ba0c9217`.
Comprobar que sus 36 archivos fuente siguen iguales a la validación y que el
commit continúa presente en `origin/main`; el recibo posterior es solo documental. No usar `main`
movible, base anterior ni checkout local como sustituto. Rechazar una expansión
no aprobada; los digests y el baseline se incorporan antes de pedir despliegue.

### A. Tres builds; no operación runtime

> Autorizo exactamente tres Cloud Builds en `zeler-platform-dev`, región
> `us-central1`, desde el repositorio conectado
> `projects/zeler-platform-dev/locations/us-central1/connections/zeler-platform-github/repositories/zeler-platform`,
> al commit `4216e18b62da289c1e67acd1ac8d6db4ba0c9217` presente en `main`. Una imagen por build:
> `gateway` (`gateway/Dockerfile`), `sheets-api`
> (`modules/sheets/Dockerfile.api`) y `sheets-worker`
> (`modules/sheets/Dockerfile.worker`), en el Artifact Registry existente
> `us-central1-docker.pkg.dev/zeler-platform-dev/zeler-platform`.
> Exijo `options.requestedVerifyOption: VERIFIED`, SUCCESS, procedencia del
> repositorio/SHA exactos, build ID y digest inmutable de cada imagen. No autorizo
> imágenes adicionales, build local, despliegue, pull en VM, limpieza ni consultas
> reales a Mercado Libre. Si falla un build, reportar; no ampliar ni repetir una
> ejecución incierta automáticamente.

### B. Inspección read-only y drift; no backup ni repair

> Autorizo una inspección de lectura de `platform-vm`, zona `us-central1-a`,
> proyecto `zeler-platform-dev`, desde el contexto VM/VPC permitido: capacidad,
> mount Mongo, memoria, Docker, salud/readiness/backlog y las identidades inmutables
> de gateway/Sheets API/worker en ejecución. Comparar fuente desplegada con
> `4216e18b62da289c1e67acd1ac8d6db4ba0c9217` cuando haya procedencia verificable. Usar preflight
> `--dry-run` y salida sanitaria seleccionada. No autorizo downloads, atestiguación
> que descargue imágenes, backup, validator/index/registro, cleanup, restart,
> reparación ni consulta de Mongo productivo desde el asistente local.

La inspección define los **digests anteriores**, headroom y writers efectivos.
Si no permite probar compatibilidad, no asumir rollback seguro ni runtime actual.

### C. Respaldo consistente y restore aislado; no restauración productiva

Antes de presentar esta aprobación, completar: inventario exacto de namespaces
relacionados de §4, writers Sheets a pausar y stop grace, ventana, destino privado
cifrado existente con acceso mínimo, destino rs0/base aislada y plazo de retención.
No autorizar un comodín `todos los servicios/colecciones` ni inventar un bucket.

> Autorizo el respaldo de `<NAMESPACES_EXACTOS>` desde VM/VPC de `platform-vm`
> mediante quiescencia de `<WRITERS_SHEETS_EXACTOS>` durante `<VENTANA>`; respetar
> ACK/NACK, stop grace y conservar entregas Rabbit. Archivo protegido 0600 hacia
> `<DESTINO_PRIVADO_CIFRADO>`, inventario/hash sanitizados y retención acordada
> `<PLAZO>`. Autorizo restaurarlo únicamente en `<RS0_Y_BASE_AISLADOS>`, sin app ni
> workers conectados, comprobando conteos, hashes, índices/validadores, joins y
> lectores/certificados, sin tocar OAuth/identidades y preservando hechos del
> origen posteriores al corte. Reanudar solo los writers aprobados y comprobar
> salud/backlog/capacidad. Si no puede probarse consistencia o restauración,
> detener y reportar. No autorizo restore sobre producción, purge, limpieza,
> reparación de datos ni inicio del piloto.

### D. Rollout: pedir después de conocer digests y rollback compatible

**No listo para ejecutar hasta completar** los tres digests destino, identidades
anteriores/rollback recuperables y atestiguadas, inventario exacto de índices/seed,
config anterior y verificación de §5. Un permiso de build no cubre este texto.

> Autorizo rollout acotado en `platform-vm` del commit
> `4216e18b62da289c1e67acd1ac8d6db4ba0c9217` a gateway=`<DIGEST_GATEWAY>`,
> Sheets API=`<DIGEST_API>` y worker=`<DIGEST_WORKER>`, con onboarding apagado.
> Aplicar únicamente `<INDICES_Y_REGISTRO_EXACTOS>` aprobados, 15 scopes/6 routing
> keys y fingerprint `bd13debfb57bba5a24d78fad93d371766cda8c6f288b70d93c9023788b09c16d`.
> El rollback acordado `<DIGESTS_ROLLBACK_Y_CONFIG>` debe aceptar `policy_authority`,
> cuotas/checkpoints y pruebas/datos persistidos, no solo arrancar. Respetar el
> orden API/worker compatibles antes de admisión gateway y readiness de
> `accounts.linked`; ≥5 GiB libres antes de cada pull y después. Reemplazar
> únicamente servicios seleccionados, verificar digests/readiness/comportamiento
> y repetir salud/capacidad tras asentamiento. Rollback solo compatible dentro de
> este alcance; no bajar scopes, borrar jobs, broad restart, prune de volúmenes ni
> restaurar toda Mongo. No autorizo activación piloto ni consultas Full.

Un worker previo de 13 scopes o que no entiende `policy_authority` **no** es
rollback compatible. Si no existe imagen compatible recuperable, preparar y
pedir autorización para esa alternativa exacta antes del rollout; no construir
una cuarta imagen con el permiso A ni seleccionar un tag antiguo por conveniencia.

### E. Piloto: una cuenta; Full excluido

> Tras aprobar baseline, respaldo/restore y rollback de las etapas anteriores,
> autorizo el piloto para vendedor `82453304` solo confirmado legítimamente
> linked. Relink normal si es necesario, sin force ni copiar tokens. Activar
> onboarding con `ZELERDATA_HISTORY_ON_LINK_SELLERS=82453304`, ajustar solo la
> autoridad del plan preservando cutoff/consumed/checkpoints y fuentes de §6:
> hasta 2,000 GET físicos iniciales adicionales y 500 de mantenimiento (máximo
> 300 por fuente), 90 minutos dentro del mismo día UTC; máximo total 2,500.
> No subir cuotas agotadas, habilitar Full, otros sellers ni legacy adicional sin
> presupuesto separado. Usar pacing compartido, verificar datos útiles/progreso,
> cobertura sana y dos ciclos con cambios reales existentes/consentidos; no
> fabricar transacciones. Detener al límite/condiciones de §6 mediante cambio
> acotado autorizado del worker; preservar jobs y evidencia, sin repairs.
> Para Sheets nativo autorizo solo `<HOJA_TEMPORAL_Y_RANGOS>` y fórmulas actuales
> exactas; el opt-in parcial del complemento no está implementado ni incluido.

**Full permanece bloqueado externamente, sin bloquear las otras cinco fuentes.**
Su autorización de hasta diez GET se pide por separado cuando se identifiquen
en la sesión legítima o el operador aporte vendedor, inventario, referencia
retiro/bulto, cantidades/fechas conocidas y
ventana UTC de hasta siete días en [la propuesta Full](zelerdata-full-validacion-acotada.md).
No solicitar tokens al usuario ni interpretar la entrega de esos datos como
permiso de ejecución.

## Referencias

- [Informe y matriz local](zelerdata-historico-al-vincular-implementacion.md).
- [Especificación](zelerdata-historico-al-vincular-especificacion.md), §§10–12.
- [Runbook deployment](../deploy.md), [preflight](../../infra/gce/docker-deploy-preflight.sh).
- [Probe Full](zelerdata-full-validacion-acotada.md).
- [Opt-in parcial mínimo del complemento — solo propuesta](zelerdata-ordenes-parciales-complemento-propuesta.md).
