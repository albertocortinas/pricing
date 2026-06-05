# Fundamento metodológico — Modelo de pricing HORECA

**Versión 0.1 · junio de 2026**
Documento de diseño previo a la implementación. Fija el marco conceptual y la forma funcional del modelo de respuesta a precio, con su justificación académica, antes de escribir código.

---

## 1. Objetivo y alcance

El encargo es construir un modelo de pricing sobre el panel de ventas y rentabilidad a granularidad Establecimiento × Material × Mes × Distribuidor. Existen varios enfoques posibles (política tarifaria, estrategia de promociones, mejora de margen, propuesta de condiciones por cluster). Este documento sostiene que **no son modelos alternativos sino capas de un mismo problema**, y fija las decisiones de diseño y la forma funcional que se derivan de la literatura, dejando la implementación para una fase posterior.

---

## 2. Estructura del problema

La cadena es Damm → distribuidor → establecimiento. Dado que **todas las decisiones de precio y condiciones las toma Damm**, el distribuidor es un conducto logístico con un *spread* administrado y no un agente que optimiza su propio margen. En consecuencia:

- No aplica la doble marginalización ni el *pass-through* estratégico: no hay que modelar una función de reacción del distribuidor. El problema es **de un solo agente**.
- La vista anclada en la tarifa de distribuidor (código 900) es **contabilidad de margen**, no un segundo precio con comportamiento propio.
- El "margen distribuidor" (50 − 900 − 901 − 902 − 920) es una constante contractual, no una variable de decisión.

Los datos tienen la estructura de una **cascada de pocket price** (Marn & Rosiello, 1992; Marn, Roegner & Zawada, 2003): tarifa de lista (050) menos deducciones *on-invoice* (descuentos 210, promociones 300) y *off-invoice* (rappels 740, amortizaciones CDT 420, obsequios 100) hasta la venta neta; la tabla de rentabilidad extiende esa cascada hasta el *pocket margin* restando el stack de costes y la capa de distribuidor. La cantidad de demanda es **consumo neto** (envíos menos devoluciones), no envíos brutos, lo que elimina el ruido de acumulación de stock.

---

## 3. Arquitectura en dos capas

El diseño separa dos componentes que suelen confundirse:

1. **Motor de respuesta a precio** — cómo responde el volumen del establecimiento a la palanca. Se estima una sola vez y produce una superficie de elasticidades. Es el activo caro y reutilizable.
2. **Capa de objetivo** — qué se maximiza (volumen, ingreso, margen Damm, margen del establecimiento). Son funciones objetivo distintas evaluadas sobre la misma superficie de respuesta, con distinta economía y restricciones.

La consecuencia operativa: cambiar de objetivo **no** rehace el motor. Lo que sí define el motor son dos decisiones previas —la **palanca** (variable de decisión) y el **sujeto de demanda**—, que constituyen la Fase 0.

---

## 4. Decisiones de diseño (Fase 0)

- **Sujeto de demanda:** el establecimiento (consumo / *sell-through*). La fijación de precio al consumidor que hace el propio bar queda absorbida dentro de la relación volumen–precio que se estima; no requiere modelarse como agente aparte.
- **Objetivo:** margen Damm (*pocket margin*). Volumen e ingreso son lentes intermedias; el margen del establecimiento entra como **restricción de aceptación** (el local debe poder repercutir la subida o abandona).
- **Palancas:** tarifa base (050) más el vector de condiciones (descuentos, promociones, rappels, contratos/amortizaciones CDT).
- **Identificación:** la subida de tarifa efectiva a 1 de diciembre (en 2022 hubo varias) como experimento natural, más experimentos diseñados. El histórico es endógeno (ver §7).

---

## 5. Forma funcional: validación académica

### 5.1. Elección de forma funcional

El meta-análisis de referencia (Tellis, 1988; 367 elasticidades) concluye que la forma funcional concreta apenas mueve la elasticidad estimada, mientras que sí la sesgan severamente la agregación temporal, la omisión de distribución o calidad, y el uso de datos solo transversales. La actualización de Bijmolt, Van Heerde & Pieters (2005), con 1.851 elasticidades, sitúa la media en torno a −2,6 y subraya la necesidad de distinguir precio actual, regular (base) y promocional; Bolton (1989) matiza que sí existen diferencias pequeñas pero significativas entre formas lineal, multiplicativa y exponencial. La lectura práctica: el **log-log multiplicativo** (elasticidad constante) es la base defendible por interpretabilidad y estándar, y el esfuerzo debe ir al control de sesgos, no a la forma.

