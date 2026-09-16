# Apps Script automatic refresh: decision and disposable probe

Task **5.3 remains open**. Local safety tests cannot establish Google Sheets
recalculation or automatic open/reopen behavior. This document authorizes no
Google mutation, scope change, publication, build, or deployment. The proposal
below requires separate operator approval and execution.

## Quick path

1. Approve a dedicated disposable spreadsheet and test add-on context; never
   run the destructive comparison on existing user formulas.
2. Test identical-formula writes against a no-write control with unchanged
   arguments and an independently changed backing result.
3. Only in disposable cells, compare clear/flush/restore and record failures,
   lost formulas, and cache behavior rather than assuming invalidation.
4. Decide on the scheduling design and any additional permission only after
   the recalculation candidate has evidence.
5. Prove automatic open-sheet and reopen behavior separately in the actual
   Editor add-on context. Keep 5.3 pending until both pass.

## Evidence boundary

The selected [specification](specs/zelerdata-pilot-reliable-sync/spec.md) requires
formula cells to update without manual editing, including reopening after data
changed while closed. A manual menu action, a sidebar the user must reopen on
every visit, an HTTP 200, or an Apps Script write count does not satisfy that
requirement. Formula signatures and existing formula text must remain unchanged.

The current manifest declares only `script.container.ui`,
`script.external_request`, and `spreadsheets.currentonly`. The
[publication runbook](../../../docs/sheets/zelerdata-marketplace-publication.md)
reserves Google project, OAuth, version, Marketplace, and post-approval smoke
operations for an authorized operator. This probe is a proposal, not execution
evidence or authority to publish.

## Verified constraints and candidate options

Official Google documentation was consulted on 2026-09-15. Distinguish supported
API capabilities from an unverified end-to-end composition:

| Path | Documented capability | Limitation / decision |
| --- | --- | --- |
| Simple `onOpen` | `LIMITED` permits current-document access; `NONE` does not. | A guarded local current-sheet formula write is compatible with the documented access model, but recalculation is not thereby proven. No sidebar or URL Fetch in `LIMITED`; handle `NONE` without properties/document access. |
| Installable open trigger | Runs in `FULL`, as the trigger creator; open triggers are supported for Editor add-ons. | Candidate for opt-in reopen activation. Programmatic creation requires additional `script.scriptapp` scope and consent. UI availability and identity behavior in the published add-on must be tested, not inferred from `FULL` alone. |
| Sidebar polling | An authorized sidebar can call server functions asynchronously. | Candidate for bounded requests while its browser context remains alive. Browser suspension, sidebar closure, navigation, and reopening require explicit handling; a sidebar is not a persistent worker. |
| Installable clock trigger | Supported for Editor add-ons. | At most hourly, not a one-minute add-on clock. Do not substitute a standalone bound-script timer and claim add-on parity. |
| `setFormula` with identical text | Writes a formula. | No documented guarantee that this invalidates custom-function result caching. Measure actual evaluations and displayed values. |
| Clear/flush/restore | Individual range operations exist. | Destructive candidate only for disposable cells. Not transactional: interruption or collaborator edits can cause loss. Success in a probe does not approve production use. |
| Hidden epoch or volatile argument | Direct changed cell arguments trigger recalculation. | Reading an epoch indirectly does not establish a dependency. Adding arguments violates the unchanged-signature contract; `NOW`/`RAND` arguments are unsuitable. |

