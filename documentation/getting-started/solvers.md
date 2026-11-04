# Solvers and computing resources

Almost every analysis in GEM Inspector reduces to linear programs (LPs): flux balance analysis, flux variability analysis (FVA), single reaction and gene deletions. One option, the minimal medium with *minimize number of components*, is a mixed-integer program (MILP). The GapFind dead-end classification is solved as linear programs with HiGHS (SciPy) whichever solver is selected, so the solver choice mainly affects FBA, FVA, deletion scans and that one MILP.

## Choosing a solver

| Solver | LP | MILP | Licence | Notes |
|---|---|---|---|---|
| GLPK | yes | yes | Open source | Installed by default. Reliable on models up to a few thousand reactions; its MILP option is slow on large models. |
| HiGHS (via SciPy) | yes | no | Open source | Fast LP solver. Because it cannot solve integer programs, MILP steps automatically use another solver. |
| Gurobi | yes | yes | Commercial; free academic licences | Recommended where available. Substantially faster for MILP and large LPs, and multi-threaded. |
| CPLEX | yes | yes | Commercial; academic programme | Supported through the same interface as Gurobi. |

With the default setting (`auto`) the application tests each solver at start-up and selects the first that works, in the order Gurobi, CPLEX, GLPK, HiGHS. A solver is accepted only if it solves a small test problem, which also catches a missing or expired licence. When a solver that cannot solve MILPs is chosen, the MILP analyses use the best available solver that can.

## Selecting a solver at start-up

There are three equivalent ways to make the choice.

=== "Interactive"

    Run `python app.py` in a terminal. If more than one solver is detected and no choice was made in advance, the application lists them and asks which to use; pressing Enter selects `auto`.

=== "Command line"

    ```bash
    python app.py --solver gurobi --threads 8 --processes 4
    ```

=== "Environment variables"

    ```bash
    export GEM_SOLVER=gurobi      # auto | gurobi | cplex | glpk | scipy
    export GEM_THREADS=8          # threads per solver call
    export GEM_PROCESSES=4        # worker processes for FVA and deletion scans
    python app.py
    ```

    On Windows PowerShell use `$env:GEM_SOLVER = "gurobi"`; in the Command Prompt, `set GEM_SOLVER=gurobi`.

Environment variables are the appropriate mechanism under gunicorn or Docker, where there is no terminal to prompt. They are also read by the child processes that run MEMOTE and GapFind, so every part of the application uses the same solver. The solver in use is shown on the **Solver** card of the summary.

!!! tip "The launcher scripts"
    `run.bat` and `run.sh` call `python app.py` without options, so the interactive prompt appears when several solvers are installed. To fix the choice, set the environment variables before running the script or edit the last line of the script.

## Gurobi {#gurobi}

1. **Obtain a licence.** Free academic licences are available to students and staff of degree-granting institutions through the Gurobi academic programme; commercial licences, Web License Service (WLS) licences and cloud licences are also available. The licence type determines whether it may be used on a shared server, so read the terms before deploying a hosted instance.
2. **Install the Python package** in the same environment as the application:

    ```bash
    python -m pip install gurobipy
    ```

    A pip-installed `gurobipy` includes a restricted trial licence that is limited in model size (a few thousand variables and constraints); it is adequate for toy models but not for genome-scale work.
3. **Activate the licence.** For a named-user academic licence, run the `grbgetkey` command supplied with the licence key; this writes `gurobi.lic` to the home directory. For a WLS licence, save the `gurobi.lic` file provided by the licence portal in the home directory, or set the `GRB_LICENSE_FILE` environment variable to its location.
4. **Check.** Start the application with `--solver gurobi`. The start-up line should read `solver=gurobi (MILP: gurobi)`. If Gurobi is not listed among the available solvers, the licence or the package is not found; the FAQ explains how to check each.

## CPLEX {#cplex}

Install the Python bindings with `python -m pip install cplex`. The version distributed on PyPI is size-limited; for genome-scale models install the full CPLEX Optimization Studio (the IBM academic programme provides it free of charge to eligible users) and its Python API as described in the IBM documentation. Then start with `--solver cplex`.

## Threads and worker processes

Two separate settings control parallelism.

**Threads (`--threads`, default: the smaller of 4 and the number of cores)** is the number of threads a single solver call may use. It applies to Gurobi and CPLEX and has no effect on GLPK, which is single-threaded.

**Worker processes (`--processes`, default: 1 on Windows and up to 4 elsewhere)** is the number of processes used for the embarrassingly parallel scans, namely FVA and the single reaction and gene deletions of the FROG report. These run one LP per reaction or gene, so they scale almost linearly with the number of cores. Windows starts new processes slowly (it cannot fork), which is why the default there is conservative; increase it for large models if memory permits, since each worker holds a copy of the model.

In addition, the GapFind analysis always runs its two problems, one for production and one for consumption, as two separate processes, so two free cores shorten it by up to a factor of two regardless of these settings.

### Practical guidance

| Situation | Suggestion |
|---|---|
| Laptop, models below about 3,000 reactions | Defaults. GLPK is sufficient. |
| Large models, or repeated use of the dead-end analysis | Use Gurobi if a licence is available. |
| Shared server | One gunicorn worker (see [Running and deploying](running.md#deployment)); `--threads` times the number of simultaneous users should not exceed the number of cores. |
| Memory-constrained machine | Keep `--processes 1`. |

## CPU, memory and GPU

The workload is CPU-bound and, for the LP and MILP solvers, largely sequential within a single solve. A GPU is not used and would not help: simplex and branch-and-cut solvers do not run on GPUs, and the problem sizes here (thousands of rows and columns) are small for first-order GPU methods. When sizing a machine, prefer additional cores (for FVA, deletion scans and concurrent users) and memory (about 1 to 3 GB per loaded genome-scale model plus a copy per worker process) over specialised hardware. [Benchmarks](../benchmarks.md) reports measured timings.
