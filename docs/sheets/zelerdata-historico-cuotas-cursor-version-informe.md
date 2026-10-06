# CUOTAS — contrato de versión BSON inmutable de checkpoint Questions

**FASE1 ENTREGADA; NO SIGO MODIFICANDO.** RED real y propuesta para Root. No modelo/export/schema/index ni Modules editados. No producción/readmisión/retry/plazo/proveedor. Root integra únicamente la unidad de contrato junto con sus tests y este informe; no publicar tests aislados como feature terminada.

## Quick path

1. Root crea `core/src/zeler_platform_core/models/sheets_history_checkpoint.py` con API abajo.
2. Integra/exporta validator literal para **nueva** `sheets_history_checkpoint_versions`; los heads/receipts existentes permanecen intactos.
3. Da turno GREEN enfocado; luego valida esquema/export y conjunto bajo congelación. Este envelope no autoriza fase2 ni operaciones.

Skills leídos: work-unit-commits (tests/docs con comportamiento; Git solo Root) y cognitive-doc-design (respuesta primero/contrato verificable). Directo, sin SDD.

## API y campos exactos propuestos

Módulo nuevo exporta `SheetsHistoryCheckpointVersion` y helper module-level:
`deterministic_version_id(acquisition_id, generation, pass_number, checkpoint_revision) -> str`.

Helper: validar str no vacío/no blank e ints no bool, generation/pass>=1, revision>=0, representables BSON signed64. Sin UUID ni normalización del ID. SHA256 hexadecimal lowercase de `BSON.encode` de este seed, en **este orden fijo**, números normalizados a Python int:

```python
{
    "acquisition_id": acquisition_id,
    "generation": generation,
    "pass_number": pass_number,
    "checkpoint_revision": checkpoint_revision,
}
```

| Campo | Contrato |
|---|---|
| id, alias `_id` | requerido, SHA64; coincide exactamente con helper |
| acquisition_id/job_id | str strict no vacío; metadata y ambos blobs identifican la misma adquisición/job |
| seller_id | str strict numérico; igual en ambos blobs |
| execution_id | str strict lowercase32hex; no inventarlo desde blobs que legítimamente no contienen este campo |
| generation/pass_number | ints strict positivos; iguales a head y binding job |
| checkpoint_revision | int strict>=0; igual a head/job binding |
| reason | requerido literal `expired_question_cursor` |
| archived_at | datetime strict aware, normalizado UTC; no parsear strings ni usar reloj actual en modelo |
| head_bson/job_bson | bytes strict,5..65536 bytes cada uno; conservar exactamente bytes originales |
| head_sha256/job_sha256 | lowercase64hex strict, SHA256 exacta de su blob |

`ConfigDict(strict=True, extra="forbid", populate_by_name=True, hide_input_in_errors=True)`. `Field(repr=False)` en ambos blobs. Mensajes de validación cerrados, nunca interpolar BSON/bytes/datos. No Logger/str(exception libre)/model_dump/errors(include_input=True) en operadores. `model_dump` es solo persistencia interna, no output; contains datos sensibles legítimos.

## Validación de blobs — sin reconstrucción

Decode BSON completo usando CodecOptions UTC aware. Truncación/trailing bytes/shape inválida: ValueError cerrado; no str del driver. **No** reconstruir bytes desde objetos/modelos ni validar el blob completo con un modelo extra-forbid que descartaría/rechazaría campos adicionales legítimos.

1. Head `_id`==acquisition_id==job_id==head.job_id==job._id==job.history_acquisition_id. Seller metadata igual a head/job. Ambos read_model questions; head.scope_id seller_scan.
2. Head.phase discover o verify; next_cursor str no vacío; published_count entero0, no bool. No publicación/claim de cobertura.
3. Head generation/pass/revision y job history_generation/history_pass_number/history_checkpoint_revision iguales a metadata. Job history_protocol_version entero1; strings/bools no son ints legítimos.
4. Head plan_id==job.history_plan_id, date_from/date_to datetime BSON iguales en ambos, start<end. Los bytes originales y su precisión BSON milliseconds se conservan; no reescribir fechas ISO/redondeos.
5. Job state failed, failure_reason source_rejected o source_cursor_expired; attempts entero>=1. Campo lease_until ausente/None o datetime BSON: **vigencia respecto a now es gate del operador**, no del modelo. Un futurelease estructuralmente válido no constituye autorización.
6. Si execution_id está presente en algún blob, debe coincidir; su ausencia legítima no inventa binding. Operador debe ligar el envelope al plan/pin/EID realmente autorizado.
7. Campos adicionales dentro del RAW BSON se preservan sin reinterpretarlos. Extra externo del envelope se rechaza. No execution_consumed/sent/balance/refund/authority/deadline nuevos.

