"""Per-model memo: keeps the result of an analysis on the model object itself.

Cached models (core.shared.MODEL_CACHE) keep the bounds they were uploaded
with, so an analysis computed once is valid for every later request on that
model: a tab, a generated report and the model report all share one run.
The memo lives and dies with the model object, so it is dropped when the
model expires from the cache. Do not use it while the model is inside a
`with model:` context (bounds may be changed there).
"""


def remember(model, key, compute, cache_if=None):
    """Return the stored result for `key`, computing it on first use.

    `cache_if(result)` can veto storing (used to avoid keeping error results).
    """
    store = model.__dict__.setdefault("_gi_memo", {})
    if key in store:
        return store[key]
    result = compute()
    if cache_if is None or cache_if(result):
        store[key] = result
    return result


def recall(model, key, default=None):
    return model.__dict__.get("_gi_memo", {}).get(key, default)


def store_value(model, key, value):
    model.__dict__.setdefault("_gi_memo", {})[key] = value


def not_error(result):
    return not (isinstance(result, dict) and "error" in result)
