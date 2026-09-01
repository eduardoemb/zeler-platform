## Linked Issue

Reemplaza el marcador por una única referencia local en una línea independiente:

Closes #<issue-number>

Solo se aceptan `Closes`, `Fixes` o `Resolves` seguidos de `#N`; no uses referencias entre repositorios ni agregues otra línea de cierre.

## PR Type

Selecciona exactamente un tipo y agrega la etiqueta `type:*` equivalente a la PR.

- [ ] Bug fix — `type:bug`
- [ ] New feature — `type:feature`
- [ ] Documentation only — `type:docs`
- [ ] Code refactoring — `type:refactor`
- [ ] Maintenance/tooling — `type:chore`
- [ ] Breaking change — `type:breaking-change`

## Summary

-

## Changes

| File | Change |
| --- | --- |
| `path/to/file` | Describe el cambio. |

## Test Plan

- [ ] Comando de validación exacto y resultado exacto: `comando` → `PASS`/`FAIL`; si no aplica, escribe `N/A` y explica por qué.
- [ ] Verificación manual del comportamiento afectado y resultado; si no aplica, escribe `N/A` y explica por qué no existe un comportamiento manual relevante.
- [ ] Verifiqué la carga de skills en al menos un agente y anoté el agente y resultado; si no aplica, escribe `N/A` y explica por qué no se modifican ni usan skills.

## Contributor Checklist

- [ ] El issue enlazado tiene `status:approved`.
- [ ] Agregué exactamente una etiqueta `type:*` permitida.
- [ ] La etiqueta coincide con el tipo seleccionado.
- [ ] Ejecuté `shellcheck` para los scripts modificados, o aporté evidencia explícita de `N/A` porque no se modificaron scripts.
- [ ] Probé las skills en al menos un agente, o aporté evidencia explícita de `N/A` porque no se modifican ni usan skills.
- [ ] Actualicé documentación cuando cambió el comportamiento.
- [ ] Usé un mensaje de commit convencional.
- [ ] No incluí trailers `Co-Authored-By`.

## Chain Context

Para una PR normal, completa todos los campos específicos de cadena con `N/A`. Para una PR encadenada, completa cada campo y marca esta PR con `📍` en el diagrama. La base permanece `main`; la estrategia apilada se dirige a `main`, no a una rama predecesora.

- Base: `main`
- Chain strategy: N/A
- Start state: N/A
- End state: N/A
- Prior dependencies: N/A
- Follow-up work: N/A
- Out of scope: N/A
- Rollback boundary: N/A
- Dependency diagram: N/A

Ejemplo de diagrama para una PR encadenada:

```text
main ← PR #123 ← 📍 PR actual ← PR #125
```
