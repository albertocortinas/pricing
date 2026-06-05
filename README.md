# Pricing

Price optimization project built on Databricks with PySpark.

## Structure

```
notebooks/
  00_config.py              # Constants + data loaders (shared via %run)
  01_functions.py           # All functions (shared via %run)
  02_exploration.py         # Phase 1 diagnostics
  03_feature_engineering.py # Waterfall + price ratios + model features
  04_model_training.py      # SCAN*PRO fit + elasticity extraction
  05_evaluation.py          # 3-layer metrics
tests/                      # Local CI
docs/                       # Methodology documentation
```

## Databricks Usage

Open any notebook (02–05) and Run All. Each notebook starts with:

```python
%run ./00_config
%run ./01_functions
```

No `%pip install`, no `sys.path` hacks, no package imports.

## Local Development

```bash
pip install -e ".[dev]"
```

## Tests

```bash
pytest tests/ -v
```

## Lint

```bash
ruff check notebooks/ tests/
```
