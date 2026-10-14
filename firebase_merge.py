"""Three-way Firebase merge. No network, credentials or local writes in this module."""
import copy
import json
from collections import Counter

DB_KEYS = ("devices", "portal", "mgmt", "names", "history")
SHARED_SETTINGS = ("mac_access_profile", "default_mac_group", "default_portal_group",
                   "known_groups", "portal_domain", "withdrawn_lines", "mgmt_iface", "mgmt_acl")
META_KEY = "_firebase_sync_v2"
_MISSING = object()


def database(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid shared database; synchronization stopped to protect local data.")
    result = {}
    for key in DB_KEYS:
        default = [] if key == "history" else {}
        value = data.get(key, default)
        if not isinstance(value, type(default)):
            raise ValueError("Invalid shared database section: " + key)
        records = value if key == "history" else value.values()
        if not all(isinstance(record, dict) for record in records):
            raise ValueError("Invalid shared database record: " + key)
        result[key] = copy.deepcopy(value)
    return result


def snapshot(data, settings):
    return {"db": database(data), "settings": {k: copy.deepcopy(settings[k])
            for k in SHARED_SETTINGS if k in settings}}


def validate(state):
    if not isinstance(state, dict) or "db" not in state:
        raise ValueError("Invalid Firebase state; no data was replaced.")
    if not isinstance(state["db"], dict) or any(k not in state["db"] for k in DB_KEYS):
        raise ValueError("Incomplete Firebase database; no data was replaced.")
    if not isinstance(state.get("settings", {}), dict):
        raise ValueError("Invalid Firebase settings.")
    if state.get("schema_version", 2) != 2:
        raise ValueError("Unsupported Firebase schema; update this application first.")
    result = snapshot(state["db"], state.get("settings", {}))
    deleted = state.get("deleted", [])
    if not isinstance(deleted, list) or not all(isinstance(p, str) for p in deleted):
        raise ValueError("Invalid Firebase deletion markers.")
    result["deleted"] = sorted(set(deleted))
    return result


def _copy(value):
    return value if value is _MISSING else copy.deepcopy(value)


def _merge(base, local, remote, conflicts, path, deleted, bootstrap):
    marker = json.dumps(path, separators=(",", ":"))
    if bootstrap and marker in deleted and remote is _MISSING:
        if local is not _MISSING:
            conflicts.append(path)
        return _MISSING
    value = _choose(base, local, remote, conflicts, path, deleted, bootstrap)
    if value is _MISSING:
        deleted.add(marker)
    else:
        deleted.discard(marker)
    return value


def _choose(base, local, remote, conflicts, path, deleted, bootstrap):
    # Recurse through maps even if an entire map is unchanged. This records
    # field-level deletion markers for fresh/stale installations as well.
    if isinstance(local, dict) and isinstance(remote, dict):
        prior = base if isinstance(base, dict) else {}
        result = {}
        for key in sorted(set(prior) | set(local) | set(remote)):
            value = _merge(prior.get(key, _MISSING), local.get(key, _MISSING),
                           remote.get(key, _MISSING), conflicts, path + [key], deleted, bootstrap)
            if value is not _MISSING:
                result[key] = value
        return result
    if local == remote:
        return _copy(local)
    if local == base:
        return _copy(remote)
    if remote == base:
        return _copy(local)
    if base is _MISSING and local is _MISSING:
        return _copy(remote)
    if base is _MISSING and remote is _MISSING:
        return _copy(local)
    conflicts.append(path)
    # The cloud's committed value wins a genuine concurrent edit. Both complete
    # input snapshots are archived before commit, including deletion conflicts.
    return _copy(remote)


def _history(local, remote):
    # Multiset union preserves repeated legacy events without duplicating shared
    # events on every poll. New events carry stable IDs assigned by LocalDB.log.
    encode = lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    seen, target = Counter(), Counter(map(encode, local)) | Counter(map(encode, remote))
    result = []
    for item in remote + local:
        key = encode(item)
        if seen[key] < target[key]:
            result.append(copy.deepcopy(item))
            seen[key] += 1
    # Older events remain in immutable cloud/local revision backups.
    result.sort(key=lambda item: str(item.get("when", "")) if isinstance(item, dict) else "")
    return result[-2000:]


def merge(base, local, remote):
    """Merge only edits relative to this device's durable last acknowledged copy."""
    local = validate(local)
    remote = validate(remote)
    base = validate(base) if base is not None else None
    conflicts = []
    deleted = set(remote["deleted"])
    result = {"db": {}, "settings": {}}
    for section in DB_KEYS:
        if section == "history":
            result["db"][section] = _history(local["db"][section], remote["db"][section])
            continue
        prior = base["db"][section] if base is not None else {}
        left, right = local["db"][section], remote["db"][section]
        merged = {}
        for key in sorted(set(prior) | set(left) | set(right)):
            marker = json.dumps([section, key], separators=(",", ":"))
            # A stale installation without a baseline cannot resurrect a deletion.
            if base is None and marker in deleted and key not in right:
                if key in left:
                    conflicts.append([section, key])
                continue
            value = _merge(prior.get(key, _MISSING), left.get(key, _MISSING),
                           right.get(key, _MISSING), conflicts, [section, key], deleted, base is None)
            if value is _MISSING:
                deleted.add(marker)
            else:
                merged[key] = value
                deleted.discard(marker)
        result["db"][section] = merged
    result["settings"] = _merge(base["settings"] if base is not None else _MISSING,
                                 local["settings"], remote["settings"], conflicts, ["settings"], deleted, base is None)
    result["deleted"] = sorted(deleted)
    return result, conflicts


def synchronize(transport, local, base=None, attempts=4):
    """Archive all inputs and conditionally commit; safe to retry after any crash."""
    local = validate(local)
    for unused in range(attempts):
        remote = transport.pull()
        version = remote.get("_update_time") if remote else None
        if remote is not None and not version:
            raise ValueError("Firebase returned no revision; unsafe write refused.")
        clean_remote = validate(remote) if remote is not None else snapshot({}, {})
        combined, conflicts = merge(base, local, clean_remote)
        if remote is not None and combined == clean_remote:
            if local != clean_remote:
                transport.archive(local)
            return {"state": combined, "conflicts": conflicts, "saved_at": remote.get("saved_at", "")}
        # Keep the previous cloud version and this device's complete input even
        # when a concurrent edit chooses one field's value over another.
        if remote is not None:
            transport.archive(clean_remote)
        transport.archive(local)
        try:
            saved_at = transport.commit(combined, version)
        except Exception as exc:
            if (getattr(exc, "status_code", None) in (409, 412)
                    or getattr(exc, "status", "") in ("ABORTED", "FAILED_PRECONDITION", "ALREADY_EXISTS")):
                continue
            raise
        return {"state": combined, "conflicts": conflicts, "saved_at": saved_at}
    raise RuntimeError("Firebase is busy with concurrent changes; the local changes remain pending.")