Esta fase valida metadatos e integridad, **no** hace append-only/CAS/owner/TTL/recovery. El operador/tx futuro deberá verificar SHA originales, lease/time/execution authority, byteigual duplicado o conflicto y rollback; no aplicar esos checks con reloj fijo dentro del modelo.

## Export literal propuesto (Root-only)

Registrar esta entrada de validator para `sheets_history_checkpoint_versions` en el export canónico; export JSON de la nueva colección solamente. Nada se aplica en esta fase.

```json
{
  "$jsonSchema": {
    "bsonType": "object",
    "additionalProperties": false,
    "required": ["_id", "acquisition_id", "job_id", "seller_id", "execution_id", "generation", "pass_number", "checkpoint_revision", "reason", "archived_at", "head_bson", "job_bson", "head_sha256", "job_sha256"],
    "properties": {
      "_id": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
      "acquisition_id": {"bsonType": "string", "minLength": 1, "pattern": "\\S"},
      "job_id": {"bsonType": "string", "minLength": 1, "pattern": "\\S"},
      "seller_id": {"bsonType": "string", "pattern": "^[0-9]+$"},
      "execution_id": {"bsonType": "string", "pattern": "^[0-9a-f]{32}$"},
      "generation": {"bsonType": ["int", "long"], "minimum": 1},
      "pass_number": {"bsonType": ["int", "long"], "minimum": 1},
      "checkpoint_revision": {"bsonType": ["int", "long"], "minimum": 0},
      "reason": {"bsonType": "string", "enum": ["expired_question_cursor"]},
      "archived_at": {"bsonType": "date"},
      "head_bson": {"bsonType": "binData"},
      "job_bson": {"bsonType": "binData"},
      "head_sha256": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
      "job_sha256": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"}
    }
  }
}
```

Bytecaps y checks crossblob/hash/ID no los demuestra ese JSON Schema: los exige el modelo y la aplicación antes de insertar. No usar maxLength para binData como falsa garantía. Mongo append-only se implementa mediante insert-only/version-id y comparación de bytes, no por esta forma del validator. Índice `_id` ya proporciona unicidad determinista; índices adicionales/validator application son decisión Root separada.

## RED y controles

Nuevo `core/tests/test_sheets_history_checkpoint_version.py`: **16 casos offline**, sin sockets/DB/puertos. Import real canónico dentro de cada caso, sin shadow ni dummy model.

- `checkpoint-version-20261006/red.log/xml`:16 FAIL.
- Final `red-security.log/xml`: **16 FAIL**, causa real `ModuleNotFoundError` porque módulo nuevo no existe todavía. No se presenta como16 fallos semánticos ya ejecutados; esos checks correrán al implementar Root.
- `ruff-security.log`, `format-check-security.log`, `mypy-security.log`: PASS (un target, configuración estándar, sin ignores ni reducción).
- Primer test exige byteigual extras+millisegundos y repr sin marcadorPII; caso SHA exige ValidationError str sin marcador/cursor. Se combinaron sin superar16 casos.

Cobertura: stable deterministicBSONID/badtypes; required/extra; SHA/ID/metadata/bindings; execution32hex; timezone; exact64KiB y +1; truncation/trailing; cursor/phase/questions/unpublished; terminal reasons/attempts; dates/plan; lease type sin clock policy; rawtypes; schema outer strict/no counters.

Logs nuevos O_EXCL0600 preservados en cache `/Users/eduardoramirez/.codex/cache/zelerdata-integracion-20261005-8dafff186997/checkpoint-version-20261006`. Env whitelisted/PYTEST plugins deshabilitados/PYTHONDONTWRITEBYTECODE, `--noconftest -o addopts='' --import-mode=importlib`; ningún uso de conftest/MONGO_URI.

## Fuera de alcance y siguiente entrega

No archivo inmutable insertado aún ni nueva pasada/readmisión. Originales Root pins59dd807a(head)/60d1c078(job) preservados; originaldeadline expirado y PAUSED81/79/24 no se cambia. Phase2 debe resolver TTL/canonicalreadmission y materialización de scan verificado dentro de caps, no asumir210detailGETs ni inferir count por page_sequence. Este informe no implementa ni autoriza esa fase.

Rollback local de unidad: quitar únicamente nuevo modelo/export/validator+este test/informe antes de su utilización; no borrar archivos/datos productivos si la colección ya fue utilizada. Git/build/rollout solo Root.

Test SHA-256: `c81bfbf063efa73f71b3cd24562f648309ce4dd0c4cdc2fc410248f6c796144f`. Informe SHA entregado por chat para evitar autorreferencia.

**ENTREGADO; NO SIGO MODIFICANDO.** Esperar integración Root y turno GREEN; sin pruebas adicionales tras cese.
