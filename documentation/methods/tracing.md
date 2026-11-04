# Pathway tracing

Exchange debugging and the pathway tracer share one implementation. It answers the question: *given the current flux solution, along which routes does a metabolite reach a target?*

## Graph construction

A flux balance solution is computed for the model as currently constrained. Only reactions with a non-zero flux (above $10^{-9}$) are retained. Each retained reaction contributes directed edges from its substrates to its products, where substrate and product roles follow the *sign of the flux*: a reversible reaction running backward is traversed with its roles swapped. The graph therefore represents what the cell is doing in this solution, not what the network could do.

## Search

A breadth-first search starts at the chosen metabolite (or at each product of the chosen reaction) and stops at the target. A reaction may appear only once in a route, which excludes cycles. A route that reaches the target is not extended. The search is bounded by the maximum number of levels and the maximum number of routes.

Two routes that consist of the same reactions in the same order are counted once. Without this, a reaction that has several products leading to the target would be reported as several identical routes.

## Currency metabolites

Highly connected cofactors (H⁺, water, ATP/ADP, NAD(H), phosphate and similar) would link almost any two metabolites through trivial hops. They are therefore excluded as path steps by default. The list is user-editable and applies to both exchange debugging and the tracer. The start and target metabolites are never excluded, even if they appear on the list. Metabolites named in *Also show metabolites* are not followed either; they are attached to the route reaction that consumes or produces them, so that a cofactor of interest can be displayed without being used as a link.

## Knockout comparison

For the before/after comparison, the requested reactions are blocked inside a temporary model context, the model is re-optimised and the same search is run on the new solution. A metabolite is knocked out by blocking every reaction in which it participates. The before and after routes are compared reaction by reaction, and each reaction on either route is labelled blocked, newly used, changed in flux, or unaffected.

## Compartment view

Metabolite compartments are read from the model. In the lane view each compartment is a horizontal band; the horizontal position of a metabolite is its first occurrence along the routes, and several metabolites of the same band and column are stacked vertically. The bands are drawn behind the graph and follow panning and zooming.
