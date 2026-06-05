# Implementación técnica — Modelo de pricing HORECA

**Versión 0.1 · junio de 2026**

Este documento describe la implementación del modelo de pricing, justifica cada decisión técnica con su fundamento teórico y enlaza las fuentes académicas pertinentes. Se complementa con el [fundamento metodológico](fundamento_metodologico_pricing_horeca.md) (diseño conceptual) y las [métricas de evaluación](metricas_evaluacion_pricing_horeca.md) (validación).

---

## 1. Cascada de pocket price

### Implementación

`src/pricing/features/engineering.py → build_pocket_price_waterfall`

La función une las tablas de ventas y margen, pivota los códigos de la cascada a columnas nominales y calcula tres agregados:

```
venta_neta   = tarifa − Σ(deducciones on-invoice)
pocket_price = venta_neta − Σ(deducciones off-invoice)
pocket_margin = pocket_price − Σ(costes) − spread_distribuidor
```

Cada término se construye a partir de los códigos definidos en `config.py`:

| Bloque | Códigos | Concepto |
|---|---|---|
| Tarifa | 050 | Precio de lista |
| On-invoice | 100, 210, 300, 420, 740 | Obsequios, descuento, promo, amortización CDT, rappel |
| Off-invoice | 920 | Colaboración |
| Costes | 858, 859, 861, 890, 954, 956 | Impuestos especiales, ecotasa, logística, producto, mano de obra, amortización IB |
| Distribuidor | 900, 901, 902 | Tarifa, impuestos, PA distribuidor |

### Justificación

La cascada de pocket price es el marco estándar de gestión de precios introducido por Marn & Rosiello (1992) y extendido en Marn, Roegner & Zawada (2003, 2004). Su valor reside en hacer visible la erosión entre el precio de lista y el margen real, desagregando las fugas por concepto y permitiendo cuantificar la contribución de cada condición al margen.

> **Fuente:** Marn, M. V. & Rosiello, R. L. (1992). Managing price, gaining profit. *Harvard Business Review*, 70(5). Marn, M. V., Roegner, E. V. & Zawada, C. C. (2004). *The Price Advantage*. Wiley.

---

## 2. Variable de precio: ratio sobre referencia

### Implementación

`src/pricing/features/engineering.py → build_price_ratios`

```
price_ratio = tarifa_actual / referencia
```

Se ofrecen dos métodos para la referencia:

- **`rolling_median`** — media móvil de los últimos *n* periodos (por defecto 6). Aproxima el "precio regular" percibido por el establecimiento.
- **`pre_tariff`** — media de la tarifa anterior al escalón del 1 de diciembre. Anclado al evento de subida.

### Justificación

El modelo SCAN\*PRO (Wittink et al., 1988; Foekens, Leeflang & Wittink, 1994; Andrews et al., 2008) define el precio como **ratio del precio actual sobre el precio regular**. La motivación es doble:

1. **Comparabilidad entre SKU.** El ratio normaliza las escalas, haciendo los coeficientes comparables entre materiales con niveles de precio distintos.
2. **Separación de precio base y promocional.** Al entrar como ratio, los descuentos temporales generan desviaciones del regular que el modelo captura como multiplicadores, sin confundirlas con el nivel de tarifa.

El concepto de precio de referencia está además fundamentado en la teoría del prospecto (Kahneman & Tversky, 1979): el consumidor evalúa el precio actual relativo a una referencia interna. La elección de la media móvil como proxy del precio regular sigue la formulación de Kalyanaram & Little (1994).

> **Fuentes:** Wittink, D. R. et al. (1988). SCAN\*PRO working paper. Foekens, Leeflang & Wittink (1994). *IJF*. Andrews et al. (2008). *IJRM*. Kalyanaram, G. & Little, J. D. C. (1994). *JCR*, 21(3), 408–418.

---

## 3. Forma funcional: log-log multiplicativo

### Implementación

`src/pricing/features/engineering.py → build_model_features`

Se aplica la transformación logarítmica a volumen y precio:

```
ln_volume     = log(volumen)       si volumen > 0
ln_price_ratio = log(price_ratio)  si price_ratio > 0
```

El modelo de respuesta opera en espacio log-log, de modo que los coeficientes son directamente elasticidades:

```
ln(q) = α + β · ln(price_ratio) + ...
⇒ β = ∂ln(q)/∂ln(p) = elasticidad-precio
```

