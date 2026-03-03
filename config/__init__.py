"""
Configuration loading and validation module.

This module provides configuration validation and access utilities.
"""

from typing import List, Any, Dict
from loguru import logger

try:
    import constants
except ModuleNotFoundError:
    print("Error: 'constants.py' not found.")
    print("")
    print("The project requires a 'constants.py' file with your API credentials.")
    print("A template example exists at: constants.py.example")
    print("")
    print("To fix this:")
    print("  1. Copy the example file: cp constants.py.example constants.py")
    print("  2. Edit constants.py and fill in your JIRA and Airfocus credentials")
    print("")
    import sys

    sys.exit(1)


def get_config() -> Any:
    """Return the constants module for configuration access."""
    return constants


def validate_config(sync_mode: str = None) -> List[str]:
    """
    Validate configuration constants at startup.

    Args:
        sync_mode: Either "jira" or "azure-devops". If None, validates all.

    Returns:
        List of validation error messages (empty if all valid)
    """
    from exceptions import ConfigurationError

    errors = []

    if not constants.AIRFOCUS_REST_URL or not constants.AIRFOCUS_REST_URL.startswith(
        "http"
    ):
        errors.append("AIRFOCUS_REST_URL must be a valid URL")

    if (
        not constants.AIRFOCUS_WORKSPACE_ID
        or not constants.AIRFOCUS_WORKSPACE_ID.strip()
    ):
        errors.append("AIRFOCUS_WORKSPACE_ID is required")

    placeholder_af = "your-airfocus-api-key-here"
    if not constants.AIRFOCUS_API_KEY or constants.AIRFOCUS_API_KEY == placeholder_af:
        errors.append("AIRFOCUS_API_KEY is not set (found placeholder value)")

    if sync_mode == "jira" or sync_mode is None:
        if not constants.JIRA_REST_URL or not constants.JIRA_REST_URL.startswith(
            "http"
        ):
            errors.append("JIRA_REST_URL must be a valid URL")

        if not constants.JIRA_PROJECT_KEY or not constants.JIRA_PROJECT_KEY.strip():
            errors.append("JIRA_PROJECT_KEY is required")

        placeholder_pat = "your-jira-personal-access-token-here"
        if not constants.JIRA_PAT or constants.JIRA_PAT == placeholder_pat:
            errors.append("JIRA_PAT is not set (found placeholder value)")

    if sync_mode == "azure-devops" or sync_mode is None:
        if not hasattr(constants, "AZURE_DEVOPS_URL") or not constants.AZURE_DEVOPS_URL:
            if sync_mode == "azure-devops" or sync_mode is None:
                errors.append("AZURE_DEVOPS_URL is required")

        if (
            not hasattr(constants, "AZURE_DEVOPS_WORK_ITEM_TYPE")
            or not constants.AZURE_DEVOPS_WORK_ITEM_TYPE
        ):
            if sync_mode == "azure-devops" or sync_mode is None:
                errors.append("AZURE_DEVOPS_WORK_ITEM_TYPE is required")

    if constants.TEAM_FIELD:
        placeholder_team_field = "YOUR_TEAM_FIELD_NAME"
        for field_name in constants.TEAM_FIELD.keys():
            if field_name == placeholder_team_field:
                errors.append(
                    f"TEAM_FIELD has placeholder value '{field_name}'. "
                    "Either set it to an empty dict (TEAM_FIELD = {{}}) or configure an existing Airfocus team field."
                )
                break

    return errors


def get_jira_headers() -> Dict[str, str]:
    """Get headers for JIRA API requests."""
    return {
        "Authorization": f"Bearer {constants.JIRA_PAT}",
        "Content-Type": "application/json",
    }


def get_airfocus_headers() -> Dict[str, str]:
    """Get headers for Airfocus API requests."""
    return {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/vnd.airfocus.markdown+json",
    }


def get_azure_devops_headers(token: str) -> Dict[str, str]:
    """Get headers for Azure DevOps API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json; api-version=7.0",
    }
