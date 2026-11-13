# Installation

GEM Inspector is a Python (Flask) application that serves a web interface on the local machine. Installation consists of obtaining the source code, creating an isolated Python environment, installing the dependencies and starting the server. No database or external service is required.

## 1. Requirements

| Component | Requirement |
|---|---|
| Operating system | Windows 10/11, macOS, or a current Linux distribution. |
| Python | 3.10, 3.11 or 3.12 (3.11 is used for the Docker image). Python must be on the `PATH`. |
| Memory | 4 GB is sufficient for models of about 3,000 reactions; 8 GB or more is advisable for larger models (for example human reconstructions) and for MEMOTE. |
| Disk | About 1 GB for the environment, including MEMOTE and its dependencies. |
| Browser | A current Chrome, Edge, Firefox or Safari. |
| Network | Required only during installation (package download). The tool itself runs offline. The MetaNetX tables used for translation are shipped in the `data/` folder. |
| Solver | GLPK is installed automatically. Gurobi, CPLEX and HiGHS are optional; see [Solvers](solvers.md). |

!!! note "Compiler and libSBML"
    The dependencies (`cobra`, `python-libsbml`, `scipy`) are distributed as pre-built wheels for the supported platforms, so no compiler is normally needed. If `pip` begins compiling a package, the Python version is probably too new or too old; use one of the versions listed above.

## 2. Obtain the source code

=== "Git"

    ```bash
    git clone https://github.com/RamanLab/GEM_Inspector.git
    cd GEM_Inspector
    ```

=== "Archive"

    Download the repository as a ZIP archive, extract it, and open a terminal in the extracted folder (the one that contains `app.py`).

## 3. Install and start

### One-step launcher

The repository contains launcher scripts that create a virtual environment named `.venv`, install `requirements.txt` and start the application.

=== "Windows"

    ```bat
    run.bat
    ```

=== "macOS / Linux"

    ```bash
    chmod +x run.sh
    ./run.sh
    ```

When the server starts, open <http://127.0.0.1:5000> in a browser.

### Manual installation

The manual procedure is preferable when a particular Python interpreter or solver configuration is needed.

=== "Windows (PowerShell)"

    ```powershell
    py -3.11 -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    python app.py
    ```

    If activation is blocked, allow scripts for the current session with
    `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, or use `.venv\Scripts\activate.bat` from the Command Prompt.

=== "macOS / Linux"

    ```bash
    python3.11 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    python app.py
    ```

The first start prints a line of the form

```text
Inspector: solver=glpk (MILP: glpk), threads=4, processes=1; available: glpk, scipy
```

which reports the solver in use and the solvers that were detected. See [Solvers and computing resources](solvers.md) to change it.

## 4. Verify the installation

1. Open <http://127.0.0.1:5000> and choose **Inspect a single model**.
2. Upload any SBML or JSON model. The *E. coli* core model (`e_coli_core`) from the [BiGG Models](http://bigg.ucsd.edu) database is a convenient small test case.
3. Press **Analyze**. The summary cards (genes, metabolites, reactions, compartments, wild-type growth, solver) should appear within seconds.

For a numerical check of the installation, the *E. coli* core model should report 95 reactions, 72 metabolites, 137 genes and a wild-type growth rate of about 0.874 h⁻¹ on its default medium.

## 5. Optional components

| Component | Purpose | Installation |
|---|---|---|
| Gurobi | Faster LP/MILP solving on large models (FVA, deletion scans, minimal medium) | `python -m pip install gurobipy` and a licence; see [Solvers](solvers.md#gurobi) |
| CPLEX | Alternative commercial solver | `python -m pip install cplex` and a licence; see [Solvers](solvers.md#cplex) |
| MEMOTE | Quality score on the Overview page | Included in `requirements.txt` |
| Reference chemistry table | Reference formulas and charges for the balance audit | Place `chem_prop.tsv` from MetaNetX in `data/` (optional) |

## 6. Docker

```bash
docker build -t gem-inspector .
docker run --rm -p 8080:8080 gem-inspector
```

The application is then available at <http://127.0.0.1:8080>. The image runs gunicorn with one worker and several threads, which is deliberate (see [Running and deploying](running.md#deployment)).

## 7. Updating and uninstalling

To update, pull the latest source and re-run `python -m pip install -r requirements.txt` inside the environment. To uninstall, delete the project folder; the virtual environment lives inside it and nothing is written elsewhere, apart from temporary files in the operating-system temporary directory, which are removed when a model session expires.
