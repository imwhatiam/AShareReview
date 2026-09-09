"""Resolve the current complete public industry-mapping version."""

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