### Justificación

La elección del log-log multiplicativo (elasticidad constante) se apoya en dos meta-análisis:

- **Tellis (1988)**: sobre 367 elasticidades, la forma funcional apenas mueve la elasticidad estimada; los sesgos provienen de la agregación temporal, la omisión de distribución/calidad y el uso exclusivo de datos transversales.
- **Bijmolt, Van Heerde & Pieters (2005)**: sobre 1.851 elasticidades, confirman que la forma funcional tiene un efecto menor relativo a otros moderadores.
- **Bolton (1989)**: documenta diferencias estadísticamente significativas pero cuantitativamente pequeñas entre formas lineal, multiplicativa y exponencial.

La lectura práctica es que el log-log es la base defendible por interpretabilidad y estándar en la literatura, y el esfuerzo debe dirigirse al control de sesgos, no a la sofisticación de la forma funcional.

> **Fuentes:** Tellis, G. J. (1988). *JMR*, 25(4), 331–341. Bijmolt, Van Heerde & Pieters (2005). *JMR*, 42(2), 141–156. Bolton, R. N. (1989). *Journal of Retailing*, 65(2), 193–219.

---

## 4. Asimetría de respuesta a precio

### Implementación

`src/pricing/models/response.py → build_pymc_model`

El modelo incorpora un término de asimetría mediante una interacción con un indicador de subida:

```
ln(q) = α + β_base · ln(price_ratio)
          + β_up · ln(price_ratio) · I(price_ratio > 1)
          + ...
```

Donde:
- `β_base` captura la elasticidad para bajadas de precio (price_ratio ≤ 1).
- `β_base + β_up` es la elasticidad total para subidas.
- `β_up ~ HalfNormal(σ=0.3)`: restringido a valores positivos, lo que garantiza que la subida sea al menos tan elástica como la bajada (en valor absoluto, más negativa).

La variable `price_increase_flag` se construye en `build_model_features` como `I(price_ratio > 1)`.

### Justificación

La asimetría de la respuesta a precio es una de las regularidades empíricas más robustas en marketing:

- **Kahneman & Tversky (1979)**: la teoría del prospecto establece que las pérdidas pesan más que las ganancias. Aplicado al consumo: una subida de precio (pérdida) reduce la demanda más que lo que una bajada equivalente (ganancia) la incrementa.
- **Hardie, Johnson & Fader (1993)**: formalizan la aversión a la pérdida en modelos de elección de marca, documentando un ratio de aversión de ~2×.
- **Krishnamurthi, Mazumdar & Raj (1992)**: demuestran asimetría empírica en datos de escáner, tanto en elección de marca como en cantidad comprada.
- **Kalyanaram & Little (1994)**: estiman una "latitud de aceptación" alrededor del precio de referencia, fuera de la cual la respuesta es más fuerte.
- **Heidhues & Kőszegi (2008)**: derivan precios óptimos bajo consumidores con aversión a la pérdida, mostrando que la rigidez de precios emerge endógenamente.

Para el caso de Damm, donde la palanca principal es la **subida** anual de tarifa, ignorar la asimetría subestimaría la caída de volumen, conduciendo a recomendaciones de precio excesivamente agresivas.

> **Fuentes:** Kahneman & Tversky (1979). *Econometrica*, 47(2), 263–291. Hardie, Johnson & Fader (1993). *Marketing Science*, 12(4), 378–394. Krishnamurthi, Mazumdar & Raj (1992). *JCR*, 19(3), 387–400. Heidhues & Kőszegi (2008). *AER*.

---

## 5. Modelo jerárquico bayesiano con shrinkage

### Implementación

`src/pricing/models/response.py → build_pymc_model`

La estructura jerárquica se implementa mediante PyMC con:

- **Interceptos por grupo** con distribución previa jerárquica: `α_i ~ N(α_family, σ_family)`. La "familia" se define por la combinación de categoría de establecimiento y línea de producto (configurable en `config.SHRINKAGE_HIERARCHY`).
- **Efectos mensuales jerárquicos:** `γ_month ~ N(0, σ_month)` con `σ_month ~ HalfNormal(0.3)`.
- **Priors informativos para la elasticidad:** `β_base ~ N(−1.35, 0.5)`, centrado en el punto medio de la banda de la literatura (−2.5, −0.2) definida en `config.ELASTICITY_PRIOR_RANGE`.

