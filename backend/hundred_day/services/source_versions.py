"""Public source versions consumed by this module.

Re-exported from ``core`` so all three post-close modules resolve the industry
mapping identically; business modules must not import each other
(``db_router`` / the isolation tests enforce it), but ``core`` is the shared
layer they are all allowed to depend on.
"""

from core.services.industry_snapshot import (  # noqa: F401
    INDUSTRY_SNAPSHOT_DATASET,
    CompleteIndustrySnapshotUnavailable,
    get_complete_industry_snapshot_version,
)
