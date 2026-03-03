"""
Shared utility functions for JIRA to Airfocus integration.
"""

import json
import os
from typing import Dict, List, Optional
from loguru import logger

import constants


def get_airfocus_field_id(field_name: str) -> Optional[str]:
    """
    Get a specific field ID from the saved Airfocus fields data.

    Args:
        field_name (str): The name of the field to retrieve the ID for.

    Returns:
        str: The field ID for the specified field, or None if not found.
    """
    try:
        filepath = f"{constants.DATA_DIR}/airfocus_fields.json"

        if not os.path.exists(filepath):
            logger.warning(
                "Airfocus fields file not found at {}. Run get_airfocus_field_data() first.",
                filepath,
            )
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            field_data = json.load(f)

        field_mapping = field_data.get("field_mapping", {})
        field_id = field_mapping.get(field_name)

        if field_id:
            logger.debug("Found {} field ID: {}", field_name, field_id)
            return field_id
        else:
            logger.warning("{} field not found in saved field mapping", field_name)
            logger.debug("Available fields: {}", list(field_mapping.keys()))
            return None

    except Exception as e:
        logger.error("Exception occurred while reading field data: {}", e)
        return None


def get_airfocus_status_id(status_name: str) -> Optional[str]:
    """
    Get a specific status ID from the saved Airfocus fields data.

    Args:
        status_name (str): The name of the status to retrieve the ID for.

    Returns:
        str: The status ID for the specified status, or None if not found.
    """
    try:
        filepath = f"{constants.DATA_DIR}/airfocus_fields.json"

        if not os.path.exists(filepath):
            logger.warning(
                "Airfocus fields file not found at {}. Run get_airfocus_field_data() first.",
                filepath,
            )
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            field_data = json.load(f)

        status_mapping = field_data.get("status_mapping", {})
        status_id = status_mapping.get(status_name)

        if status_id:
            logger.debug("Found {} status ID: {}", status_name, status_id)
            return status_id
        else:
            logger.warning("{} status not found in saved status mapping", status_name)
            logger.debug("Available statuses: {}", list(status_mapping.keys()))
            return None

    except Exception as e:
        logger.error("Exception occurred while reading status data: {}", e)
        return None


def get_airfocus_field_option_id(field_name: str, option_name: str) -> Optional[str]:
    """
    Get a specific option ID from a select field in the saved Airfocus fields data.

    Args:
        field_name (str): The name of the field to search in.
        option_name (str): The name of the option to retrieve the ID for.

    Returns:
        str: The option ID for the specified option, or None if not found.
    """
    try:
        filepath = f"{constants.DATA_DIR}/airfocus_fields.json"

        if not os.path.exists(filepath):
            logger.warning(
                "Airfocus fields file not found at {}. Run get_airfocus_field_data() first.",
                filepath,
            )
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            field_data = json.load(f)

        fields = field_data.get("fields", [])
        for field in fields:
            if field.get("name") == field_name:
                if field.get("typeId") == "select":
                    options = field.get("settings", {}).get("options", [])
                    for option in options:
                        if option.get("name") == option_name:
                            return option.get("id")

                    logger.warning(
                        "Option '{}' not found in select field '{}'",
                        option_name,
                        field_name,
                    )
                    return None
                else:
                    logger.error(
                        "Field '{}' is not a select field (type: {})",
                        field_name,
                        field.get("typeId"),
                    )
                    return None

        logger.warning("Field '{}' not found in saved field data", field_name)
        return None

    except Exception as e:
        logger.error("Exception occurred while reading field option data: {}", e)
        return None


def get_mapped_status_id(
    source_status_name: str,
    source_key: str,
    mapping: Optional[Dict[str, List[str]]] = None,
) -> Optional[str]:
    """
    Get Airfocus status ID from source status name using mappings and fallbacks.

    Args:
        source_status_name (str): Source status name to map (JIRA or Azure DevOps)
        source_key (str): Source issue key for logging purposes
        mapping (dict): Status mapping dict. Defaults to JIRA_TO_AIRFOCUS_STATUS_MAPPING

    Returns:
        str: Airfocus status ID, or None if no suitable status found
    """
    if not source_status_name:
        return None

    if mapping is None:
        mapping = constants.JIRA_TO_AIRFOCUS_STATUS_MAPPING

    for (
        airfocus_status,
        source_variants,
    ) in mapping.items():
        if source_status_name in source_variants:
            status_id = get_airfocus_status_id(airfocus_status)
            if status_id:
                logger.info(
                    "Mapped status '{}' to Airfocus status '{}'",
                    source_status_name,
                    airfocus_status,
                )
                return status_id

    logger.warning(
        "Status '{}' not found in status mappings. Falling back to 'Draft' status.",
        source_status_name,
    )
    status_id = get_airfocus_status_id("Draft")

    if not status_id:
        try:
            filepath = f"{constants.DATA_DIR}/airfocus_fields.json"
            with open(filepath, "r", encoding="utf-8") as f:
                field_data = json.load(f)

            statuses = field_data.get("statuses", [])
            for status in statuses:
                if status.get("default", False):
                    status_id = status.get("id")
                    logger.info(
                        "Using default status '{}' for JIRA issue {}",
                        status.get("name"),
                        source_key,
                    )
                    return status_id

            if statuses:
                status_id = statuses[0].get("id")
                logger.warning(
                    "No suitable status found for source status '{}', using first available status '{}' for issue {}",
                    source_status_name,
                    statuses[0].get("name"),
                    source_key,
                )
                return status_id

        except Exception as e:
            logger.error("Failed to get default status: {}", e)

    if not status_id:
        logger.error(
            "Could not determine status ID for JIRA issue {}. Status will be left empty.",
            source_key,
        )

    return status_id


# =============================================================================
# Azure DevOps helpers
# =============================================================================


def get_azure_devops_token() -> Optional[str]:
    """Get an Azure DevOps access token using Azure CLI device-code login.

    Requires configuration in constants.py:
      - AZURE_DEVOPS_RESOURCE
    Optionally:
      - AZURE_CLI_PYTHON_EXE
      - AZURE_CLI_BAT_PATH

    Returns:
      Access token string or None.
    """
    try:
        from .azure_devops import AzureCliConfig, get_devops_token_via_azure_cli

        devops_resource = getattr(constants, "AZURE_DEVOPS_RESOURCE", "")
        if not devops_resource:
            logger.error("AZURE_DEVOPS_RESOURCE is not set in constants.py")
            return None

        config = AzureCliConfig(
            devops_resource=devops_resource,
            az_cli_python_exe=getattr(constants, "AZURE_CLI_PYTHON_EXE", None),
            az_cli_bat_path=getattr(constants, "AZURE_CLI_BAT_PATH", None),
        )

        token = get_devops_token_via_azure_cli(config)
        if not token:
            logger.error("Failed to obtain Azure DevOps token via Azure CLI")
        return token
    except Exception as e:
        logger.error("Failed to get Azure DevOps token: {}", e)
        return None
