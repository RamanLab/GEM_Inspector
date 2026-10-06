"""Biomass precursor producibility check.

For every biomass (objective) reaction, each reactant (precursor) is tested
on its own: a temporary demand reaction drains just that metabolite, the
biomass reaction itself is switched off so it can't compete, and the maximum
demand flux is found. A precursor that cannot be produced at all means the
model cannot grow, no matter what the optimizer does elsewhere.

Each precursor is tested twice: under the model's current bounds/diet, and
with every exchange opened up (uptake allowed). "Producible only when
exchanges are open" points to a missing nutrient in the diet; "not
producible even then" points to a gap inside the network.

Everything runs inside `with model:` blocks, so the cached model is never
changed.
"""
from cobra import Reaction
from cobra.util import linear_reaction_coefficients

from diagnostics.solver_utils import run_with_exact_solver

EPS = 1e-6
TEST_ID = "__precursor_test__"


def _are_partners(met, prod, biomass_rxn):
    for rxn in met.reactions:
        if rxn.boundary or rxn is biomass_rxn or prod not in rxn.metabolites:
            continue
        if rxn.metabolites[met] * rxn.metabolites[prod] < 0:
            return True
    return False


def _max_production(model, biomass_rxn, met, open_exchanges, recycle=None):
    with model:
        biomass_rxn.bounds = (0, 0)
        if open_exchanges:
            for ex in model.exchanges:
                ex.lower_bound = min(ex.lower_bound, -1000)
        test = Reaction(TEST_ID)
        test.bounds = (0, 1000)
        model.add_reactions([test])
        test.add_metabolites({met: -1})
        if recycle:
            # Cofactors and energy carriers (ATP, NAD(P)H, acetyl-CoA) are only converted
            # to a paired form by biomass (ATP -> ADP, NADPH -> NADP+ ...). Draining them
            # alone would demand de novo synthesis of the whole pool (a conserved moiety),
            # which is not what biomass does, so the partner metabolite(s) are released
            # back into the network in this variant of the test.
            for prod in recycle:
                test.add_metabolites({prod: 1})
        model.objective = test
        value = model.slim_optimize(error_value=0.0)
    return 0.0 if value is None or value != value else float(value)


def _producers_consumers(met):
    prod = cons = 0
    for rxn in met.reactions:
        coef = rxn.metabolites[met]
        if rxn.boundary:
            continue
        can_fwd, can_rev = rxn.upper_bound > 0, rxn.lower_bound < 0
        if (coef > 0 and can_fwd) or (coef < 0 and can_rev):
            prod += 1
        if (coef < 0 and can_fwd) or (coef > 0 and can_rev):
            cons += 1
    return prod, cons


def _hint(current_ok, open_ok, producers, recycled_ok=False):
    if current_ok:
        return ""
    if recycled_ok:
        return ("Not producible on its own, but fine when the by-products biomass releases (e.g. ADP, Pi) are "
                "recycled: typical for a cofactor or energy carrier that biomass only converts to a paired form.")
    if open_ok:
        return ("Producible only when all exchanges are open: a nutrient it is made from is missing from the current "
                "diet/medium. Try the Minimal Medium tab or a richer diet.")
    if producers == 0:
        return ("No reaction in the model can produce this metabolite. Add a biosynthesis reaction or a "
                "transport/exchange for it.")
    return ("Reactions exist that could make it, but none can carry flux even with every exchange open: a gap "
            "upstream (a missing enzyme/reaction, a blocked step, or a missing cofactor). Check Network Gaps and "
            "trace the pathway with the Pathway Tracer.")


def compute_biomass_precursor_report(model):
    try:
        objective = [(r, c) for r, c in linear_reaction_coefficients(model).items()]
    except Exception:
        objective = []
    if not objective:
        return {"error": "The model has no objective (biomass) reaction set."}

    def work():
        out = []
        for rxn, _ in objective:
            precursors = []
            for met, coef in sorted(rxn.metabolites.items(), key=lambda kv: kv[0].id):
                if coef >= 0:
                    continue
                cur = _max_production(model, rxn, met, False)
                opn = _max_production(model, rxn, met, True)
                producers, consumers = _producers_consumers(met)
                cur_ok, open_ok = cur > EPS, opn > EPS
                rec_ok = False
                if not cur_ok and not open_ok:
                    partners = [p for p, c in rxn.metabolites.items()
                                if c > 0 and p is not met and _are_partners(met, p, rxn)]
                    candidates = ([partners] if len(partners) > 1 else []) + [[p] for p in partners]
                    rec_ok = any(_max_production(model, rxn, met, False, recycle=c) > EPS for c in candidates)
                precursors.append({
                    "id": met.id, "name": met.name or "", "compartment": met.compartment,
                    "coefficient": coef,
                    "current": {"producible": cur_ok, "max_flux": cur},
                    "open": {"producible": open_ok, "max_flux": opn},
                    "producers": producers, "consumers": consumers,
                    "verdict": "ok" if cur_ok else ("diet" if open_ok else ("recycled" if rec_ok else "gap")),
                    "hint": _hint(cur_ok, open_ok, producers, rec_ok),
                })
            counts = {"ok": sum(p["verdict"] == "ok" for p in precursors),
                      "diet": sum(p["verdict"] == "diet" for p in precursors),
                      "recycled": sum(p["verdict"] == "recycled" for p in precursors),
                      "gap": sum(p["verdict"] == "gap" for p in precursors)}
            out.append({"id": rxn.id, "name": rxn.name or "", "precursors": precursors, "counts": counts})
        return out

    return {"biomass_reactions": run_with_exact_solver(model, work)}
