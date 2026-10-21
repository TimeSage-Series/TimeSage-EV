"""TimeSage environment engine.

Public surface (imported by agents):
  protocol — request/response dataclasses, env-var names, status sentinels
  network  — time-isolated search_with_isolation()

Used internally:
  world, rephraser, runner, cli
"""
