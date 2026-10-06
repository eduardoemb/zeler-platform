# CUOTAS — preservar texto vacío conocido de Questions BANNED

**ENTREGADO; NO SIGO MODIFICANDO.** Fix localizado de dos condiciones del predicate, sin Core/schema/validator/otras áreas ni producción. La ventana08:17:23Z expiró; h1 OFF y planPAUSED81/79/24 permanecen según evidencia Root. No aprobación nueva recibida ni apply/replay/readmisión/proveedor por especialista.

## Cambio exacto

`_complete_scan_question` acepta **texto presente string vacío** únicamente cuando:
- question.status es exactamente BANNED; o
- question.status ANSWERED y answer.status exactamente BANNED para su answer.text.

Texto None/ausente sigue missing; cualquier blank noBANNED mantiene fallback/reject anterior. No default ACTIVE, texto/status sintéticos ni recuperación de contenido oculto. Tipos, enum/canonical schema, fecha/identity/range, dos manifiestos completos/concordantes y source_version questions.scan.v4.verified permanecen iguales. No editar exporter ni contratos compartidos.

## Evidencia y prueba

Root hizo lectura productiva metadata3queries: antiguos150members,148complete/2missing; ambos missing eran question BANNED/text PRESENTEMPTY/item+buyer presentes/answerNone. No rawdata ni providerGET. Eso no prueba totalidad210 ni dos pases completos.

Root verificó docs primarias Meli de15enero2026: BANNED redacta texto de question/answer a vacío. [Documentación oficial](https://developers.mercadolibre.com.ar/en_us/categories-and-attributes/manage-questions-and-answers). Consulta documental propia devolvió403; sin repetición, no confundir con diagnóstico/provider HTTP. Core Question.text/Answer.text son str y validator permite vacío según inspección Root; los fakes ejecutan realmente writer/schema/reader actuales.

TDD offline11casos:
- RED4FAIL/7PASS antes del fix: known-empty question/answer intentaban fallback y fallaban, tanto materialización como publisher/reader.
- GREEN **11PASS**,0.32s.
- Ruff/formato/Mypy2 PASS, estándar sin ignores/reducción.

Fixtures previos de materialización usados **solo lectura**, no editados. Socketconnect/connect_ex prohibidos, env whitelist sin Mongo/AMQP/secrets, noconftest/importlib/autopluginsOFF; sin DB/puertos/network tests, suite general, Git/build/agentes. Logs red/green/xml/quality O_EXCL0600 preservados en cache `question-banned-source-20261006`.

Pruebas: dos manifestsBANNED→0detailGET/provenance; actualpublisher/canonicalwriter/schema/reader preservan vacío+status sin contenido oculto; None/ausente noaceptado en ambos textos; blanks noBANNED permanecen incompletos; answerstatus ausente nunca ACTIVE.

## Integración pendiente Root

Worker image afectada: predicate runtime histórico Questions. Root hace controles conjuntos y después build explícito solo afectado; tests/build no prueban despliegue ni aceptación. Sin nueva operación productiva mientras ventana/autoridad estén vencidas. No declarar hiddenoriginal recovered, cincofuentes/año ni piloto completado.

## Hashes SHA-256

- history_questions.py: `97d46422189c9e5d113b9b44b4da9411565bcaaa4e63ff189c6e6e278e02e6da`
- test_history_question_banned_source.py: `8890110e0b66824a4374821db64ed33eb73282a8ae65a4f05b6e2de9c2fb6cf1`

InformeSHA por chat, evitando autorreferencia. **ENTREGADO; NO SIGO MODIFICANDO.**
