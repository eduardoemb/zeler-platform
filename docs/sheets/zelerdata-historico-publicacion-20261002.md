# ZelerData: recibo de publicación y autorizaciones pendientes

Actualización: 3 de octubre de 2026 UTC. **Implementación original C1/C2 y
corrección propia C3 publicadas en `main`; fuente validada vigente:
`aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d`.** No se hicieron builds ni despliegues.
La búsqueda Full autorizada sí se ejecutó y cerró por 429 tras 7/10 GET, sin
referencia auténtica; el usuario cerró la investigación y no se usarán ni
programarán los tres restantes. Parciales nativos en Sheets siguen sin implementar.
Este follow-up es exclusivamente documental: registra C3 ya publicado y evita
atribuirse un SHA futuro propio; las imágenes propuestas usan C3, no este recibo.

## Fuente actual C3 validada/publicada y delta exacta

- Commit **`aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d`**:
  `fix(sheets): scope Full acquisition to owned inventories`.
- Parent exacto C2: `55ef7ab0b1e879b998e1d657469572660396539f`.
- Solo seis archivos propios: `onboarding_sources.py`, tres tests
  (`test_onboarding_sources.py`, `test_full_onboarding_handler.py`,
  `test_history_onboarding_shared_capacity.py`) y los dos reportes de histórico/
  validación Full. Sin código ajeno, dumps, DB ni credenciales.
- Root comprobó hashes de los cuatro blobs ejecutables staged y del commit
  contra el snapshot congelado ya validado; push sin force, SHA remoto
  `refs/heads/main` exactamente igual a C3 y checkout limpio al terminar ese push.
- Validación existente, no repetida para publicar: **5,820 aprobadas, 0 fallos,
  9 skips; 381.04 s**, más **8 rs0 protegidas aprobadas/0 skips** y **28 focused**.
  Ruff, formato (643 archivos), mypy completo (643 archivos), direct-Meli lint y schema-export aprobados.
  Los ocho skips de guard de suite se cubrieron con rs0 separado; restante Caddy
  sin claves requeridas. Review sigue `disabled/unmanaged`.
- Comparación de objetos C1→C3 confirmada: **32 de los 36 hashes originales
  permanecen iguales; solo cuatro cambian** y coinciden con los valores nuevos
  de esta tabla. La tabla original de 36 filas al final se conserva como evidencia
  histórica de C1, no se reescribe para simular que C1 contenía el fix.

| Archivo actualizado | SHA-256 validado de C3 |
| --- | --- |
| `modules/sheets/src/zeler_sheets/onboarding_sources.py` | `3ed6551f9bad782ac5e7fe6a28d18e55c1e2e187cada197ce471c52fa894dec6` |
| `modules/sheets/tests/test_onboarding_sources.py` | `9224817d46d1f52a9f03bcacf3af44d2cd858f61edd425bdeff70ca127bc5f9e` |
| `modules/sheets/tests/test_full_onboarding_handler.py` | `5c9beac81b4249dc71a275a6d3074a30a2d7ed00068390236145e768ad2a7b9a` |
| `modules/sheets/tests/test_history_onboarding_shared_capacity.py` | `3526b4e5df20d95d0185dc7b9948f0043ad7fa0febe593158f1f77ff6dd5322e` |

Un commit posterior de este follow-up documental conservará el código/config/tests
de C3; root comprobará esa equivalencia y el SHA remoto después de publicarlo.
No se escribe aquí su futuro SHA para evitar autorreferencia. **Fuente recomendada
para los tres builds propuestos: C3 exacto**, sin referencia móvil ni checkout
local subido. Publicar no demuestra drift resuelto ni procedencia desplegada.

## Fuente original C1/C2 y conservación — evidencia histórica

- Base ajena preservada: `124fd236fea600ead8c1436560a22b1909d7c3c8` (diagnóstico OAuth).
- SHA fuente validado/publicado (`feat(sheets): add bounded history-on-link onboarding`):
  `4216e18b62da289c1e67acd1ac8d6db4ba0c9217`.
