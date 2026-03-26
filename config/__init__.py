"""Configuration loading and validation module."""

import os
from importlib import import_module
from typing import List, Any, Dict

from exceptions import ConfigurationError


def _load_constants_module() -> Any:
    """Load the local `constants.py` module or raise a configuration error."""
    try:
        return import_module("constants")
    except ModuleNotFoundError as exc:
        raise ConfigurationError(
            "'constants.py' not found. Copy 'constants.py.example' to 'constants.py' and fill in your settings."
        ) from exc


constants = _load_constants_module()


def _get_env_override(name: str, default: Any) -> Any:
    """Return an environment override when present, else the provided default."""
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def get_config() -> Any:
    """Return the config object with environment overrides applied."""
    sensitive_fields = [
        "JIRA_PAT",
        "AIRFOCUS_API_KEY",
        "AZURE_TENANT_ID",
        "AZURE_DEVOPS_RESOURCE",
        "AZURE_DEVOPS_URL",
        "JIRA_REST_URL",
        "JIRA_PROJECT_KEY",
        "AIRFOCUS_REST_URL",
        "AIRFOCUS_WORKSPACE_ID",
        "AZURE_DEVOPS_WORK_ITEM_TYPE",
    ]

    for field_name in sensitive_fields:
        current_value = getattr(constants, field_name, None)
        override_value = _get_env_override(field_name, current_value)
        setattr(constants, field_name, override_value)

    return constants


def validate_config(sync_mode: str = None) -> List[str]:
    """
    Validate configuration constants at startup.

    Args:
        sync_mode: Either "jira" or "azure-devops". If None, validates all.

    Returns:
        List of validation error messages (empty if all valid)
    """
    errors = []
    active_config = get_config()

    if not active_config.AIRFOCUS_REST_URL or not active_config.AIRFOCUS_REST_URL.startswith(
        "http"
    ):
        errors.append("AIRFOCUS_REST_URL must be a valid URL")

    if (
        not active_config.AIRFOCUS_WORKSPACE_ID
        or not active_config.AIRFOCUS_WORKSPACE_ID.strip()
    ):
        errors.append("AIRFOCUS_WORKSPACE_ID is required")

    placeholder_af = "your-airfocus-api-key-here"
    if (
        not active_config.AIRFOCUS_API_KEY
        or active_config.AIRFOCUS_API_KEY == placeholder_af
    ):
        errors.append("AIRFOCUS_API_KEY is not set (found placeholder value)")

    if sync_mode == "jira" or sync_mode is None:
        if not active_config.JIRA_REST_URL or not active_config.JIRA_REST_URL.startswith(
            "http"
        ):
            errors.append("JIRA_REST_URL must be a valid URL")

        if not active_config.JIRA_PROJECT_KEY or not active_config.JIRA_PROJECT_KEY.strip():
            errors.append("JIRA_PROJECT_KEY is required")

        placeholder_pat = "your-jira-personal-access-token-here"
        if not active_config.JIRA_PAT or active_config.JIRA_PAT == placeholder_pat:
            errors.append("JIRA_PAT is not set (found placeholder value)")

    if sync_mode == "azure-devops" or sync_mode is None:
        if not hasattr(active_config, "AZURE_DEVOPS_URL") or not active_config.AZURE_DEVOPS_URL:
            if sync_mode == "azure-devops" or sync_mode is None:
                errors.append("AZURE_DEVOPS_URL is required")

        if (
            not hasattr(active_config, "AZURE_DEVOPS_WORK_ITEM_TYPE")
            or not active_config.AZURE_DEVOPS_WORK_ITEM_TYPE
        ):
            if sync_mode == "azure-devops" or sync_mode is None:
                errors.append("AZURE_DEVOPS_WORK_ITEM_TYPE is required")

    if active_config.TEAM_FIELD:
        placeholder_team_field = "YOUR_TEAM_FIELD_NAME"
        for field_name in active_config.TEAM_FIELD.keys():
            if field_name == placeholder_team_field:
                errors.append(
                    f"TEAM_FIELD has placeholder value '{field_name}'. "
                    "Either set it to an empty dict (TEAM_FIELD = {{}}) or configure an existing Airfocus team field."
                )
                break

    return errors


def get_jira_headers() -> Dict[str, str]:
    """Get headers for JIRA API requests."""
    active_config = get_config()
    return {
        "Authorization": f"Bearer {active_config.JIRA_PAT}",
        "Content-Type": "application/json",
    }


def get_airfocus_headers() -> Dict[str, str]:
    """Get headers for Airfocus API requests."""
    active_config = get_config()
    return {
        "Authorization": f"Bearer {active_config.AIRFOCUS_API_KEY}",
        "Content-Type": "application/vnd.airfocus.markdown+json",
    }


def get_azure_devops_headers(token: str) -> Dict[str, str]:
    """Get headers for Azure DevOps API requests."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json; api-version=7.0",
    }
