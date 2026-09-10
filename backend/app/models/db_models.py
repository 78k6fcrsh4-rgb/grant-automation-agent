"""Deprecated shim.

The ORM moved to app.models.core_models when the `core` schema became
shared with Perch (v2.8.0). Import from there. This module re-exports
Tenant and User so existing imports keep working for one release.
"""
from app.models.core_models import Tenant, User  # noqa: F401

__all__ = ["Tenant", "User"]
