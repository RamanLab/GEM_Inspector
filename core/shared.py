"""Model upload/caching and small generic helpers shared across sections."""
import math
import shutil
import tempfile
import threading
import time
from pathlib import Path

from cobra.io import load_json_model, load_matlab_model, load_yaml_model, read_sbml_model
from cobra.util import linear_reaction_coefficients

ALLOWED = {".xml", ".sbml", ".json", ".yml", ".yaml", ".mat", ".gz", ".zip", ".bz2"}

# In-memory cache for uploaded models: model_id -> (model, last_touched_ts).
# Keeps a model available across requests (KO analysis, exchange debugging,
# pathway tracing, ...) without re-uploading, and evicts it after
# MODEL_TTL_SECONDS of inactivity so the cache doesn't grow unbounded.
MODEL_CACHE = {}
MODEL_TTL_SECONDS = 600  # 10 minutes

# The file exactly as uploaded, kept on disk next to the cached model:
# model_id -> path. MEMOTE is run on this (the cached model has the chosen
# diet applied, which would change MEMOTE's results). Removed when the model
# expires from MODEL_CACHE.
ORIGINAL_FILES = {}

# Callables(model_id) run when a cached model expires (e.g. cancel a running
# MEMOTE job). Modules register themselves here to avoid circular imports.
EXPIRY_HOOKS = []


def store_original_file(model_id, src_path):
    """Copy an uploaded model file into a private temp dir that outlives the
    request, and remember it under model_id. Returns the new path."""
    folder = Path(tempfile.mkdtemp(prefix="gem_inspector_orig_"))
    dest = folder / Path(src_path).name
    shutil.copy2(src_path, dest)
    ORIGINAL_FILES[model_id] = dest
    return dest


def drop_original_file(model_id):
    path = ORIGINAL_FILES.pop(model_id, None)
    if path is not None:
        shutil.rmtree(Path(path).parent, ignore_errors=True)


def _is_busy(model_id):
    """True while a registered module (MEMOTE) is still using this model."""
    for hook in BUSY_CHECKS:
        try:
            if hook(model_id):
                return True
        except Exception:
            pass
    return False


# Callables(model_id) -> bool; True keeps the model alive past its TTL.
BUSY_CHECKS = []


def start_model_cache_cleanup():
    """Start the background thread that periodically evicts expired cached
    models. Call once, at app startup."""
    def cleanup_old_models():
        while True:
            time.sleep(300)  # check every 5 minutes
            now = time.time()
            expired = [mid for mid, (_, ts) in MODEL_CACHE.items() if now - ts > MODEL_TTL_SECONDS]
            for mid in expired:
                if _is_busy(mid):
                    continue  # a long MEMOTE run is still going
                MODEL_CACHE.pop(mid, None)
                for hook in EXPIRY_HOOKS:
                    try:
                        hook(mid)
                    except Exception:
                        pass
                drop_original_file(mid)

    thread = threading.Thread(target=cleanup_old_models, daemon=True)
    thread.start()
    return thread


def touch_model_cache(model_id):
    """Refresh a cached model's TTL so it survives while the user is still
    working with it (e.g. moving from KO analysis to exchange debugging)."""
    entry = MODEL_CACHE.get(model_id)
    if entry is not None:
        model, _ = entry
        MODEL_CACHE[model_id] = (model, time.time())


def safe_float(value):
    try:
        x = float(value)
        if math.isfinite(x):
            return x
    except (TypeError, ValueError):
        pass
    return None


def clean(value):
    """Recursively coerce a value into something JSON-serializable."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [clean(x) for x in value]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    return str(value)


def subsystem_value(reaction):
    # COBRApy models vary: subsystem may be a string, a list, or absent.
    value = getattr(reaction, "subsystem", None)
    if isinstance(value, (list, tuple, set)):
        return "; ".join(map(str, value))
    return str(value or "")


def load_uploaded_model(path: Path):
    """Load an uploaded model file, picking the reader by extension.

    Uses explicit readers for local files rather than cobra.io.load_model,
    which is intended for remote repository identifiers.
    """
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".json"):
        return load_json_model(str(path))
    if suffixes.endswith(".yml") or suffixes.endswith(".yaml"):
        return load_yaml_model(str(path))
    if suffixes.endswith(".mat"):
        return load_matlab_model(str(path))
    # SBML reader supports .gz/.zip/.bz2 when libSBML was built accordingly.
    return read_sbml_model(str(path))


def wt_solution(model):
    """FBA optimum under the model's own bounds, solved once per cached model."""
    from core.memo import remember
    return remember(model, "wt_solution", model.optimize)


def classify_reactions(model):
    """Classify every reaction once and return {reaction_id: type}.

    Building the exchange/demand/sink id sets a single time and classifying
    every reaction in one pass keeps this O(n); rebuilding those sets per
    reaction would make it O(n^2) for a model with n reactions.
    """
    exchange_ids = {r.id for r in model.exchanges}
    demand_ids = {r.id for r in model.demands}
    sink_ids = {r.id for r in model.sinks}

    types = {}
    for reaction in model.reactions:
        if reaction.id in exchange_ids:
            types[reaction.id] = "exchange"
        elif reaction.id in demand_ids:
            types[reaction.id] = "demand"
        elif reaction.id in sink_ids:
            types[reaction.id] = "sink"
        else:
            # Transport is inherently model-dependent; this heuristic flags
            # reactions whose metabolites span multiple compartments.
            compartments = {m.compartment for m in reaction.metabolites if m.compartment}
            types[reaction.id] = "transport" if len(compartments) > 1 else "internal"
    return types


def find_biomass_reaction(model):
    """Best-effort identification of the biomass reaction.

    The model's linear objective is almost always exactly the biomass
    reaction, so that's checked first (O(1) rather than scanning every
    reaction's id/name). Falls back to a name search over model.reactions
    (never model.exchanges -- a biomass reaction is essentially never an
    exchange) for models where the objective isn't set.
    """
    try:
        coefficients = linear_reaction_coefficients(model)
        if coefficients:
            return next(iter(coefficients)).id
    except Exception:
        pass

    for rxn in model.reactions:
        if "biomass" in rxn.id.lower() or "biomass" in (rxn.name or "").lower():
            return rxn.id
    return None