### 5.2. Cómo entran las condiciones: SCAN\*PRO

El modelo canónico de respuesta de ventas a nivel de punto de venta es SCAN\*PRO (Wittink, Addona, Hawkes & Porter, 1988; Foekens, Leeflang & Wittink, 1994; Andrews, Currim, Leeflang & Lim, 2008). Es multiplicativo y descompone las ventas en efectos propios y cruzados de precio, *feature*, *display*, efectos de semana y de tienda. Clave para este proyecto: **el precio entra como ratio del precio actual sobre el precio regular (base)**, y los instrumentos promocionales entran como multiplicadores. Esto justifica **no colapsar todo en un único *pocket price***, sino estimar la elasticidad del precio base (tarifa regular 050) y, por separado, multiplicadores por cada condición. La curva de efecto-promoción es además no lineal (Van Heerde, Leeflang & Wittink, 2001) y genera *dips* pre y post promoción (Van Heerde, Leeflang & Wittink, 2000) —la dinámica de *pull-forward* a controlar.

### 5.3. Asimetría y precio de referencia

Como la palanca tarifaria es una **subida**, la asimetría de respuesta es central. Desde la teoría del prospecto (Kahneman & Tversky, 1979), las pérdidas pesan más que las ganancias, de modo que la demanda es más elástica ante subidas que ante bajadas, con una curva con *kink* en el precio de referencia. La evidencia empírica en bienes de consumo lo confirma (Hardie, Johnson & Fader, 1993; Krishnamurthi, Mazumdar & Raj, 1992; Kalyanaram & Little, 1994) y existe formalización teórica para fijación de precios bajo aversión a la pérdida (Heidhues & Kőszegi, 2008). Un estudio de demanda de bebidas azucaradas en Gran Bretaña (*Journal of Economic Behavior & Organization*, 2020) documenta asimetría empírica en una categoría de bebidas, con reacción más fuerte cuando el precio sube por encima del nivel de referencia. **Implicación:** un log-log simétrico subestima la caída de volumen de una subida; hay que permitir asimetría (coeficiente de subida separado o término de referencia con *kink* anclado en el escalón del 1-dic).

### 5.4. Heterogeneidad y jerarquía

La heterogeneidad entre establecimientos es sistemática, no ruido (Hoch, Kim, Montgomery & Rossi, 1995), y la extensión bayesiana jerárquica de SCAN\*PRO está bien establecida (Andrews et al., 2008). Esto fundamenta una capa **jerárquica bayesiana con *shrinkage*** (*empirical Bayes*) que estabiliza las celdas esparsas contrayéndolas hacia la media de su familia.

### 5.5. Sesgos a controlar

Siguiendo a Tellis (1988): controlar **distribución/disponibilidad** y **calidad/marca** (omitirlas sesga la elasticidad en direcciones conocidas), usar **panel** y no solo corte transversal, y vigilar la **agregación temporal** (ver §6).

---

## 6. Granularidad temporal

**Principio:** elegir el grano más fino en el que (a) la palanca que se mide realmente varía y (b) se preserva la dinámica relevante, manteniendo celdas con señal; almacenar siempre al grano más fino y agregar hacia arriba (de mensual no se recupera la semana).

**Evidencia del sesgo de agregación.** La agregación temporal por encima del nivel semanal produce sesgo hacia cero en la elasticidad, al perderse las fluctuaciones temporales y recaer el peso en la variación transversal (Tellis, 1988). Es un resultado robusto en la literatura de sesgo por intervalo de datos (Bass & Leone, 1983) y de nivel de agregación en modelos log-lineales de ventas (Foekens, Leeflang & Wittink, 1994; Wang, 2021).

**Aplicación al caso.** El aviso anterior supone variación de precio de alta frecuencia. La tarifa base se mueve una vez al año (1-dic), por lo que no hay señal semanal de precio base que perder. De ahí un reparto por palanca:

- **Elasticidad de precio base y *event study* del 1-dic → mensual** (Establecimiento × Material). Cuadra con la frontera del 1-dic, y suaviza la grumosidad de pedidos y el desfase de devoluciones, que a grano diario/semanal generan meses con volumen negativo espurio.
- **Respuesta a promociones/condiciones → semanal.** Ahí vive la variación de alta frecuencia y la dinámica de *pull-forward*; agregar a mensual la atenúa. A nivel local × SKU la semana es casi todo ceros, por lo que conviene **subir la sección cruzada** (clusters de locales, o marca × región) para que la celda tenga señal.
- **Diario → fuera del modelo de respuesta.** Reservado a *forecast* operativo, estacionalidad de día de semana, o al *timing* exacto del *forward-buying* alrededor del 1-dic.

