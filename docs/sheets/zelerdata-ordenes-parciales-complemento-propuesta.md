# ZelerData: opt-in mínimo de órdenes parciales en el complemento

Fecha: 2 de octubre de 2026. **Solo propuesta: no implementada, publicada ni
disponible en Sheets.** El API normal ya permite consultar hechos adquiridos de
órdenes con aviso; el complemento actual no envía ese opt-in. Este documento
propone el puente mínimo, sin rehacer adquisición, añadir fórmula ni debilitar
totales exactos.

## Ruta rápida

1. Autorizar por separado esta adaptación local y sus pruebas enfocadas.
2. Extender únicamente `ZELERDATA_ORDENES` y su alias con un argumento booleano
   final opcional; conservar nombre, seis posiciones existentes y defaults.
3. Enviar `allow_partial:true` al API solo ante `true` explícito y conservar el
   aviso visible devuelto en la tabla. Predeterminado: exacto, como hoy.
4. Probar con harness ejecutable, luego autorizar publicación/versionado del
   complemento y validar una hoja/rango de prueba por separado. El backend/API
   validado localmente no demuestra disponibilidad del complemento en Sheets.

## 1. Qué existe y qué falta

| Área verificada | Estado actual | Cambio mínimo propuesto |
| --- | --- | --- |
| `Formulas.gs`, `ZELERDATA_ORDENES` y alias minúsculo | Seis argumentos; no opt-in. | Séptimo argumento final `permitir_parcial=false`. |
| `Client.gs`, `zelerdataExecute_` | POST al API normal autenticado con `formula`, `cuenta`, `args`, `request_id`. | Opción interna explícita; propiedad superior `allow_partial:true` solo para órdenes y booleano `true`. |
| `Client.gs`, `zelerdataEnvelopeToValues_` | Devuelve `values`; no muestra `meta`. | Preservar sin recortar la fila `PARCIAL` del servidor. |
| API/handler de órdenes | `StrictBool`; opt-in solo para `ZELERDATA_ORDENES`; descarta `_allow_partial` público. | Reutilizar; no cambiar contrato backend ni protección compartida de agregados. |
| Caché | No hay caché de resultados en el complemento; órdenes está fuera de `PRECALCULATED_FORMULAS`. | No crear caché nuevo. Cualquier caché futuro deberá separar exacto/parcial. |

El opt-in permite **solo filas canónicas adquiridas**, no garantiza que sean todas
las órdenes ni que estén frescas. En un intervalo certificado el handler mantiene
la tabla exacta normal, aun si el usuario acepta parciales. En un intervalo no
certificado agrega aviso y `meta.coverage.exact=false`; `pending_count` puede ser
`null`: no deducir el número total de faltantes de las filas descargadas.

## 2. Firma compatible propuesta — todavía no operativa

```text
ZELERDATA_ORDENES(cuenta, fecha_inicial, fecha_final,
                 estado="todos", compradores="", encabezados="",
                 permitir_parcial=false)
```

Aplicar el mismo argumento final a `zelerdata_ordenes`, manteniendo el alias.
No tocar `ZELERDATA_ORDENESPORSKU`, dashboards, sumas, ventas ni otras fórmulas.
No crear menú/global que convierta fórmulas existentes a parcial, ni sustituir
fórmulas del usuario. Argumento final es suficiente; un menú sería más alcance.

**Reglas de entrada:** omisión o booleano `false` mantienen payload/comportamiento
actual. Solo booleano `true` solicita parciales. No activar con `"true"`, `"si"`,
`1`, un rango ni coerción truthy; una entrada explícita no booleana debe producir
error visible de argumento sin llamada HTTP. Una celda que contiene un booleano
real puede suministrar ese booleano; no una matriz/rango multi-celda.

El wrapper puede pasar la opción como cuarto argumento interno del helper, sin
introducirla en `args`. El helper agrega la propiedad superior únicamente cuando
`formulaName === "ZELERDATA_ORDENES"` y opción `=== true`; para otros wrappers el
helper mantiene su llamada de tres argumentos. Nunca enviar `_allow_partial` ni
reinterpretarlo como autorización.

**Ejemplos futuros**, no copiar como función disponible todavía:

```text
# Exacto por defecto; conserva lo que ya usa el usuario:
=ZELERDATA_ORDENES(A1; B1; C1; "todos"; ""; "si")

# Aceptación explícita de filas parciales y su aviso:
=ZELERDATA_ORDENES(A1; B1; C1; "todos"; ""; "si"; VERDADERO)
```

Los separadores/localización dependen de la hoja. No ampliar los selectores de
encabezados: usar `"si"` o `""`, que ya acepta el handler.

## 3. Aviso visible, incluyendo encabezados y vacío

Reutilizar la fila rectangular existente, sin fabricar un mensaje a partir de
`meta` que se pueda perder durante conversión:

> PARCIAL: solo órdenes adquiridas; puede haber faltantes; no es un total exacto.

