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
    data_version: str,
) -> CacheKey:
    if not _SAFE_MODULE_ID.fullmatch(module_id):
        raise ValueError('module_id must contain only lowercase letters, digits, and underscores.')
    material = json.dumps(
        {
            'endpoint': endpoint,
            'params': params,
            'data_version': data_version,
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
