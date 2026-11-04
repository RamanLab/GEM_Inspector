# Debugging toolkit

The debugging module supports the step after detection: understanding why the model behaves as it does. It traces the actual flux-carrying routes of the current solution.

## Exchange debugging {#exchange-debugging}

For each essential exchange selected from the essentiality scan, the tool traces active-flux routes from the exchanged metabolite to biomass, once with the exchange available and once with it removed. Comparing the two shows which route disappears, whether an alternative route is used, and how far the effect propagates. Common cofactors can be hidden from the traces.

## Pathway tracer

![Pathway tracer, network view](../assets/tracer_network.png)

The tracer finds active-flux routes between any start (a metabolite, or a reaction resolved to the metabolites it currently produces) and any target metabolite.

| Option | Effect |
|---|---|
| Max levels, max paths | Bound the search depth and the number of distinct routes returned. |
| Hide common cofactors | Excludes currency metabolites such as H⁺, water and ATP/ADP as path steps. The list is editable: *Currency list* opens an editor, and the edited list applies to exchange debugging and the tracer. |
| Also show metabolites | A comma-separated list (for example `atp, nadh`). Each listed metabolite that a route reaction consumes or produces is displayed one step off the route, so selected cofactors can be shown without being followed as path steps. |
| Compare knockout | One or more reaction or metabolite identifiers are blocked and the same route search is repeated; a before/after toggle highlights reactions whose flux changed, disappeared or appeared, together with the growth impact. |
| View as | A step-by-step text view, or an interactive network (zoom, pan, subsystem and flux filters, search, hover cards). |

In the network view, **Compartment lanes** separates the graph into horizontal bands, one per compartment, divided by dashed lines. Columns follow the order along the route, node outlines are coloured by compartment, and reactions that cross a dividing line are transport steps. The method is described in [Pathway tracing](../methods/tracing.md).

## Compare models

Two models are compared by naming convention first (metabolite and reaction namespaces, compartment tags), then by genes, metabolites, reactions and biomass components, listed as shared, only in the first or only in the second. Reactions are also paired by equation, and differences in bounds and coefficients are reported. Each list can be copied or exported as CSV with MetaNetX identifiers alongside the model identifiers.
