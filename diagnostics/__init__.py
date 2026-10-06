"""Diagnostics & Comparative Analyses.

On-request tabs that test the model under different conditions or flag
structural issues, independently of one another and without ever
permanently changing the cached model:

  - diet.py           applying a diet/media (none / complete / minimal /
                      custom) to exchange bounds before analysis
  - solver_utils.py   the exact-arithmetic solver switch used by every
                      repeated-solve computation below, for numerical
                      robustness
  - minimal_medium.py smallest nutrient set sustaining a chosen growth
                      cutoff (Minimal Medium tab)
  - network_gaps.py   blocked reactions and dead-end metabolites (Network
                      Gaps tab)
  - demand_sink.py    demand/sink reaction usage and essentiality audit
  - frog.py           the FROG reproducibility report (FVA, reaction
                      deletions, objective, gene deletions)
"""
