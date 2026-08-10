"""Zpětně kompatibilní obal nad signal_engine.

Detekční pravidla byla sloučena s bodováním ze scoring.py do jednoho
systému v signal_engine.py. Tento modul zůstává, aby staré importy
(from app.signals import detect_signals) dál fungovaly.
"""

from .signal_engine import detect_signals, find_context, SIGNAL_RULES  # noqa: F401
