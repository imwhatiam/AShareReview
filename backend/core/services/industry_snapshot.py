"""Check that the current Kaipanla industry mapping is stored.

The industry mapping is a *separate* public dataset from the daily prices, and
every post-close module writes one industry snapshot per stock into each of its
result rows. A day whose prices are stored but whose industry mapping is missing
cannot be turned into a result at all — the rows would have to leave
``industries`` empty, which the page renders as "no industry" rather than "not
loaded yet". All three modules therefore share this one check instead of each
testing the table themselves, and a business module re-exports it rather than
copying it (see e.g. ``hundred_day.services.industry_source``).
"""

from core.models import IndustrySnapshot


class CompleteIndustrySnapshotUnavailable(LookupError):
    """Raised when no Kaipanla industry mapping is stored."""


def require_industry_snapshot() -> None:
    if not IndustrySnapshot.objects.exists():
        raise CompleteIndustrySnapshotUnavailable(
            'No Kaipanla industry snapshot is stored.'
        )