El muestreo utiliza NUTS (No-U-Turn Sampler) con `target_accept=0.9` para manejar las correlaciones posteriores del modelo jerárquico.

### Justificación

**Shrinkage jerárquico.** La heterogeneidad entre establecimientos es sistemática, no ruido (Hoch, Kim, Montgomery & Rossi, 1995). Sin embargo, muchas celdas Establecimiento × Material tienen pocas observaciones. La estimación independiente por celda produce estimaciones ruidosas; la estimación pooled ignora la heterogeneidad. El compromiso óptimo es el *shrinkage* bayesiano jerárquico, que contrae las celdas con pocos datos hacia la media de su grupo, ponderando automáticamente por la cantidad de información local frente a la grupal.

La extensión jerárquica bayesiana de SCAN\*PRO está establecida en Andrews, Currim, Leeflang & Lim (2008), que comparan estimación HB (hierarchical Bayes), FM (finite mixture) y OLS, concluyendo que HB domina en predicción fuera de muestra.

**Priors informativos.** Los priors sobre la elasticidad se informan por la distribución empírica de 1.851 estimaciones en Bijmolt et al. (2005), con la salvedad de que el canal HORECA con contratos CDT y lealtad de marca tenderá hacia el extremo inelástico de la banda. El prior es deliberadamente difuso (sd=0.5 sobre un rango de 2.3 unidades) para que los datos dominen cuando hay suficiente información.

**Distribución vía Spark.** La estimación se distribuye mediante `applyInPandas`, agrupando por segmento (e.g. Marca × Categoría). Cada grupo se estima independientemente con PyMC dentro de una UDF de pandas, lo que permite paralelismo a nivel de cluster Spark sin sacrificar la flexibilidad del modelo bayesiano.

> **Fuentes:** Hoch, Kim, Montgomery & Rossi (1995). *JMR*, 32(1), 17–29. Andrews, Currim, Leeflang & Lim (2008). *IJRM*. Bijmolt, Van Heerde & Pieters (2005). *JMR*, 42(2), 141–156.

---

## 6. Condiciones como semi-elasticidades

### Implementación

En `build_pymc_model`, cada condición (descuento, promoción, rappel, etc.) entra como un término aditivo en el modelo log:

```
ln(q) = ... + Σ_k δ_k · condition_k + ...
```

Donde `δ_k ~ N(0, 1)` — semi-elasticidades con prior difuso.

### Justificación

En el marco SCAN\*PRO, los instrumentos promocionales entran como **multiplicadores** en el modelo multiplicativo, que en espacio log son aditivos. La ventaja sobre un pocket price único es doble:

1. **Descomposición.** Permite medir el efecto incremental de cada condición por separado, necesario para optimizar el mix de condiciones.
2. **No linealidad.** La curva de efecto promocional es no lineal (Van Heerde, Leeflang & Wittink, 2001) y genera dips pre y post promoción por *pull-forward* (Van Heerde, Leeflang & Wittink, 2000). Modelar cada condición por separado permite capturar estas dinámicas.

El objetivo de optimización no es maximizar el lift aparente de la promoción, sino el **margen incremental sobre el baseline**, neto de pull-forward y canibalización. El lift aparente sobrestima sistemáticamente el efecto (Van Heerde et al., 2000).

> **Fuentes:** Van Heerde, Leeflang & Wittink (2001). *JMR*, 38(2), 197–215. Van Heerde, Leeflang & Wittink (2000). *JMR*, 37(3), 383–395.

---

## 7. Diagnósticos de la cascada (Fase 1)

### Implementación

`src/pricing/diagnostics/waterfall.py`

| Función | Propósito |
|---|---|
| `summarize_price_band` | Distribución del pocket price por segmento (percentiles p10–p90) |
| `summarize_leakage` | Cuantificación de fugas por concepto desde tarifa hasta pocket price |
| `flag_sparse_cells` | Identificación de celdas con < *n* periodos (por defecto 12) |
| `flag_negative_volume` | Detección de meses con volumen ≤ 0 (artefacto de devoluciones) |

### Justificación

El diagnóstico del price band es el primer paso en la metodología de Marn et al.: antes de modelar, hay que entender la dispersión del precio real y dónde se pierde margen. Las celdas esparsas y los meses con volumen negativo son problemas específicos del panel HORECA documentados en el fundamento metodológico (§10, riesgos 4-5). Su detección temprana es necesaria para decidir el nivel de agregación y los filtros previos a la estimación.

