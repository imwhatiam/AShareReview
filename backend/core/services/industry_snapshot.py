"""Resolve the current complete public industry-mapping version.

The industry mapping is a *separate* dataset from the daily prices, and every
post-close module stores one industry snapshot per stock in each of its result
rows. Tracking only the daily-price version means a re-run of the industry
mapping alone can never be detected: the stored industries stay behind while the
response keeps claiming it is current. All three modules therefore depend on
this one lookup, and a business module re-exports it rather than copying it
(see e.g. ``hundred_day.services.source_versions``).
"""

from core.models import DataVersion

INDUSTRY_SNAPSHOT_DATASET = 'industry_snapshot'


class CompleteIndustrySnapshotUnavailable(LookupError):
    """Raised when no complete Kaipanla industry mapping has been published."""


def get_complete_industry_snapshot_version() -> str:
    version = (
        DataVersion.objects.filter(
            dataset_key=INDUSTRY_SNAPSHOT_DATASET,
            status=DataVersion.Status.COMPLETE,
        )
        .order_by('-last_success_at', '-started_at')
        .first()
    )
    if version is None:
        raise CompleteIndustrySnapshotUnavailable(
            'No complete Kaipanla industry snapshot is available.'
        )
    return version.version