Sources: [Editor authorization](https://developers.google.com/workspace/add-ons/concepts/editor-auth-lifecycle),
[Editor triggers](https://developers.google.com/workspace/add-ons/concepts/editor-triggers),
[installable trigger identity](https://developers.google.com/apps-script/guides/triggers/installable),
[ScriptApp permissions](https://developers.google.com/apps-script/reference/script/script-app#newTrigger(String)),
[sidebar API](https://developers.google.com/apps-script/reference/base/ui#showSidebar(HtmlOutput)),
[asynchronous sidebar calls](https://developers.google.com/apps-script/guides/html/reference/run),
[custom-function recalculation](https://developers.google.com/apps-script/guides/sheets/functions#arguments),
[range writes](https://developers.google.com/apps-script/reference/spreadsheet/range#setFormula(String)).

`SpreadsheetApp.openById` requires broad `spreadsheets` permission, not merely
`currentonly`. Do not add it as an implicit timer workaround. Existing-document
and event-source access must be tested under the actual manifest instead.
[SpreadsheetApp authorization](https://developers.google.com/apps-script/reference/spreadsheet/spreadsheet-app#openById(String)).

Custom-function `getUserProperties()` reads the spreadsheet owner's properties.
Menu execution and installable triggers can have different effective identities.
Use a legitimately issued owner token through the normal settings flow; never
copy another user's token or expose it in cells, logs, browser responses, or
evidence. Test collaborators separately; owner success is not proof of
per-operator token behavior.
[Custom-function service access](https://developers.google.com/apps-script/guides/sheets/functions#using_apps_script_services).

## Explicit operator approval scope

Before execution, record approval for:

- One disposable spreadsheet owned by the authorized pilot operator, with two
  disposable tabs; record its identifier privately, not in public evidence.
- One identified test add-on version matching reviewed repository source. Keep
  production listing, existing user spreadsheets, and existing formulas untouched.
- Synthetic nonsecret probe data and, in a separate phase, read-only Formula API
  calls using a legitimate pilot token for seller `82453304`.
- A bounded test window, maximum evaluations, and request cadence. Proposed
  initial bound: 10 minutes, at most 30 requested evaluations, one outstanding
  browser/server request, no repeated retries after authorization/rate-limit
  errors. These are probe limits, not asserted provider quotas.
- Separate permission for trigger experiments if selected: exact additional
  scope, one opt-in open trigger, creator identity, disable action, and cleanup.
  The initial same-text experiment does not require trigger creation.
- Deleting only the probe's own trigger and disposable resources at the end, if
  cleanup is included in approval. Never delete unrelated user triggers.

No backend production mutation is needed for the synthetic phase. For real
formula acceptance, use independently verified naturally changed pilot data or
a separately authorized legitimate source action; do not patch Mongo or tokens.

## Experiment A: isolate recalculation from scheduling

Use a test-only custom function returning a nonsecret generation plus invocation
identifier from controlled test state. Inputs remain fixed. Changing generation
must not change any argument cell or formula. Keep this probe function out of
the published formula catalog. Its synthetic behavior is diagnostic, not proof
that all 52 product formulas work.

Create three isolated anchor cells with room for array output and sentinel
values outside their spill areas. Preserve their original formulas and displayed
results in sanitized evidence. Repeat on the second tab, including a lowercase
formula and one protected/no-edit cell where supported.

| Arm | Operator action after backing generation changes | Observation |
| --- | --- | --- |
| Control | No cell write | Establish whether Sheets reevaluates spontaneously. |
| Same text | Read formula, write exactly that formula once | Record a new actual evaluation and displayed generation, or failure to refresh. |
| Destructive comparison | Save formula; clear anchor; flush; restore exact formula; flush | Record result and restoration outcome. Only disposable anchor cells may be cleared. |

Observe immediately and at bounded later checks; record elapsed time rather than
inventing a guaranteed recalculation deadline. Repeat with another generation to
avoid mistaking a first-run calculation for repeatable invalidation. Record
unchanged arguments, formulas before/after, actual evaluation evidence, visible
result, spill safety, and untouched sentinels. A write completing or `flush`
returning is not calculation-completion evidence.

In the disposable destructive arm only, deliberately stop between clear and
restore to demonstrate the interruption boundary, then restore from the saved
formula manually. If this can lose content, document the failure; do not promote
that path to user spreadsheets merely because the normal run passed.

Do not infer a particular cache TTL from a single observation. The add-on has no
application `CacheService` invalidation path, and application-cache eviction
would not itself prove that Sheets invokes an unchanged custom function.

## Experiment B: automatic open and reopen

Proceed only after selecting a candidate and obtaining any missing scope/trigger
approval. The possible design is an opt-in installable open handler that starts
an authorized sidebar, followed by one-at-a-time bounded refresh requests. This
is a hypothesis to test, not a claim of supported automatic sidebar delivery.

1. Test menu-only behavior in `NONE`, enabled-document `LIMITED`, and the
   installed handler's `FULL` context; no authorization failure may remove menus.
2. With the sheet open, change backing generation and prove visible update
   without menu clicks or manual formula edits; include cells on both tabs.
3. Close the spreadsheet/browser context, change generation, and reopen. Prove
   activation and visible update without manually restarting the sidebar.
4. Repeat with an authorized collaborator. Record trigger creator versus opener
   and ensure neither unauthorized token use nor competing loops occur.
5. Close the sidebar, suspend/resume the browser, reject permissions, and revoke
   the test token. Fail safely, stop requests, and show honest stopped/error
   status; do not claim continuous operation while the browser is suspended.
6. Exercise explicit disable and reopen: no automatic writes/requests occur.

If the installed open handler cannot safely activate the sidebar in the actual
Editor add-on, retain 5.3 as failed/pending and return for a design decision. Do
not silently substitute manual restart, broader scopes, or formula rewrites.

## Evidence and completion gate

| Evidence | Required record |
| --- | --- |
| Authority | Approved disposable target, operation scope, identity roles, limits |
| Version | Repository commit, immutable add-on version, relevant backend images |
| Recalculation | Each arm's generation, actual evaluation, visible result, elapsed time |
| Safety | Exact preserved formulas, unchanged sentinels, protection and interruption outcomes |
| Automatic behavior | Open and closed/reopened scenarios without manual intervention |
| Identity / permissions | Owner/collaborator result, actual scopes, denial and revocation behavior |
| Shutdown | Loop stopped, own triggers removed if approved, unrelated resources preserved |

All runtime observations are **PENDING**. This document closes only the research
and probe-design work unit, not task 5.3 or the 52-formula acceptance matrix.
Independent verification must rerun affected checks after implementation.

## Local work-unit evidence

- Executable behavior changed: none; strict-TDD cycle is not applicable to this
  documentation-only unit.
- Validation: relative file references, official-source claims, authority
  boundaries, unchanged-scope contract, and pending task status must be checked.
- Runtime harness: not executed; requires the explicit operator approval above.
- Rollback: remove this document and its task/progress references only; no
  runtime or Google artifact is changed by this work unit.
