"""Safe serialization and atomic, concurrency-checked writes."""

import copy
import datetime
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

from .errors import BurrError, require

METADATA = {"rationale", "source", "confidence", "as_of", "unit", "tolerance"}
VALUE_KEYS = {"value", "start", "end", "shape", "until", "after", "dist", "mean", "sd",
              "lo", "hi", "low", "high", "applies_to"}
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*\Z")


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int)) or isinstance(key, bool):
            raise ValueError("mapping keys must be strings or years")
        if key in result:
            raise ValueError(f"duplicate YAML key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def json_text(value):
    return json.dumps(plain(value), sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")) + "\n"


def yaml_text(value):
    return yaml.safe_dump(plain(value), sort_keys=False, allow_unicode=True, width=100)


def read_yaml(path):
    try:
        result = plain(yaml.load(Path(path).read_text(), Loader=UniqueLoader))
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as exc:
        raise BurrError("usage_error", f"cannot read YAML: {exc}", file=path, exit_code=2) from exc
    require(isinstance(result, dict), "usage_error", "expected a YAML mapping", file=path, exit_code=2)
    return result


def identifier(name):
    require(isinstance(name, str) and IDENTIFIER.fullmatch(name), "patch_conflict",
            f"invalid identifier {name!r}")
    return name


def merge(base, patch):
    if not isinstance(patch, dict) or (VALUE_KEYS | METADATA) & patch.keys():
        return copy.deepcopy(patch)
    if not isinstance(base, dict) or (VALUE_KEYS | METADATA) & base.keys():
        return copy.deepcopy(patch)
    result = copy.deepcopy(base)
    for key, value in patch.items():
        result[key] = merge(result.get(key), value)
    return result


def digest(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def atomic_write(path, content, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise BurrError("patch_conflict", f"{path.name} already exists", file=path) from exc
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def workspace_lock(root):
    # Lock the existing pin, leaving no lock-file mutation behind on failure.
    import fcntl
    with (Path(root) / "burr.lock").open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
