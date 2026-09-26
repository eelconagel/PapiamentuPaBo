"""Server side of progress sync: validate the browser's progress blob and merge two of them.

Rules: if the browser saved on top of the latest server revision, its state wins as-is
(so spending XP on a hint sticks). Otherwise two devices diverged and we merge, never
losing progress: highest XP, union of unlocked lists/lesson steps/scenarios, and per word
the highest count.

Newer fields (like "nieuws") are kept from the stored copy when an older browser sends a
state without them, so a tab that still runs stale JavaScript can't wipe them.
"""
import json

MAX_BYTES = 256 * 1024
_LIMITS = {"woorden": 5000, "lessen": 500, "scenarios": 500, "nieuws": 1000, "lijsten": 200}
# Completion maps: id -> ISO timestamp of the first time it was finished.
_DONE_MAPS = ("scenarios", "nieuws")
# Fields (of any shape) that a browser running stale JavaScript might not send at all —
# keep the stored value in that case instead of letting sanitize() reset it to empty/zero.
_PROTECT_IF_MISSING = _DONE_MAPS + ("xpEarned",)


def _int(value, lo=0, hi=10_000_000):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return lo


def _key(k) -> str | None:
    k = str(k)
    return k if 0 < len(k) <= 40 else None


def sanitize(state) -> dict:
    """Keep only known fields with sane types and sizes. Theme stays per device."""
    if not isinstance(state, dict):
        state = {}
    out = {"version": 1, "profile": None, "xp": _int(state.get("xp")), "xpEarned": _int(state.get("xpEarned")),
           "woorden": {}, "lijsten": [], "lessen": {}, "scenarios": {}, "nieuws": {}}

    profile = state.get("profile")
    if isinstance(profile, dict) and isinstance(profile.get("name"), str) and profile["name"].strip():
        out["profile"] = {"name": profile["name"].strip()[:60]}

    woorden = state.get("woorden") if isinstance(state.get("woorden"), dict) else {}
    for k, v in list(woorden.items())[:_LIMITS["woorden"]]:
        if (k := _key(k)) and isinstance(v, dict):
            out["woorden"][k] = {"correct_count": _int(v.get("correct_count"), hi=1000),
                                 "is_mastered": bool(v.get("is_mastered"))}

    lijsten = state.get("lijsten") if isinstance(state.get("lijsten"), list) else []
    out["lijsten"] = sorted({_int(x, lo=1, hi=10_000) for x in lijsten[:_LIMITS["lijsten"]]} | {1})

    lessen = state.get("lessen") if isinstance(state.get("lessen"), dict) else {}
    for k, steps in list(lessen.items())[:_LIMITS["lessen"]]:
        if (k := _key(k)) and isinstance(steps, list):
            clean = sorted({s for s in (_int(x, lo=0, hi=4) for x in steps[:10]) if s >= 1})
            if clean:
                out["lessen"][k] = clean

    for field in _DONE_MAPS:
        done = state.get(field) if isinstance(state.get(field), dict) else {}
        for k, when in list(done.items())[:_LIMITS[field]]:
            if (k := _key(k)) and when:
                out[field][k] = str(when)[:40]
    return out


def merge(a: dict, b: dict) -> dict:
    """Combine two sanitized states without losing progress from either."""
    out = sanitize({})
    out["profile"] = a["profile"] or b["profile"]
    out["xp"] = max(a["xp"], b["xp"])
    out["xpEarned"] = max(a["xpEarned"], b["xpEarned"])
    for k in a["woorden"].keys() | b["woorden"].keys():
        wa, wb = a["woorden"].get(k, {}), b["woorden"].get(k, {})
        out["woorden"][k] = {
            "correct_count": max(wa.get("correct_count", 0), wb.get("correct_count", 0)),
            "is_mastered": wa.get("is_mastered", False) or wb.get("is_mastered", False),
        }
    out["lijsten"] = sorted(set(a["lijsten"]) | set(b["lijsten"]))
    for k in a["lessen"].keys() | b["lessen"].keys():
        out["lessen"][k] = sorted(set(a["lessen"].get(k, [])) | set(b["lessen"].get(k, [])))
    for field in _DONE_MAPS:
        for k in a[field].keys() | b[field].keys():
            out[field][k] = min(v for v in (a[field].get(k), b[field].get(k)) if v)
    return out


def resolve(stored_json: str | None, stored_rev: int | None, incoming, base_rev, replace: bool):
    """Return (new_state, new_rev) for an incoming save."""
    missing = [f for f in _PROTECT_IF_MISSING if not (isinstance(incoming, dict) and f in incoming)]
    incoming = sanitize(incoming)
    stored = sanitize(json.loads(stored_json)) if stored_json else None
    if stored is not None:
        for field in missing:
            incoming[field] = stored[field]
    if stored is None:
        new = incoming
    elif replace or base_rev == stored_rev:
        new = incoming
        new["profile"] = new["profile"] or stored["profile"]
    else:
        new = merge(stored, incoming)
    return new, (stored_rev or 0) + 1