> **Fuente:** Marn, Roegner & Zawada (2003). *McKinsey Quarterly*; ver también *The Price Advantage* (2004).

---

## 8. Extracción de elasticidades y superficie

### Implementación

`src/pricing/models/elasticity.py`

- `extract_elasticities`: extrae de los resultados posteriores la media e intervalo HDI al 94% de `β_base`, `β_up`, y computa `β_total_up = β_base + β_up`. Aplica el gate causal: segmentos donde el HDI superior de `β_base` es ≥ 0 (es decir, P(β<0) < 0.95 aproximadamente) son marcados como no pasando el gate.
- `build_elasticity_surface`: une las elasticidades al grid completo Establecimiento × Material. Las celdas sin estimación directa heredan la media de los segmentos que pasan el gate causal (shrinkage).

### Justificación

La superficie de elasticidades es el activo central del motor de respuesta (§3 del fundamento: arquitectura en dos capas). La separación explícita de `β_base` (bajadas) y `β_total_up` (subidas) materializa la asimetría del §4. El gate causal al 95% de probabilidad posterior sigue la recomendación de las métricas de evaluación (Capa 2, §signo de elasticidad) y es un estándar en la inferencia bayesiana para verificar que el efecto tiene la dirección esperada por la teoría económica.

El fallback de shrinkage hacia la media global de los segmentos válidos implementa un empirical Bayes simple: en ausencia de información local, la mejor predicción es la media del grupo.

---

## 9. Métricas de evaluación (tres capas)

### Implementación

`src/pricing/evaluation/metrics.py`

**Capa 1 — Ajuste:**

| Función | Métrica | Fórmula |
|---|---|---|
| `compute_crps` | CRPS | E\|X−y\| − ½E\|X−X'\| (forma de energía) |
| `compute_wape` | WAPE | Σ\|y−ŷ\| / Σ\|y\| |
| `compute_rmsle` | RMSLE | √(mean((log(1+ŷ)−log(1+y))²)) |
| `compute_bias` | Sesgo | Σ(ŷ−y) / Σy |
| `compute_interval_coverage` | Cobertura | % de y ∈ [lower, upper] |

**Capa 2 — Gate causal:**

| Función | Test |
|---|---|
| `check_elasticity_sign` | P(β<0) ≥ 0.95 (hard) |
| `check_elasticity_magnitude` | Media posterior en banda (−2.5, −0.2) |
| `run_placebo_test` | IC del "efecto" en fecha falsa incluye 0 |

**Capa 3 — Valor de decisión:**

| Función | Métrica |
|---|---|
| `compute_margin_uplift` | E[margen(π_modelo)] − E[margen(π_actual)] |

**Validación temporal:** `temporal_split` con modos rolling-origin y leave-one-quarter-out.

### Justificación

**CRPS como métrica principal.** El CRPS evalúa la calidad de la distribución predictiva completa, no solo el punto central. Es una regla de puntuación estrictamente propia (Gneiting & Raftery, 2007), lo que significa que se minimiza cuando la distribución predictiva coincide con la verdadera distribución generadora. Para un modelo bayesiano que produce una posterior completa, es la métrica natural.

**WAPE sobre MAPE.** Hyndman & Koehler (2006) demuestran que el MAPE es inadecuado con datos que contienen ceros o valores cercanos a cero. El WAPE (equivalente al MAE normalizado) es agregable, robusto a ceros y conserva la interpretabilidad porcentual.

**RMSLE.** Coherente con el modelo log-log: penaliza errores multiplicativos de forma simétrica en escala logarítmica. Solo se computa donde el volumen es positivo, evitando el artefacto de los meses-cola.

**Gate causal.** El principio de que el ajuste no aprueba el modelo por sí solo está documentado extensamente en la literatura de endogeneidad de precios. El ejemplo canónico: un modelo con buen MAPE pero elasticidad positiva (por endogeneidad) recomendaría subir precios indefinidamente. El gate P(β<0)>0.95 es un umbral bayesiano análogo al rechazo de la hipótesis nula en un test clásico de un lado al 5%.

**Placebo/falsación.** Estándar en la evaluación de diseños de diferencias-en-diferencias y event studies: si el modelo detecta un "efecto" en una fecha donde no hubo intervención, la identificación causal es dudosa.

