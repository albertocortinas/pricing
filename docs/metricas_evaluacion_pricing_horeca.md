# Métricas de evaluación — Modelo de pricing HORECA

**Versión 0.1 · junio de 2026** · (apéndice del documento de fundamento metodológico)

Principio: el modelo es causal y alimenta una optimización de margen, no es un *forecast*. Por tanto, **una métrica de ajuste nunca aprueba el modelo por sí sola**. El orden de autoridad es: la Capa 2 (validez causal) es el *gate* que decide si el modelo es válido; la Capa 3 (valor de decisión) es el norte; la Capa 1 (ajuste) es necesaria pero insuficiente.

Niveles de agregación usados abajo: **celda** = Establecimiento × Material × periodo; **segmento** = categoría/provincia × marca/línea (el nivel en que de verdad se decide); **total** = cartera.

Los umbrales marcados *(prov.)* son puntos de partida a recalibrar tras la primera corrida; no son absolutos y, salvo donde se indique *hard*, sirven para señalar revisión, no para rechazar de forma automática.

---

## Capa 1 — Ajuste (necesaria, no suficiente)

| Métrica | Qué mide | Cálculo | Nivel | Umbral *(prov.)* |
|---|---|---|---|---|
| **CRPS** *(principal)* | calidad de toda la predictiva, no solo el punto | media del CRPS sobre celdas, a partir de las muestras posteriores | celda + segmento | mejor que el baseline (naïve / estacional); comparativo, sin valor absoluto |
| **WAPE** | error de punto agregable y robusto a ceros | Σ\|y − ŷ\| / Σ\|y\| | celda + segmento | < 0.30–0.40 a nivel segmento |
| **RMSLE** | error multiplicativo, coherente con el modelo log-log | √(media((ln(1+ŷ) − ln(1+y))²)), solo filas con volumen > 0 | celda | comparativo vs baseline |
| **Sesgo agregado** | desviación sistemática (lo que más daña al agregar) | Σ(ŷ − y) / Σy | segmento + total | \|sesgo\| < 2–3%, centrado en 0 |
| **RMSE** | dispersión en unidades (solo donde la escala está controlada) | √(media((y − ŷ)²)) | segmento + total (**no** celda) | comparativo |
| **Cobertura de intervalos** | calibración de la incertidumbre | % de celdas con y dentro del intervalo central P% | celda + segmento | dentro de ±5 pp del nominal (p. ej. 80% → 75–85%) |

> **Fuera:** MAPE como métrica de cabecera — se indefine/explota con los ceros y negativos de los meses-cola, es asimétrico y no admite negativos.

---

## Capa 2 — Validez causal (*gate*; mayormente hard)

| Métrica | Qué mide | Cálculo | Nivel | Umbral |
|---|---|---|---|---|
| **Signo de elasticidad** | dirección correcta | P(β_precio < 0) en la posterior | SKU / segmento | **hard:** P(β<0) > 0.95 — si no, se rechaza |
| **Magnitud de elasticidad** | plausibilidad | banda informada por literatura | SKU / segmento | banda-prior (p. ej. −0.2 a −2.5; HORECA esperable hacia inelástico). Fuera de banda → revisión, no rechazo automático |
| **Recuperación en evento retenido** | validez causal real (predice el Δ, que es lo que se usa) | predicho vs. realizado del Δln(q) alrededor de un escalón del 1-dic retenido; o elasticidad del *holdout* vs. la de muestra completa | SKU / segmento | el Δ realizado cae dentro del IC del predicho; elasticidad *holdout* dentro de tolerancia |
| **Placebo / falsación** | ausencia de efecto espurio | "efecto" estimado en una fecha falsa o en celdas sin cambio de precio | segmento | indistinguible de 0 (el IC incluye 0) |
| **Estabilidad jerárquica** | sanidad del *shrinkage* | dispersión de elasticidades dentro de cada familia; nº de celdas que colapsan al prior | familia (marca/línea) | sin signos invertidos dentro de familia; *shrinkage* razonable y no degenerado |

---

## Capa 3 — Valor de decisión (norte)

| Métrica | Qué mide | Cálculo | Nivel | Umbral |
|---|---|---|---|---|
| **Uplift de margen (offline)** | el valor real del modelo | E[margen(π_modelo) − margen(π_actual)] sobre la respuesta estimada, con IC posterior | segmento + total | > 0 con alta probabilidad posterior (p. ej. P > 0.9) |
| **Regret de decisión** | coste de equivocarse | margen perdido frente a la política óptima conocida en *backtest*/simulación | segmento | minimizar; comparativo entre modelos |
| **Uplift validado en experimento** | prueba definitiva | margen real *test* vs. *control* | segmento | el IC del experimento excluye 0 y es consistente con lo predicho |

---

## Esquema de validación

- **Partición temporal**, no aleatoria: *rolling-origin* y/o *leave-one-quarter/season-out*. El *k-fold* aleatorio filtra información por la estructura de panel y temporal.
- **Evaluar al nivel en que se decide.** El reporting de cabecera va a nivel segmento/total; el nivel celda sirve para diagnóstico, no como juez (su ruido no representa el error de la decisión).
- **Siempre contra un baseline** (naïve, estacional, o "no cambiar nada"): casi todas las métricas de ajuste son comparativas, no absolutas.
- **Reportar sesgo y dispersión por separado** en cada capa: para un modelo que se agrega, un sesgo pequeño y estable vale más que una dispersión baja por celda.

## Anti-patrones a evitar

- MAPE como métrica de cabecera sobre datos esparsos con ceros/negativos.
- *k-fold* aleatorio sobre el panel.
- Optimizar el ajuste (Capa 1) sacrificando la pendiente causal (Capa 2) — el caso clásico de "buen MAPE, elasticidad equivocada" por endogeneidad.
- Umbrales absolutos sin baseline ni IC.
- Aprobar el despliegue con métricas de ajuste sin pasar el *gate* causal.

---

*Referencias de apoyo: Hyndman & Koehler (2006) sobre medidas de error de pronóstico; Gneiting & Raftery (2007) sobre reglas de puntuación propias y CRPS.*
