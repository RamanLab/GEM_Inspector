# Architecture

GEM Inspector is a Flask application of roughly 7,500 lines of Python and 5,500 lines of JavaScript. The back end exposes JSON endpoints over COBRApy models; the front end is a single page written in plain JavaScript, so there is no build step and no Node dependency at run time.

## Layout

| Package | Responsibility |
|---|---|
| `overview/` | Upload and model loading, summary statistics, tables, objective, exchange essentiality, and the MEMOTE job manager and worker. |
| `diagnostics/` | Minimal medium, GapFind and blocked reactions, demand and sink audit, balance and audit, biomass precursors, FROG, diet application, solver utilities. |
| `debugging/` | Active-flux tracing (shared by exchange debugging and the tracer), knockout comparison, two-model comparison and its exports. |
| `annotation/` | Namespace detection, MetaNetX cross-referencing and translation, SEED to VMH conversion, display names and the currency list. |
| `comparative/` | Multi-model statistics, automatic findings, charts, and HTML and Excel exports. |
| `core/` | Shared state: the model cache, the per-model memo, the shared knockout routine, solver configuration, report saving. |
| `static/`, `templates/` | The single-page front end, with Cytoscape.js vendored locally. |
| `data/` | MetaNetX cross-reference tables and the SEED to VMH translation tables. |

Each package registers a Flask blueprint, and `app.py` wires them together. Each analysis lives in its own module with a small function interface, so that the same function serves the interface, the report generator and the multi-model comparison.

## Model sessions and caching

An uploaded model is parsed once and held in an in-process dictionary under a random identifier, with a ten-minute inactivity time-out that every request refreshes. Requests carry the identifier rather than the model. Consequently the application has to run as a single process (see [Running and deploying](../getting-started/running.md#deployment)).

Analysis results are memoised on the model object itself. A result computed for one tab is therefore reused by a later tab, by a generated report and by the multi-model comparison, and it disappears with the model when the session expires. Models in the cache keep the bounds they were uploaded with, and every what-if calculation runs inside a COBRApy `with model:` context that restores them.

### Shared computations {#shared-computations}

Where two analyses need the same expensive quantity, it is computed once.

| Quantity | Used by |
|---|---|
| Flux variability analysis at 0 % of the optimum | Blocked reactions; FROG flux variability (at the same cut-off) |
| Single reaction knockout growth | Exchange essentiality, demand and sink audit, FROG reaction deletions |
| GapFind classification | Network gaps tab, blocked-reaction grouping, model report, multi-model comparison |

Every analysis can be started first. Each one computes what it needs if it is not yet available, so no analysis depends on a previous click. MEMOTE is the exception to sharing: it solves its own copy of the model in a separate process.

## Process isolation

Two analyses run in child processes. The GapFind linear programs run in two processes (production and consumption) so that a crash of the native solver library cannot take down the server, and they overlap in time. MEMOTE runs in a worker process that reports progress through a file, can be cancelled, and is retried with an exact-arithmetic solver if it dies.

## Solver layer

`core/solver_config.py` is the single place that decides which solver is used. It reads the `GEM_SOLVER`, `GEM_THREADS` and `GEM_PROCESSES` environment variables (set by the command-line options), tests the available solvers with a small problem, and exposes the choice to the rest of the code. COBRApy models are created with the selected solver; the minimal-medium step that minimises the number of components obtains an [optlang](https://github.com/opencobra/optlang) interface that supports integer variables. GapFind does not use the selected solver: it solves its linear programs with HiGHS through SciPy.

## Front end

The interface is a set of vanilla JavaScript modules that share a small set of helpers for sortable tables, CSV export, progress bars and entity hyperlinks. The network views use Cytoscape.js (Franz et al., 2016). Compartment lanes are an HTML overlay positioned from the Cytoscape pan and zoom state. Browser storage is used only for convenience values such as the edited currency list; nothing the user computes is stored in the browser.

## Extending the tool

A new analysis requires a function that takes the cached model and returns a JSON-serialisable result, a route in the relevant blueprint (using the shared `remember` memo if the result should be reused), and a render function and tab in the front end. The existing modules follow this pattern and are the best templates.