**Validación temporal, no aleatoria.** El k-fold aleatorio en datos de panel filtra información futura al training set, violando la estructura temporal. El rolling-origin y leave-one-quarter-out respetan la dirección temporal y simulan el uso real del modelo (predicción hacia adelante).

> **Fuentes:** Gneiting, T. & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *JASA*, 102(477), 359–378. Hyndman, R. J. & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *IJF*, 22(4), 679–688.

---

## 10. Simulador de margen y optimización (Fase 3)

### Implementación

`src/pricing/models/optimizer.py`

- `simulate_margin`: dada una política de precios propuesta, predice el volumen usando la superficie de respuesta log-log y calcula el margen esperado. Selecciona la elasticidad apropiada (base vs. total up) según la dirección del cambio de precio.
- `optimize_policy`: scaffold que actualmente aplica un incremento uniforme del 2%. Reservado para optimización con restricciones (scipy o similar) en fases posteriores.

### Justificación

La separación de simulación y optimización sigue la arquitectura de dos capas (§3 del fundamento): el motor de respuesta produce la superficie, y la capa de objetivo evalúa políticas sobre ella. La elección de elasticidad según dirección materializa la asimetría: una subida usa `β_total_up` (más elástica), una bajada usa `β_base`, evitando sobrestimar el volumen recuperado con descuentos o subestimar la pérdida con subidas.

Las restricciones pendientes incluyen: máximo incremento por segmento, restricción de aceptación del establecimiento (que el margen del local no caiga por debajo de un umbral), y presupuesto total de condiciones.

---

## 11. Identificación causal

### Implementación

La estrategia de identificación no es un módulo de código independiente sino un principio que informa el diseño de features y la validación:

1. **Escalón del 1 de diciembre.** La variable `is_post_tariff_step` (en `build_model_features`) marca los periodos posteriores a la subida anual. La variación de tarifa es centralizada y aproximadamente uniforme, lo que la convierte en un cuasi-experimento natural apto para event study / diferencias-en-diferencias.
2. **Placebo test** (en `run_placebo_test`): verifica que no hay efecto espurio en fechas sin intervención.
3. **Priors informativos** como regularización contra la endogeneidad residual: anclan la elasticidad en la banda de la literatura, limitando el daño de la correlación espuria.

### Justificación

La endogeneidad es el riesgo central del modelo: todo precio histórico es una decisión de Damm correlacionada con las características del establecimiento. Una regresión ingenua confunde "locales a los que se descuenta" con "locales sensibles al precio". La evidencia del sesgo es cuantificable: en experimentos de campo, las elasticidades experimentales son sustancialmente menores en valor absoluto que las observacionales (~−0.34 vs. ~−2.0, working paper Kellogg 2024).

La subida del 1 de diciembre es el instrumento principal porque es:
- **Exógena al establecimiento individual:** decidida centralmente, sin targeting local.
- **De magnitud relevante:** genera variación suficiente para estimar el efecto.
- **Recurrente:** permite validación cruzada entre años.

> **Fuentes:** Working paper Kellogg (2024) sobre endogeneidad de precios y comparación experimental. Tellis (1988) sobre sesgos de omisión y agregación.

---

## 12. Granularidad temporal

### Implementación

`config.TEMPORAL_GRANULARITY` define:
- `base_price: "monthly"` — la tarifa base varía una vez al año; el grano mensual es suficiente y suaviza los artefactos de pedidos y devoluciones.
- `promotions: "weekly"` — las condiciones promocionales varían a alta frecuencia; agregar a mensual atenúa la dinámica de pull-forward.

### Justificación

La agregación temporal por encima del nivel en que varía la palanca produce sesgo hacia cero en la elasticidad estimada (Tellis, 1988; Bass & Leone, 1983; Foekens et al., 1994; Wang, 2021). Sin embargo, el grano más fino no siempre es mejor: a nivel diario/semanal, las celdas Establecimiento × Material tienen ruido extremo (muchos ceros, volúmenes negativos por devoluciones). La solución es desacoplar la granularidad por tipo de palanca, usando mensual para la tarifa base y semanal para promociones, con agrupación en sección cruzada cuando la celda semanal es demasiado esparsa.

