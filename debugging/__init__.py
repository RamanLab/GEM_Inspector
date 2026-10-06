"""Debugging Toolkit.

Active-flux pathway tracing: following only the reactions that carry
non-zero flux in a given FBA solution, from a starting metabolite/reaction
to a target, optionally comparing before/after a knockout.

  - tracing.py  the shared BFS tracing engine, used by both:
                - the Exchange Debugging tab (exchanged metabolite -> biomass,
                  before and after knocking out the exchange)
                - the general-purpose Pathway Tracer (any start -> any
                  target metabolite, with an optional knockout comparison)
"""
