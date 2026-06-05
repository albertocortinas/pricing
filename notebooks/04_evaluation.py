# Databricks notebook source

# COMMAND ----------

# MAGIC %pip install -e /Workspace/Repos/aalsinat@damm.com/pricing --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC # Evaluation (3-Layer)

# COMMAND ----------

import numpy as np

from pricing.evaluation.metrics import (
    compute_crps,
    compute_wape,
    compute_rmsle,
    compute_bias,
    compute_interval_coverage,
    check_elasticity_sign,
    check_elasticity_magnitude,
    temporal_split,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Layer 1 — Fit metrics
# MAGIC
# MAGIC Run after model training to evaluate predictive quality.

# COMMAND ----------

# Example with collected posterior predictive arrays:
# posterior_samples = idata.posterior_predictive["y_obs"].values  # (chains, draws, obs)
# actuals = test_data["ln_volume"].values
#
# crps = compute_crps(posterior_samples.reshape(-1, len(actuals)), actuals)
# wape = compute_wape(predicted_mean, actuals)
# rmsle = compute_rmsle(np.exp(predicted_mean), np.exp(actuals))
# bias = compute_bias(predicted_mean, actuals)
# coverage = compute_interval_coverage(hdi_lo, hdi_hi, actuals)
#
# print(f"CRPS: {crps:.4f}")
# print(f"WAPE: {wape:.4f}")
# print(f"RMSLE: {rmsle:.4f}")
# print(f"Bias: {bias:.4f}")
# print(f"Coverage (94%): {coverage:.2%}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Layer 2 — Causal gate

# COMMAND ----------

# beta_samples = idata.posterior["beta_base"].values.flatten()
# sign_check = check_elasticity_sign(beta_samples)
# mag_check = check_elasticity_magnitude(beta_samples)
# print(f"Sign gate: P(β<0) = {sign_check['prob_negative']:.3f} — {'PASS' if sign_check['passes'] else 'FAIL'}")
# print(f"Magnitude gate: mean={mag_check['mean']:.3f}, in band={mag_check['in_band']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Layer 3 — Decision value

# COMMAND ----------

# from pricing.evaluation.metrics import compute_margin_uplift
# uplift = compute_margin_uplift(current_policy_df, model_policy_df, response_surface)
# print(f"Margin uplift: {uplift['uplift_pct']:.1f}%")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Temporal splits

# COMMAND ----------

# splits = temporal_split(features_df, method="rolling_origin", n_splits=4)
# for i, (train, test) in enumerate(splits):
#     print(f"Split {i}: train={train.count()}, test={test.count()}")
