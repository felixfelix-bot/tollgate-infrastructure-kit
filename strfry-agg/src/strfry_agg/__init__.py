"""Strfry aggregation relay toolkit.

Provides gated write-policy logic, follow-list reconciliation (grow + shrink
on unfollow), and negentropy-based scraping for a dedicated strfry instance
that mirrors only the events of a root npub's followed set.
"""

__version__ = "0.1.0"