> **Fuentes:** Bass, F. M. & Leone, R. P. (1983). *Management Science*, 29(1), 1–11. Foekens, Leeflang & Wittink (1994). *IJF*, 10(2), 245–261. Wang (2021). *POM*.

---

## Referencias consolidadas

### Académicas

- Andrews, R. L., Currim, I. S., Leeflang, P. S. H. & Lim, J. (2008). Estimating the SCAN\*PRO model of store sales: HB, FM or just OLS? *International Journal of Research in Marketing*, 25(1), 25–33.
- Bass, F. M. & Leone, R. P. (1983). Temporal aggregation, the data interval bias, and empirical estimation of bimonthly relations from annual data. *Management Science*, 29(1), 1–11.
- Bijmolt, T. H. A., Van Heerde, H. J. & Pieters, R. G. M. (2005). New empirical generalizations on the determinants of price elasticity. *Journal of Marketing Research*, 42(2), 141–156.
- Bolton, R. N. (1989). The robustness of retail-level price elasticity estimates. *Journal of Retailing*, 65(2), 193–219.
- Foekens, E. W., Leeflang, P. S. H. & Wittink, D. R. (1994). A comparison and an exploration of the forecasting accuracy of a loglinear model at different levels of aggregation. *International Journal of Forecasting*, 10(2), 245–261.
- Gneiting, T. & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. *Journal of the American Statistical Association*, 102(477), 359–378.
- Hardie, B. G. S., Johnson, E. J. & Fader, P. S. (1993). Modeling loss aversion and reference dependence effects on brand choice. *Marketing Science*, 12(4), 378–394.
- Heidhues, P. & Kőszegi, B. (2008). Competition and price variation when consumers are loss averse. *American Economic Review*, 98(4), 1245–1268.
- Hoch, S. J., Kim, B.-D., Montgomery, A. L. & Rossi, P. E. (1995). Determinants of store-level price elasticity. *Journal of Marketing Research*, 32(1), 17–29.
- Hyndman, R. J. & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting*, 22(4), 679–688.
- Kahneman, D. & Tversky, A. (1979). Prospect theory: An analysis of decision under risk. *Econometrica*, 47(2), 263–291.
- Kalyanaram, G. & Little, J. D. C. (1994). An empirical analysis of latitude of price acceptance in consumer package goods. *Journal of Consumer Research*, 21(3), 408–418.
- Krishnamurthi, L., Mazumdar, T. & Raj, S. P. (1992). Asymmetric response to price in consumer brand choice and purchase quantity decisions. *Journal of Consumer Research*, 19(3), 387–400.
- Tellis, G. J. (1988). The price elasticity of selective demand: A meta-analysis of econometric models of sales. *Journal of Marketing Research*, 25(4), 331–341.
- Van Heerde, H. J., Leeflang, P. S. H. & Wittink, D. R. (2000). The estimation of pre- and post-promotion dips with store-level scanner data. *Journal of Marketing Research*, 37(3), 383–395.
- Van Heerde, H. J., Leeflang, P. S. H. & Wittink, D. R. (2001). Semiparametric analysis to estimate the deal effect curve. *Journal of Marketing Research*, 38(2), 197–215.
- Wang (2021). Aggregation bias in estimating log-log demand functions. *Production and Operations Management*.
- Wittink, D. R., Addona, M. J., Hawkes, W. J. & Porter, J. C. (1988). *The estimation, validation, and use of promotional effects based on scanner data*. Working paper, Cornell University (modelo SCAN\*PRO).

### Sector / profesional

- Marn, M. V. & Rosiello, R. L. (1992). Managing price, gaining profit. *Harvard Business Review*, 70(5).
- Marn, M. V., Roegner, E. V. & Zawada, C. C. (2003). The power of pricing. *McKinsey Quarterly*.
- Marn, M. V., Roegner, E. V. & Zawada, C. C. (2004). *The Price Advantage*. Wiley.
- Working paper, Kellogg School of Management (2024). Endogeneidad del precio y comparación experimental vs. observacional de elasticidades.

### Software

- Salvatier, J., Wiecki, T. V. & Fonnesbeck, C. (2016). Probabilistic programming in Python using PyMC3. *PeerJ Computer Science*, 2, e55. (PyMC.)
- Kumar, R. et al. (2019). ArviZ — a unified library for exploratory analysis of Bayesian models in Python. *JOSS*, 4(33), 1143.
