# GEM Inspector

**GEM Inspector** is a browser-based toolkit for inspecting, diagnosing and debugging genome-scale metabolic models (GEMs). It is built on [COBRApy](https://github.com/opencobra/cobrapy) and runs locally. It is designed around *inspection rather than repair*: it locates problems, classifies them, shows the evidence and leaves the correction to the curator.

[**Documentation:**](https://gem-inspector.readthedocs.io/en/latest/getting-started/)  installation and solver set-up, user guide, methods, benchmarks and comparison with existing tools.

> GEM Inspector is under active development. Feedback, bug reports and suggestions are welcome: [open an issue](https://github.com/RamanLab/GEM_Inspector/issues) or write to ic43006@imail.iitm.ac.in.

## What it does

| Module | Contents |
|---|---|
| **Overview** | Model statistics, linked metabolite, reaction and gene tables, objective, applied medium, and [MEMOTE](https://memote.readthedocs.io) quality report. |
| **Diagnostics** | Minimal medium, exchange essentiality, network gaps, demand/sink audits, reaction balance with an audit, biomass precursor producibility, and a FROG-style reproducibility report. |
| **Debugging** | Exchange debugging, an active-flux pathway tracer (editable cofactor list, compartment view, before/after knockout comparison) and pairwise model comparison. |
| **Annotation and translation** | Identifier namespace detection, annotation coverage, SEED to VMH translation and translation through MetaNetX. |
| **Reports** | Self-contained HTML reports from any selection of analyses, CSV exports, and a side-by-side comparison of two to five models as HTML and Excel. |

Supported model formats: SBML (also compressed), JSON, YAML and MATLAB. See the [user guide]([https://gem-inspector.readthedocs.io/en/latest/]) for details of each analysis.

## Quick start

Requires Python 3.10 or later.

```bash
# macOS / Linux
chmod +x run.sh && ./run.sh

# Windows
run.bat
```

The launcher creates a virtual environment, installs [`requirements.txt`](requirements.txt) and starts the application at <http://127.0.0.1:5000>.

### Solvers and cores

GLPK is installed by default. Gurobi or CPLEX (licence required) and HiGHS are detected at start-up:

```bash
python app.py --solver gurobi --threads 8 --processes 4
```

The same settings are available as the environment variables `GEM_SOLVER`, `GEM_THREADS` and `GEM_PROCESSES`. See [Solvers and computing resources]([https://gem-inspector.readthedocs.io/en/latest/getting-started/solvers/]/getting-started/solvers/) for the options and for CPU and memory guidance.

### Docker

```bash
docker build -t gem-inspector .
docker run -p 8080:8080 gem-inspector
```

The image runs gunicorn with a single worker (loaded models are cached in memory) and sets `GEM_HOSTED=1`, which disables saving reports to a server path. The application has no authentication; put it behind an authenticating proxy before exposing it. See [Running and deploying]([https://gem-inspector.readthedocs.io/en/latest/getting-started/running/).


## Licence and acknowledgements

Released under the [MIT licence](LICENSE). GEM Inspector builds on COBRApy, MEMOTE, SciPy (HiGHS) and Cytoscape.js, and was developed with the assistance of Claude (Anthropic).

Developed by Sabdhayini K B, Computational Systems Biology Lab, Indian Institute of Technology Madras.
