# FAQ and troubleshooting

## Installation

**`pip` fails while building a package.** The Python version is probably outside 3.10 to 3.12. Create the virtual environment with a supported interpreter (`py -3.11 -m venv .venv` on Windows, `python3.11 -m venv .venv` elsewhere).

**PowerShell refuses to activate the environment.** Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window, or use the Command Prompt and `.venv\Scripts\activate.bat`.

**The browser cannot reach the page.** Check that the terminal shows the server running, and use <http://127.0.0.1:5000> (the Docker image uses port 8080). Another program may occupy port 5000; stop it, or change the port in `app.py`.

## Solvers

**Gurobi is installed but not listed as available.** The start-up check solves a small problem with each solver. If Gurobi fails it, confirm that `python -c "import gurobipy"` works in the same environment, that the licence file is in the home directory or `GRB_LICENSE_FILE` points to it, and that the licence has not expired or exceeded its machine limit. A pip-installed `gurobipy` without a licence file is limited in model size and will pass the test but fail on genome-scale problems.

**The analysis stops with a message about the solver.** For GapFind this normally means the native solver library failed. Switch to another solver (`--solver glpk` or `--solver gurobi`) and retry.

**GapFind is slow.** On large models GapFind is the slowest step; see [Benchmarks](benchmarks.md). It uses HiGHS and two processes, so make sure two cores are free; the solver setting does not affect it.

## Using the tool

**"Model not found or expired".** A model is discarded after ten minutes without activity. Re-run the initial analysis.

**A request fails with "Failed to fetch".** The server stopped or restarted while the request was running. Check the terminal for a traceback and, when reporting the problem, include it.

**The wild-type growth is zero.** The medium may lack an essential nutrient or the objective may be misidentified. Use *Exchange essentiality* and *Biomass precursors* to find what is missing.

**A large model uses a lot of memory.** Keep `--processes 1`, close sessions you no longer need, and avoid running several analyses on several large models at once.

## Reporting a problem

Please send the model identifier or file (if it can be shared), the steps to reproduce, the start-up line beginning `Inspector:` (it shows the solver and options), and any traceback from the terminal. Issues can be filed at [REPO-URL]/issues.
