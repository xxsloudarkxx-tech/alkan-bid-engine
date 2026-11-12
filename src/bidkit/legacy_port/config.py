"""
Legacy compatibility layer for ProjectConfig.

DEPRECATED: This module provides backward compatibility for code that still uses
the old ProjectConfig API. New code should import from project_schema instead.

This will be removed in a future version once all code is migrated.
"""

from __future__ import annotations

from pathlib import Path

# Re-export new schema components for backward compatibility
from .project_schema import (
    ProjectConfig,
    discover_projects,
    find_project_by_id,
    find_workspace_root,
)

# Legacy alias
find_project_root = find_workspace_root


__all__ = [
    "ProjectConfig",
    "find_project_root",
    "find_workspace_root",
    "find_project_by_id",
    "discover_projects",
]
