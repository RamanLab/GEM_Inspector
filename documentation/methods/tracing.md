# Pathway tracing

Exchange debugging and the pathway tracer share one implementation. It answers the question: *given the current flux solution, along which routes does a metabolite reach a target?*

## Graph construction

A flux balance solution is computed for the model as currently constrained. In *active* mode only reactions with a non-zero flux (above $10^{-9}$) are retained. In *all possible routes* mode every reaction is retained in each direction its bounds allow (forward if the upper bound is positive, reverse if the lower bound is negative; blocked reactions are skipped). Each retained reaction contributes directed edges from its substrates to its products, where substrate and product roles follow the *sign of the flux*: a reversible reaction running backward is traversed with its roles swapped. The active graph therefore represents what the cell is doing in this solution; the all-routes graph represents what the network could do.

## Search

Breadth-first distances from the start and to the target (over the reversed graph) are computed first. A depth-first search then lists routes whose length does not exceed the shortest route plus three reactions, never reusing a reaction or metabolite and discarding any branch that can no longer reach the target in time. The shortest routes are kept when more exist than the maximum number requested. A reaction start is resolved to the metabolites it produces and a reaction target to the metabolites it consumes (cofactors excluded).

Two routes that consist of the same reactions in the same order are counted once. Without this, a reaction that has several products leading to the target would be reported as several identical routes.

## Currency metabolites

Highly connected cofactors (H⁺, water, ATP/ADP, NAD(H), phosphate and similar) would link almost any two metabolites through trivial hops. They are therefore excluded as path steps by default. The list is user-editable and applies to both exchange debugging and the tracer. The start and target metabolites are never excluded, even if they appear on the list. Metabolites added under *Also show* are drawn but not used as route steps unless they lie on a route anyway.

## Neighbourhood

With *hops* above zero, every reaction that touches a route metabolite (cofactors excluded) is added, then those touching the newly added metabolites, up to the chosen number of hops. Active reactions are added first and the map is capped at 300 reactions.

## Knockout comparison

The requested reactions are blocked inside a temporary model context and the model is re-optimised. The map keeps the routes found for the unmodified model and shows each reaction's flux before and after; a reaction active before and inactive after is marked as lost, the reverse as gained. A metabolite is knocked out by blocking every reaction in which it participates. When the knockout abolishes growth, no flux distribution is shown after it, because the solver then returns an arbitrary one.
