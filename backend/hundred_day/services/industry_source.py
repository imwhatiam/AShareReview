"""The industry mapping this module consumes, and the check that it is present.

Re-exported from ``core`` so all three post-close modules resolve the industry
mapping identically; business modules must not import each other
(``db_router`` / the isolation tests enforce it), but ``core`` is the shared
layer they are all allowed to depend on.
"""

from core.services.industry_snapshot import (  # noqa: F401
    CompleteIndustrySnapshotUnavailable,
    require_industry_snapshot,
)