**Trade-off de dos ejes:** tiempo y sección cruzada compiten por densidad de celda; más fino en el tiempo obliga a más grueso en la sección cruzada. **Diagnóstico de robustez:** estimar el mismo efecto a dos granos contiguos; si la elasticidad se atenúa al engrosar, es sesgo de agregación y se confía en el grano fino para ese efecto.

---

## 7. Identificación causal y endogeneidad

Dado que **todo precio del histórico es una decisión de Damm**, la dispersión del *pocket price* entre establecimientos (el *price band*) refleja a quién decidió Damm dar condiciones —potencial, presión competitiva, riesgo de fuga, negociación—, no la sensibilidad al precio. Es endogeneidad máxima: una regresión ingenua de volumen contra precio confunde "locales a los que descontamos" con "locales sensibles". La magnitud del problema está documentada: en un experimento de campo a gran escala, las elasticidades experimentales fueron muy inferiores en valor absoluto a las observacionales (≈ −0,34 frente a ≈ −2,0; *working paper*, Kellogg, 2024).

Estrategia de identificación, en orden de fiabilidad:

1. **El escalón central del 1-dic** como columna vertebral: variación no targetizada local a local, aplicada de forma ~uniforme y centralizada (*event study* / diferencias-en-diferencias).
2. **Reglas mecánicas** que generen cuasi-aleatoriedad: umbrales de rappel (*regression discontinuity*), *rollouts* de promoción por calendario independientes del estado del local (diferencias-en-diferencias).
3. **Experimentos diseñados:** como Damm controla todas las palancas, puede aleatorizar tarifa o condiciones sobre locales emparejados. Es el *gold standard* y elimina la endogeneidad de raíz; conviene reservar 2-3 tests pequeños desde el inicio.

---

## 8. Promociones e incrementalidad

El objetivo correcto para promociones no es maximizar ventas sino el **margen incremental sobre baseline**, neto de *pull-forward* y canibalización; el *apparent lift* sobrestima sistemáticamente el efecto (Van Heerde, Leeflang & Wittink, 2000). La evidencia del sector indica que una proporción elevada de las promociones no genera margen incremental y que el gasto en *trade* representa una fracción sustancial de los ingresos en bienes de consumo (McKinsey). Esto refuerza que la palanca promocional debe evaluarse con el motor causal y no con medias históricas.

---

## 9. Especificación recomendada

- **Núcleo:** modelo log-log multiplicativo tipo SCAN\*PRO sobre el consumo neto.
- **Precio en dos bloques:** elasticidad del precio base (tarifa regular 050) más multiplicadores/semi-elasticidades por condición (descuento, promoción, rappel, CDT). El *pocket price* único se reserva como modelo *benchmark* de cordura.
- **Asimetría** en el precio base, anclada al escalón del 1-dic (término de referencia con *kink* o coeficiente de subida separado). Es la desviación deliberada respecto al SCAN\*PRO clásico, justificada por el objetivo de optimizar subidas.
- **Jerárquico bayesiano:** *shrinkage* Material → línea → marca y Establecimiento → categoría/provincia, con efecto de establecimiento y estacionalidad mensual; control de disponibilidad/distribución.
- **Validación:** signos correctos, magnitudes acotadas usando los rangos de la literatura como *prior* —con la salvedad de que esas medias provienen de retail orientado a consumidor, mientras que el canal HORECA con *lock-in* de contrato CDT y lealtad de marca puede ser bastante más inelástico—, contraste fuera de muestra (*leave-one-quarter-out*) y validación contra el experimento del 1-dic.
- **Camino de mejora:** si se incorporan precios de competencia, migrar hacia un modelo de atracción/logit o un sistema de demanda (AIDS/EASI), que maneja efectos cruzados y acomoda la asimetría de forma teóricamente consistente.

---

## 10. Riesgos principales

- Confundir locales descontados con locales sensibles (endogeneidad del histórico).
- Subestimar la elasticidad por agregación temporal por encima del nivel necesario.
- Subestimar la caída de volumen por asumir simetría en la respuesta a subidas.
- Meses-cola por desfase de devoluciones (volumen casi nulo o negativo).
- Esparsidad a nivel local × SKU, que obliga a *shrinkage* y a elegir bien el grano.

---

## 11. Roadmap por fases

