"""PBC-Hokkaido: calibrated week 3-4 outlooks of Hokkaido snow-week ingredients.

Core conventions (see docs/DATA_NOTES.md):
- every target (grid cell or scalar index) lives on a ``target`` dimension;
- weekly values are labelled by the week's start date on a daily ``time`` axis;
- cumulative probabilities ``F(k) = P(y < q_k)`` live on an integer ``k`` axis, k = 1..K-1.
"""
__version__ = "0.1.0"
