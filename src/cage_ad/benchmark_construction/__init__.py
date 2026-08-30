"""Benchmark construction gates, intentionally independent of diagnosis policies."""

from .admission import AdmissionError, AdmissionPolicy, evaluate_candidate

__all__ = ["AdmissionError", "AdmissionPolicy", "evaluate_candidate"]
