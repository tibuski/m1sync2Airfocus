"""
Models package for JIRA to Airfocus integration.

This package contains data model classes for handling JIRA and Airfocus items
with proper encapsulation, validation, and type safety.
"""

from .jira_item import JiraItem, JiraStatus, JiraAssignee, JiraAttachment
from .airfocus_item import AirfocusItem
from .utils import (
    get_airfocus_field_id,
    get_airfocus_status_id,
    get_mapped_status_id,
    get_airfocus_field_option_id,
)
from .azure_devops import AzureCliConfig


__all__ = [
    "JiraItem",
    "JiraStatus",
    "JiraAssignee",
    "JiraAttachment",
    "AirfocusItem",
    "get_airfocus_field_id",
    "get_airfocus_status_id",
    "get_mapped_status_id",
    "get_airfocus_field_option_id",
    "AzureCliConfig",
]
