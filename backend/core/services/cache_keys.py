"""Stable, filesystem-safe cache-key construction."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping


_SAFE_MODULE_ID = re.compile(r'^[a-z0-9_]+$')


@dataclass(frozen=True)
class CacheKey:
    module_id: str
    filename: str


def build_cache_key(
    module_id: str,
    endpoint: str,
    params: Mapping[str, object],
    cache_identity: str,
) -> CacheKey:
    """Key one cached payload by module, endpoint, params and payload identity.

    ``cache_identity`` is whatever makes the underlying rows "these rows and not
    another set": the moment the served result row was written for the derived
    modules, the newest collected slot for Kaipanla. It is part of the key so a
    cached body can never outlive the data it was built from.
    """
    if not _SAFE_MODULE_ID.fullmatch(module_id):
        raise ValueError('module_id must contain only lowercase letters, digits, and underscores.')
    material = json.dumps(
        {
            'endpoint': endpoint,
            'params': params,
            'cache_identity': cache_identity,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        default=str,
    )
    return CacheKey(
        module_id=module_id,
        filename=f'{hashlib.sha256(material.encode("utf-8")).hexdigest()}.json',
    )
