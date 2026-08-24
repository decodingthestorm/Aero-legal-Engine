"""Uncertainty quantification for stochastic (LLM-generated) outputs.

Semantic entropy over bidirectional-entailment clusters, used as an
abstention gate: when a model's sampled answers disagree with each other
about *meaning* (not just wording), the right move is to refuse rather
than to return one of them.
"""