- Envío: `124fd23..4216e18`, sin force. Después del push, `git ls-remote origin refs/heads/main` coincidió exactamente con HEAD; checkout limpio.
- Este commit fuente permanece como ancestro de `main` tras el recibo documental. **Fue la fuente recomendada para el snapshot original**; la fuente vigente de builds es C3 exacto, arriba, no C1 ni una referencia móvil.
- Snapshot validado: 36 archivos de código/configuración/pruebas; SHA-256 del mapa JSON ordenado compacto:
  `9e424d1487d0a7334a90032aa59ad55d2ab6fbe7a70b50e036336000c9126c8e`.
- Verificados los 36 blobs staged y los 36 blobs del commit contra los hashes por archivo siguientes; el follow-up documental conserva exactamente este código/configuración/tests. No se incluyen dumps, DB, credenciales ni trabajo ajeno.
- Gates ya realizados sobre este snapshot: Linux **5,808 passed / 9 skipped** (402.77 s), más rs0 protegido **8 passed / 0 skipped** (2.10 s). Ruff, format (643 archivos), mypy completo (643 archivos), direct-Meli lint y schema-export: éxito. No se abre otra ronda general; documentación y equivalencia de fuente se verifican al publicar.
- Detalle y limitaciones de los skips/entorno: [informe local](zelerdata-historico-al-vincular-implementacion.md). Review opt-in: `disabled/unmanaged`, no aprobación fabricada.

## Pendientes explícitos y Full cerrado

- **RETIROS Full:** jerarquía retiro/bulto, cantidad solicitada y fecha siguen sin
  evidencia auténtica de mapeo; no bloquea las otras cinco fuentes. La corrección
  de inventarios de C3 no convierte movimientos de stock en retiros.
- Búsqueda UI inicial histórica: detenida en 34 s ante una cuenta de prueba, sin
  abrir retiro ni cambiar sesión. No se propone volver al navegador.
- [Descubrimiento técnico posterior](zelerdata-full-validacion-acotada.md):
  HOPEMOB legítimo verificado dentro de VM, búsqueda read-only por gateway;
  tres GET previos más cuatro de una ejecución autorizada = **7/10 acumulados**,
  últimos 200/200/200 vacíos y 429/over_quota; postcheck audit confirma 7 GET y 14 scopes sin cambios.
  No hubo referencia útil. Usuario cerró investigación Full: **no ejecutar ni
  programar los tres sin usar**, no retry ni otra propuesta de consulta.
- Runtime observado: 14 scopes por permiso search individual previamente
  autorizado y respaldado. Contrato local de 15 scopes/6 keys **no declarado
  desplegado**. Readiness de contenedor/imports no atestigua fuente/digest actual.
- [Complemento parcial](zelerdata-ordenes-parciales-complemento-propuesta.md): solo
  propuesta del séptimo argumento booleano, default falso, aviso visible y totales
  protegidos. **No implementado ni disponible en Sheets.**

## Operación posterior, no autorizada

Usar **`aeefe993ad5c9a4ff4760c9b691ac11ad47b5a6d`** para las tres imágenes afectadas: `gateway`, `sheets-api`, `sheets-worker`. Fuente desplegada, procedencia y digests actuales **no atestiguados**; verificar drift, no asumir que el runtime contiene esta entrega. Se recomienda un nuevo Cloud Build por servicio afectado, sujeto a autorización separada y procedencia verificada. No se ha construido ni desplegado nada.

