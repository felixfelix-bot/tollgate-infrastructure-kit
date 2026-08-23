"""Tollgate DM auto-issuance service (quote-handoff mode).

Receives NIP-59 gift-wrapped DMs of the form ``ecash <amount>`` from
whitelisted npubs, requests a Cashu mint bolt11 quote, marks it PAID via the
cdk-mintd gRPC ``UpdateNut04Quote`` RPC, verifies the state on the public REST
endpoint, and DMs the resulting ``quote_id`` back to the sender (also
gift-wrapped). The service never touches Cashu secrets, blinded messages, or
tokens: handing off the paid quote_id is the entire issuance surface.
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
