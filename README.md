# GEM / GSMM Inspector

**GEM Inspector** is a curation and debugging toolkit for genome-scale metabolic models (GEMs).

Curating a genome-scale metabolic model is rarely a straightforward process. Models can contain blocked reactions, dead-end metabolites, unexpected essential nutrients, missing pathways, inconsistent annotations, energy-generating cycles, and other issues that are often difficult to identify and trace back to their source. Debugging these problems can also become repetitive, especially when working with multiple models.

**GEM Inspector is being developed to make this process easier.** It brings together model inspection, diagnostics, comparative analyses, and debugging tools in one place, with a particular focus on helping researchers understand *why* a model behaves the way it does and where curation may be needed.

The tool is currently a **work in progress**, and we are actively expanding and improving its functionality based on ongoing use and feedback.

> **Current status:** GEM Inspector currently runs locally. You will need to clone this repository and run the application on your own machine (**[Installation & Setup](#installation--setup)**). We are also exploring the possibility of hosting it as an online tool in the future.

## What can GEM Inspector do currently?

The current version is organized around **four main modules**, covering different aspects of GEM inspection and curation:

### 1. Overview

A quick view of the model's overall structure and key properties.

* Model information and metadata
* Genes, metabolites, reactions, and compartment statistics
* Objective function and growth information
* Reaction and metabolite browsing
* Exchange reaction overview
* Diet/media selection
* MEMOTE quality assessment
* Minimal medium analysis

### 2. Diagnostics & Comparative Analyses

Tools for identifying common structural and functional issues and comparing model behaviour.

* Essential exchange analysis
* Essential gene and reaction analysis
* Blocked reaction detection
* Dead-end metabolite detection
* Demand and sink audits
* Network gap analysis
* FROG reproducibility analysis
* Model-level reports and CSV exports

### 3. Debugging Toolkit

The debugging module is a major focus of the tool. It is designed to help move beyond simply identifying an issue and instead **trace and investigate what is happening inside the model**.

* Essential exchange debugging
* Biomass precursor production checks
* Pathway tracing
* Before/after knockout comparisons
* Flux-pathway visualisation
* Energy-cycle and futile-loop investigation
* Currency/cofactor-aware pathway tracing
* Interactive network views
* Debugging and comparison reports

### 4. Annotation & Translation Toolkit

Tools for working with model annotations and translating information across identifier systems.

* Annotation coverage
* Identifier and namespace inspection
* Annotation translation across namespaces
* Model annotation quality checks

## Supported Model Formats

GEM Inspector currently accepts:

* SBML / XML
* JSON
* YAML
* MATLAB
* Supported compressed SBML files

## A few key features

### Essential Exchange Debugging

Essential exchanges can be investigated individually by tracing active-flux pathways from the exchanged metabolite towards biomass.

The tool allows comparison of:

* **Before KO** — the pathway in the original FBA solution
* **After KO** — the pathway after knocking out the exchange

This helps identify whether the exchange is required because it feeds a specific pathway, whether an alternative route exists, and where the effect of the knockout propagates through the model.

### Pathway Tracer

The general-purpose pathway tracer allows users to trace active metabolic routes between metabolites.

It supports:

* Metabolite- or reaction-based starting points
* Configurable tracing depth
* Multiple possible paths
* Currency/cofactor filtering
* Text-based pathway views
* Interactive Cytoscape.js network visualisation
* Before/after knockout comparisons

### Network Gaps & Audits

The network audit tools provide complementary views of model gaps:

* **Blocked reactions** — reactions unable to carry flux
* **Dead-end metabolites** — metabolites that can only be produced or only consumed
* **Demand & sink reactions** — usage and essentiality of demand/sink reactions

These analyses can be independently exported as CSV files.

### Diet & Minimal Medium

GEM Inspector allows users to select or define the medium used for analysis, including:

* Original model bounds
* Complete media
* Minimal media
* Custom diets

A separate minimal-medium analysis can also determine the smallest set of nutrients required to achieve a selected growth level.

### FROG Analysis

The FROG module provides model reproducibility checks through:

* **F** — Flux Variability Analysis
* **R** — Reaction deletions
* **O** — Objective value
* **G** — Gene deletions

Results can be inspected within the application and exported as CSV or a standalone HTML report.

### Reports

Results from multiple modules can be combined into a single self-contained HTML report for documentation, comparison, and sharing.

## Installation

GEM Inspector is currently designed to be run locally.

Clone this repository and follow the installation instructions:

### Installation & Setup

#### macOS / Linux

```bash
chmod +x run.sh
./run.sh
```

#### Windows

```bash
run.bat
```

Once the application starts, open:

```text
http://127.0.0.1:5000
```

For the required Python environment and dependencies, see [`requirements.txt`](requirements.txt).

## Acknowledgements

GEM Inspector is built using tools and libraries from the GEM/constraint-based modelling ecosystem, including **COBRApy**, **MEMOTE**, and **Cytoscape.js**.

For more information on the implementation and individual analyses, see the documentation and source code in this repository.
