[Propuesta operativa](zelerdata-historico-publicacion-piloto-propuesta.md#8-autorizaciones-concretas-listas-para-completar):

1. **A — tres builds:** repositorio conectado, SHA exacto de main, una imagen por build, `VERIFIED`; sin pull/deploy/consulta real.
2. **B — lectura VM/VPC:** identidad de imágenes, drift, capacidad/readiness/backlog; sin descarga, repair ni restart.
3. **C — respaldo:** completar namespaces/writers/ventana/destinos privados; quiescencia y restore aislado verificado, sin restaurar producción.
4. **D — rollout:** completar tres digests y rollback recuperable compatible con 15 scopes/6 keys y `policy_authority`; API/worker antes de admisión gateway, flag apagado. Sin borrar datos/jobs ni bajar scopes; ≥5 GiB raíz antes de cada pull.
5. **E — piloto:** solo vendedor `82453304` legítimamente linked, hasta 2,000 GET iniciales + 500 mantenimiento, ≤90 minutos/un día UTC, Full excluido. Preservar corte/consumed/checkpoints y cobertura sana; dos ciclos con cambios reales. API parcial con aviso, no opt-in nativo Sheets.

Backup/rollout/piloto aún requieren los campos del baseline, destinos y digests; no son permisos generales listos para ejecutar. Build y lectura VM pueden aprobarse por separado: el SHA publicado ya está incorporado a los textos A/B de la propuesta. Tras publicar el follow-up documental se verificará SHA remoto = HEAD y equivalencia de los 36 objetos código/configuración/tests respecto de C3; su identidad final se reporta fuera del propio commit para evitar autorreferencia.

## Inventario SHA-256 original C1 — 36 filas históricas

| Archivo | SHA-256 |
| --- | --- |
| `core/src/zeler_platform_core/history_onboarding.py` | `ab4819dafde56522d36b728239165c5390c224af31964fc581c67e45e0b7af94` |
| `core/tests/test_runtime_phase4.py` | `7f9185ec469c4eed17dc11d96e704c7e4861dfade7c5e1b10255f3a51acbf5ac` |
| `gateway/src/zeler_gateway/oauth/events.py` | `3f6f73ac0b9bc26d6acd8d58986dc393a6bc85cd188b4af24ac7607c19f84cae` |
| `gateway/tests/test_lifespan_rabbit.py` | `12d6e8c0ee0f65f7f551977a555012f52a32dbce7024341d58361f7625b4cdc2` |
| `infra/deploy/sheets_rollback.py` | `bc409a65aa7c9942280dcc5fe73e23699f782b022945a2700acc2cbdb00163a6` |
| `infra/mongo/indexes/sheets_full_operations.json` | `7dee2ce87b57a8814db463a850bd8325346ad4428148b864b7a601786e13aad5` |
| `infra/mongo/indexes/sheets_history_backfill_plans.json` | `165c28cff3387c2be8e9af98404b16ed2967343f51506d073126c995098187db` |
| `infra/mongo/indexes/sheets_history_pending_records.json` | `5ac097c749b00334004286597218b71bc8eea6409bedb8582c16abd7da72dafa` |
| `infra/mongo/indexes/sheets_history_receipts.json` | `1b0fc5fcdc8051c4dd40734333dd910ee34f6f7037b07d956896156eb3e7e82b` |
| `infra/mongo/seeds/module_registry.admin_clients.json` | `09871036cdc7aede23ef6fb3620bb5a5acc2c86227995de36814c8b238ee2f25` |
| `modules/sheets/manifest.yaml` | `477de1782da47b22dc15556193ca601e9cbcb83f65e3de2bf95761daae775f36` |
| `modules/sheets/src/zeler_sheets/api.py` | `973fd9f36c9458f7624a72399cd362dcb5829c4a59a7830aa60b264082b48362` |
| `modules/sheets/src/zeler_sheets/consumer.py` | `60e60e1246b4444b2c2821ed4f8c8786471cc308ac58c15029448aafec4e879b` |
| `modules/sheets/src/zeler_sheets/devoluciones_runner.py` | `c5f2f43126c9c7e100d7b5237f9375b13169254147fb5552d63b18723a19afe0` |
| `modules/sheets/src/zeler_sheets/formulas/handlers_orders_questions.py` | `42a83e39bab7a01a61ee19ed93888da66a346a82d7d8433204d5a994c363aa23` |
| `modules/sheets/src/zeler_sheets/formulas/recovery.py` | `371babe134e5db26615ccae62b49bd5ef45cd429db6f5186048bc74d131f0d33` |
| `modules/sheets/src/zeler_sheets/formulas/recovery_worker.py` | `410d9172db9bbe0ab1369a9a2006cd0ce143eabca2fc97eb29dec909daa80e35` |
| `modules/sheets/src/zeler_sheets/history_onboarding.py` | `b7f51c02ea4574c41357435317b8b45df9694956e96fa29098f2e97611e6ace5` |
| `modules/sheets/src/zeler_sheets/onboarding_sources.py` | `565532dd7854c45befc50c62007ab9639b27ff429172702fcc5dcdf8ebdc04f1` |
| `modules/sheets/src/zeler_sheets/partial_history.py` | `4430e55f1be086801e96292ccf5c63f9ec0553427e593a0d75369b4e5c7e9224` |
| `modules/sheets/src/zeler_sheets/pilot_history_backfill.py` | `e60656d6be443a8858c8974115be228f25a19051d791b37f1ec992f458ae0421` |
| `modules/sheets/tests/test_app_phase6.py` | `9e68b0bb2d3eeda52d907471ea06de4d6781554efe9a3e80cd34a363bcd92102` |
| `modules/sheets/tests/test_devoluciones_onboarding.py` | `c58421f570b01d9a42bffa963ba595531021dc3b2cfd4394b1c7cfb1d483c83f` |
| `modules/sheets/tests/test_full_onboarding_handler.py` | `3acfd1a7d3bf3e5383c3b8cb2d3e7ce97e14d2018e438ef616743ae83185a11d` |
| `modules/sheets/tests/test_history_old_messages.py` | `abeeeefe3c9c10976ef736a369bde92522f40608038711a145d124fc1e82c87a` |
| `modules/sheets/tests/test_history_onboarding.py` | `02b8f4895fa9cb7b7dca1385227a0299c49e96373706b4367036bcfbfd8501d8` |
| `modules/sheets/tests/test_history_onboarding_capacity.py` | `43bffa6a3dfb97331c6ae818d15ce776dbf7f7d2df92587f1aab596ab37fd17a` |
| `modules/sheets/tests/test_history_onboarding_shared_capacity.py` | `2711a78b35842089ea05c0b860592b825882b926b2fd89481c6d389e9d9315bc` |
| `modules/sheets/tests/test_history_pilot_scope.py` | `e865fcc05603371ddd6ecded4c66ccc497dcd89869ec6b290fe90c21590d8209` |
| `modules/sheets/tests/test_onboarding_indexes.py` | `548458278f08af3929288e26bdb317c2332faa0831843a171468fe6e9ce07301` |
| `modules/sheets/tests/test_onboarding_sources.py` | `1ba6fba272f96853d390c478e10a7275a39e6f3e68dd1c48c49779cf2c71b72b` |
| `modules/sheets/tests/test_partial_history.py` | `a7a99663bf31f53bf330cdd20527491a77e4645f738d7921402066c6f78d9002` |
| `modules/sheets/tests/test_partial_history_api.py` | `509176ab0a5eb50e014f8ecf1c2b0731f95e08ec4e53932cb687c2c7ce432e2c` |
| `modules/sheets/tests/test_pilot_sheets_config_progress.py` | `77565bf3d6404a4235293dced0dbda521a1051c52312c49794a57e4d270a0c2a` |
| `tests/integration/test_devoluciones_onboarding.py` | `f87d7bb4e8a7e89d396cc52f4bf77f916a09aa2a6691eff912622f1ebbb1767b` |
| `tests/test_deployment_preflight.py` | `afe3a4365fdec60500e713fa1419a29270ce6ff6f9a1b1bc9862816ab6987db7` |
