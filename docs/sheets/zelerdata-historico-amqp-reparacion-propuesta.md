# ZelerData — propuesta condicional: retry de un segundo

**DECLARACIÓN CONFIRMADA / METADATA Y BINDING VERIFICADOS.** El usuario autorizó resolver la cola faltante:
«Bien, resuelve la cola de reintento que hace falta, te autorizo lo que necesites».
Aplicar únicamente la reparación y verificación acotadas descritas aquí; no
convertirla en permiso de expansión del piloto o cambios generales al broker.
Esta propuesta no solicita de nuevo despliegue/piloto. El cleanup AMQP falló y se
conserva sin repetir la declaración. La lectura posterior se detuvo en retry5s;
la continuación necesaria está en [buckets restantes](zelerdata-historico-amqp-retries-restantes-propuesta.md).

## Motivo y condición

La lectura Management del 5 de octubre devolvió HTTP404 en
`zeler.sheets.claims.retry.1s`, después de verificar cinco colas y sus bindings.
HTTP404 por sí solo no demuestra ausencia. Una comprobación pasiva distinta,
con una conexión propia y sin crear/consumir mensajes, confirmó broker404
`NOT_FOUND` del recurso exacto a23:44:15–21UTC. Su cleanup reportó tool_error:
proceso transitorio terminado, sin prueba de cierre limpio/server-side ni retry.

El bucket sigue requerido por el primer retry transitorio del worker actual.
No se declara en startup ni durante retry: `consumer.py:156–162,775–797,1052–1061`.
El operador general `prestart` está excluido: puede drenar/eliminar legacy.

## Única mutación propuesta

Desde el worker legítimo de `platform-vm`, `zeler-platform-dev/us-central1-a`,
usando la conexión existente configurada (sin imprimir/copiar credenciales):

- Declarar exclusivamente `zeler.sheets.claims.retry.1s`.
- `durable=true`, `exclusive=false`, `auto_delete=false`.
- Argumentos: `x-message-ttl=1000`, `x-dead-letter-exchange=""`,
  `x-dead-letter-routing-key="zeler.sheets.claims"`.
- Binding del exchange default al nombre de la cola: automático del broker;
  no agregar routing keys al exchange `meli.events` ni cambiar las seis existentes.

No policies/global settings, otras colas/exchanges, datos, trabajos, índices,
validators, flags, IAM, capacidad, limpieza, mensajes de prueba ni Meli/Full.
Conservar operator limits existentes; no cambiar sus valores por esta propuesta.

## Gates, presupuesto y STOP

1. Ausencia confirmada pasivamente; identidad/digest/tool frozen comprobados.
2. Procedimiento y recibos sanitizados probados offline con TDD antes de usarlo.
   Resolver offline el tratamiento de cleanup/cierre para la futura herramienta,
   sin repetir la comprobación pasiva ni convertir su error en cierre acreditado.
3. Una sola declaración activa, una conexión propia, máximo cinco minutos.
4. Si otro actor creó una cola equivalente, conservarla: la declaración debe
   comprobar equivalencia. Diferencia, timeout/error/resultado incierto → STOP;
   no retry ni borrado/recreación para imponer argumentos.
5. Verificación posterior de solo lectura, limitada a los trece GET pendientes
   necesarios del inventario seleccionado, máximo60s/64KiB/body; registrar el
   consumo previo13 y posterior por separado, sin reiniciar el ledger.
6. Esta verificación no demuestra publisher-confirm, tiempos reales, admisión
   segura, despliegue ni aceptación. Los gates restantes permanecen independientes.

## Recuperación compatible

No borrar automáticamente la cola creada, aunque aparente vacía: podría recibir
mensajes concurrentes. Conservarla durable/compatible con el worker antiguo y el
nuevo; dejar adquisición cerrada si falla verificación. Nunca drenar, purgar,
consumir, ACK/requeue manualmente ni resetear jobs/counters para recuperar.
Cualquier acción distinta requerirá una propuesta y autoridad separadas.

## Evidencia y siguiente decisión

[Ledger único](zelerdata-historico-paralelo.md),
[inspección revisada](zelerdata-historico-amqp-revisado-informe.md).
La comprobación pasiva ya confirmó ausencia; su fallo de cleanup se conserva.
La declaración compatible fue confirmada a00:35:27–35UTC del6octubre y su metadata/
bindingHTTP200 se verificaron a00:36:45–50UTC. `created_by_us=null`: no inferir
autoría por una declaración equivalente. Cleanup tool_error/waitererror,
close solicitado localmente; no cierre remoto probado. Preservar ese resultado.
No consumir presupuesto productivo adicional para repetir/mejorar ese recibo.
