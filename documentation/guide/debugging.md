# Debugging toolkit

The debugging module supports the step after detection: understanding why the model behaves as it does. It traces the actual flux-carrying routes of the current solution.

## Exchange debugging {#exchange-debugging}

![Exchange debugging map](../assets/exchange_map.png)

The tab maps how the metabolite of one exchange reaches biomass. Essential exchanges are listed first; the remaining exchanges are available under *Show non-essential exchanges*, with a search box. The map has two parts.

* **Primary route.** The active-flux route from the exchanged metabolite to the biomass reaction in the current FBA solution (blue). The same route is also listed as text.
* **Neighbourhood.** With *Hops* set to 1, 2 or 3, every reaction that touches a metabolite on the route is added, then every reaction that touches the new metabolites, and so on. Reactions are drawn as boxes between the metabolites they consume and produce, with arrows in the direction of flux. Reactions that carry flux are green, those that carry none are grey, and reactions whose bounds are both zero are dashed red. A two-headed arrow marks a reversible reaction with no flux. Currency metabolites (the editable list) are left out and listed in the hover card of each reaction. Hover a node for its equation, bounds, subsystem and gene rule.

*Before knockout* and *After knockout* switch the flux shown. For an essential exchange growth is lost after the knockout, so no flux distribution is defined and every reaction is shown as inactive; for a non-essential exchange the flux of the re-optimised solution is shown. *Show inactive reactions* can be cleared to display only the routes in use, and the reactions in the map are listed in a table that can be downloaded as CSV.

For an essential exchange that should not be essential, the neighbourhood is the place to look for a missing or blocked step: reactions around the route that have no flux, are blocked by their bounds, or have no counterpart in the direction needed. The map is limited to 300 reactions (active reactions are kept first); lower the number of hops or hide more cofactors to see everything.

## Pathway tracer

![Pathway tracer, network view](../assets/tracer_network.png)

The tracer finds routes between a start and a target, each of which can be a **metabolite or a reaction** (pick from the list or type to search). A reaction start is resolved to the metabolites it produces, a reaction target to the metabolites it consumes. The result is drawn like the exchange map: route reactions in blue, the neighbourhood around them, and a table of every reaction shown.

| Option | Effect |
|---|---|
| Routes | *Active flux only* follows reactions carrying flux in the current solution. *All possible routes* follows every reaction whose bounds allow the direction, whether or not it carries flux, so alternatives and blocked links become visible. Shortest routes are listed first. |
| Hops | Adds every reaction within this many steps of the routes, active or not. |
| Max levels, max paths | Bound the route length and the number of distinct routes. |
| Hide cofactors | Excludes currency metabolites such as H⁺, water and ATP/ADP as route steps. The list is editable via *Currency list*. |
| Also show | Pick metabolites or reactions to always include in the map (reactions are outlined in purple). A cofactor added here is shown without being used as a route step. |
| Knock out | Pick reactions (or metabolites, which block every reaction they take part in). The map gains a before/after toggle; reactions that lose or gain flux are highlighted, and the growth impact is shown. If growth is lost, no flux is shown after the knockout. |

The map offers clustered, tree and **compartment lanes** layouts, a *Find a node* box, hover cards, and a reactions table with CSV download. The table leaves out the biomass reaction unless *Include biomass reaction* is ticked. The method is described in [Pathway tracing](../methods/tracing.md).

## Compare models

Two models are compared by naming convention first (metabolite and reaction namespaces, compartment tags), then by genes, metabolites, reactions and biomass components, listed as shared, only in the first or only in the second. Reactions are also paired by equation, and differences in bounds and coefficients are reported. Each list can be copied or exported as CSV with MetaNetX identifiers alongside the model identifiers.