- **Fase 0 — Objetivo y decisor (cerrada).** Sujeto = establecimiento; objetivo = margen Damm; palancas = tarifa + condiciones; identificación = 1-dic + experimentos.
- **Fase 1 — Diagnóstico.** Cascada de *pocket price*, *price band* por SKU/segmento, cuantificación de fugas.
- **Fase 2 — Motor causal.** Especificación del §9, identificación del §7, validación dura.
- **Fase 3 — Simulador y optimización.** Optimización con *guardrails* y, como salida, la propuesta de condiciones (tarifa + condiciones) óptima por segmento.

---

## Referencias

*Nota: las referencias proceden de la literatura consultada durante el diseño. Conviene verificar los datos bibliográficos exactos (volumen, número, páginas) contra la fuente original antes de un uso formal.*

**Académicas**

- Andrews, R. L., Currim, I. S., Leeflang, P. S. H., & Lim, J. (2008). Estimating the SCAN\*PRO model of store sales: HB, FM or just OLS? *International Journal of Research in Marketing*.
- Bass, F. M., & Leone, R. P. (1983). Temporal aggregation, the data interval bias, and empirical estimation of bimonthly relations from annual data. *Management Science*, 29(1), 1–11.
- Bijmolt, T. H. A., Van Heerde, H. J., & Pieters, R. G. M. (2005). New empirical generalizations on the determinants of price elasticity. *Journal of Marketing Research*, 42(2), 141–156.
- Bolton, R. N. (1989). The robustness of retail-level price elasticity estimates. *Journal of Retailing*, 65(2), 193–219.
- Foekens, E. W., Leeflang, P. S. H., & Wittink, D. R. (1994). A comparison and an exploration of the forecasting accuracy of a loglinear model at different levels of aggregation. *International Journal of Forecasting*, 10(2), 245–261.
- Hardie, B. G. S., Johnson, E. J., & Fader, P. S. (1993). Modeling loss aversion and reference dependence effects on brand choice. *Marketing Science*, 12(4), 378–394.
- Heidhues, P., & Kőszegi, B. (2008). Competition and price variation when consumers are loss averse. *American Economic Review*.
- Hoch, S. J., Kim, B.-D., Montgomery, A. L., & Rossi, P. E. (1995). Determinants of store-level price elasticity. *Journal of Marketing Research*, 32(1), 17–29.
- Kahneman, D., & Tversky, A. (1979). Prospect theory: An analysis of decision under risk. *Econometrica*, 47(2), 263–291.
- Kalyanaram, G., & Little, J. D. C. (1994). An empirical analysis of latitude of price acceptance in consumer package goods. *Journal of Consumer Research*, 21(3), 408–418.
- Krishnamurthi, L., Mazumdar, T., & Raj, S. P. (1992). Asymmetric response to price in consumer brand choice and purchase quantity decisions. *Journal of Consumer Research*, 19(3), 387–400.
- Tellis, G. J. (1988). The price elasticity of selective demand: A meta-analysis of econometric models of sales. *Journal of Marketing Research*, 25(4), 331–341.
- Van Heerde, H. J., Leeflang, P. S. H., & Wittink, D. R. (2000). The estimation of pre- and post-promotion dips with store-level scanner data. *Journal of Marketing Research*, 37(3), 383–395.
- Van Heerde, H. J., Leeflang, P. S. H., & Wittink, D. R. (2001). Semiparametric analysis to estimate the deal effect curve. *Journal of Marketing Research*, 38(2), 197–215.
- Wang, (2021). Aggregation bias in estimating log-log demand functions. *Production and Operations Management*.
- Wittink, D. R., Addona, M. J., Hawkes, W. J., & Porter, J. C. (1988). *The estimation, validation, and use of promotional effects based on scanner data*. Working paper, Johnson Graduate School of Management, Cornell University. (Modelo SCAN\*PRO.)
- Estudio de demanda de bebidas azucaradas con elasticidades asimétricas y precios de referencia. *Journal of Economic Behavior & Organization* (2020). *(Verificar autoría antes de citar formalmente.)*

**Sector / profesional**

- Marn, M. V., & Rosiello, R. L. (1992). Managing price, gaining profit. *Harvard Business Review*, 70(5).
- Marn, M. V., Roegner, E. V., & Zawada, C. C. (2003). The power of pricing. *McKinsey Quarterly*. (Ver también *The Price Advantage*, 2004.)
- *Working paper* sobre endogeneidad del precio y comparación experimental vs. observacional de elasticidades. Kellogg School of Management (2024). *(Verificar autoría y título exacto.)*
