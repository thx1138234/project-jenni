"""
jenni — Higher Education Intelligence Layer

JENNI synthesizes 25+ years of U.S. federal institutional data (Form 990, IPEDS,
EADA, College Scorecard) into analytical output that drives decisions for the people
who advise CFOs, presidents, provosts, and boards.

Architecture:
  query_resolver  → classify query, extract entities, assemble context package
  synthesizer     → call Claude API with context package, model routing
  delivery        → Rich terminal rendering and JSON output
  cli             → click commands: analyze, compare, trend, stress, sector, data

The model never touches the database. All retrieval happens in query_resolver.
The model receives a structured context package with pre-encoded narratives clearly
marked as [pre-encoded] stable facts.
"""

__version__ = "0.1.0"
