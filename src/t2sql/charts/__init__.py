"""Declarative charts. Specs are validated data; no model-generated code is ever executed."""

from t2sql.charts.spec import ChartRefusal, ChartSpec, build_spec, render

__all__ = ["ChartRefusal", "ChartSpec", "build_spec", "render"]
