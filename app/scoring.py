"""Zpětně kompatibilní obal nad signal_engine.

Původní bodovací pravidla byla sloučena s pravidly ze signals.py
do jednoho systému v signal_engine.py. Tento modul zůstává, aby
staré importy (from app.scoring import analyze) dál fungovaly.
"""

from .signal_engine import analyze  # noqa: F401