| Respuesta del API | Resultado exigido en la hoja |
| --- | --- |
| Parcial con encabezados | Aviso **primero**, encabezados después y luego filas; mismo ancho. |
| Parcial sin encabezados | Aviso primero y luego filas; nunca ocultarlo por quitar encabezados. |
| Parcial sin filas adquiridas | Aviso visible, con encabezados si se pidieron; no convertir a celda vacía ni "cero ventas". |
| Intervalo certificado | Tabla exacta actual, sin aviso parcial inventado ni alteración de forma. |
| Error, `PROCESSING`, credenciales o indisponibilidad | Tratamiento visible actual; no convertir errores en tabla parcial. |

La fila de aviso **ya va antes del encabezado en el servidor**. No moverla debajo,
recortarla, sumar filas ni removerla para hacer funcionar gráficos/agregados.
El usuario puede inspeccionar precio/cantidad/comisión de órdenes adquiridas;
campos no adquiridos siguen `NA` y filtros/join que requieran evidencia pueden
seguir no disponibles. No prometer todas las columnas o filtros para toda cuenta.

Si una respuesta se identifica parcial (`coverage.exact=false`) pero no contiene
el aviso rectangular esperado en `values`, el puente debe fallar con advertencia
visible, no mostrar datos silenciosamente como exactos. No duplicar el aviso
cuando ya está presente. No sumar estas filas para ofrecer un total exacto.

## 4. Caché y separación de modos

La adaptación propuesta no añade caché. La implementación actual de órdenes no
usa caché precalculado y Apps Script no usa `CacheService` para sus resultados.
No introducir un caché común por fórmula/argumentos que mezcle ambos modos.

Si posteriormente se añade caché, la clave deberá incluir fórmula, identidad de
cuenta autorizada, argumentos y **modo exacto/parcial explícito**; el valor deberá
conservar aviso/coverage y reglas de frescura. Una respuesta parcial nunca puede
responder una petición exacta, ni una respuesta vacía ocultar el aviso. La llamada
actual al store precalculado usa `payload.args`, no `allow_partial`; por eso no se
debe ampliar su lista a órdenes sin adaptar esta separación y probarla.

## 5. Implementación y aceptación enfocadas futuras

TDD local: escribir primero casos RED del wrapper+cliente real cargados en un
harness Node, luego el cambio mínimo y GREEN. No repetir una ronda general de
perfección ni realizar consultas reales para estas pruebas.

- Omitido/`false`: mismos seis argumentos/defaults, payload sin opt-in y salida
  exacta; canonical y alias minúsculo conservan comportamiento.
- `true`: solamente órdenes envía `allow_partial:true` superior, no `args` ni
  `_allow_partial`; otros wrappers y valores truthy inválidos no lo activan.
- Respuesta parcial con/sin encabezados y cero filas conserva aviso/ancho; caso
  9,999 filas válidas + pendiente por el API normal muestra las filas y aviso.
- Intervalo certificado sigue exacto; default no certificado conserva
  `DATA_UNAVAILABLE`/recovery y los agregados/totales permanecen cerrados.
- Error/`PROCESSING`, token/endpoint y actualización manual mantienen garantías
  existentes; ninguna caché cruza modos. Parcial sin aviso falla visiblemente.

Reutilizar/extender pruebas:

- [Wrapper y cliente existentes](../../modules/sheets/tests/test_apps_script_addon.py):
  prueba de firmas exige hoy igualdad literal contra fixture histórico. Agregar
  una excepción **aditiva y explícita solo para el argumento final de órdenes**,
  comprobando las seis posiciones/defaults intactos; no reescribir silenciosamente
  el [fixture histórico](../../tests/sheets/fixtures/sheetseller_formula_contracts.json)
  ni el contrato backend para hacer pasar el test.
- [Harness de actualización manual](../../modules/sheets/tests/test_apps_script_refresh_execution.py)
  y [cliente ejecutable](../../modules/sheets/tests/apps_script_refresh_harness.cjs):
  reutilizar patrón de servicios locales, sin token real.
- [API parcial autenticada](../../modules/sheets/tests/test_partial_history_api.py):
  conservar la prueba 9,999+1 y protecciones del comportamiento exacto.

Cambios futuros previstos: wrappers/JSDoc en `Formulas.gs`, puente/validación en
`Client.gs`, README del complemento y pruebas enfocadas. Sin scopes nuevos,
provider APIs, esquema Mongo, frontend nuevo ni ajustes de adquisición.
Controles proporcionales: harness Node + pruebas Python afectadas, sintaxis y
coherencia de documentación; al completar código, gates exigidos por el repo.
Versionado/publicación Apps Script y smoke nativo son permisos posteriores.

## Siguiente paso y fronteras

Solicitar autorización **de desarrollo local de esta adaptación**. Esta entrega
publica la propuesta, no el acceso parcial nativo. Para ponerlo disponible se
requieren código/pruebas, versión inmutable del complemento, publicación
expresamente autorizada y prueba humana en hoja/rango aprobados.

[Propuesta de publicación y operación](zelerdata-historico-publicacion-piloto-propuesta.md)
separa backend, builds, respaldo, rollback y piloto.
[RETIROS Full](zelerdata-full-validacion-acotada.md) continúa pendiente externo y
no bloquea otras fuentes. La adaptación no resuelve ni suplanta ese mapeo.
