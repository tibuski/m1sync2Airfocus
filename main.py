"""
JIRA to Airfocus Integration Script

This module provides functionality to fetch data from JIRA projects and sync them with Airfocus.
It handles authentication, data retrieval, and logging for the integration process.
"""

import sys
import os
import argparse
import requests
import json
from datetime import datetime
import urllib3
import glob
from typing import Dict, List, Tuple, Optional, Any

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
    sys.exit(1)

from models import (
    AirfocusItem,
    JiraItem,
)
from models.azure_devops import AzureCliConfig, get_devops_token_via_azure_cli

# Conditionally disable SSL warnings when certificate verification is disabled
if not constants.SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure loguru logging with both file and console output
logger.remove()  # Remove default handler
# File Logging
logger.add(
    constants.LOG_FILE_PATH,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}",
    rotation="10 MB",
    retention="30 days",
)
# Console Logging
logger.add(sys.stderr, level=constants.LOGGING_LEVEL, colorize=True)


# Helper Functions


def validate_constants() -> List[str]:
    """
    Validate configuration constants at startup.

    Returns:
        List of validation error messages (empty if all valid)
    """
    errors = []

    if not constants.JIRA_REST_URL or not constants.JIRA_REST_URL.startswith("http"):
        errors.append("JIRA_REST_URL must be a valid URL")

    if not constants.AIRFOCUS_REST_URL or not constants.AIRFOCUS_REST_URL.startswith(
        "http"
    ):
        errors.append("AIRFOCUS_REST_URL must be a valid URL")

    if not constants.JIRA_PROJECT_KEY or not constants.JIRA_PROJECT_KEY.strip():
        errors.append("JIRA_PROJECT_KEY is required")

    if (
        not constants.AIRFOCUS_WORKSPACE_ID
        or not constants.AIRFOCUS_WORKSPACE_ID.strip()
    ):
        errors.append("AIRFOCUS_WORKSPACE_ID is required")

    placeholder_pat = "your-jira-personal-access-token-here"
    placeholder_af = "your-airfocus-api-key-here"

    if not constants.JIRA_PAT or constants.JIRA_PAT == placeholder_pat:
        errors.append("JIRA_PAT is not set (found placeholder value)")

    if not constants.AIRFOCUS_API_KEY or constants.AIRFOCUS_API_KEY == placeholder_af:
        errors.append("AIRFOCUS_API_KEY is not set (found placeholder value)")

    # Check TEAM_FIELD configuration
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


def validate_api_response(
    response: requests.Response,
    operation_name: str,
    expected_status_codes: Optional[List[int]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Validate API response and return standardized result.

    Args:
        response: requests.Response object
        operation_name (str): Name of the operation for logging
        expected_status_codes (list): List of acceptable status codes

    Returns:
        tuple: (success: bool, data: dict or error_dict)
    """
    # Avoid mutable default argument
    if expected_status_codes is None:
        expected_status_codes = [200]

    if response.status_code in expected_status_codes:
        try:
            data = response.json()
            logger.debug("{} successful. Response: {}", operation_name, data)
            return True, data
        except Exception as e:
            error_msg = f"Failed to parse JSON response for {operation_name}: {str(e)}"
            logger.error(error_msg)
            return False, {"error": error_msg}
    else:
        error_msg = f"{operation_name} failed. Status code: {response.status_code}"
        logger.error(error_msg)
        logger.error("Response: {}", response.text)
        return False, {"error": error_msg, "response": response.text}


def get_jira_project_data(project_key: str) -> Dict[str, Any]:
    """
    Fetch JIRA project data including issues, descriptions, status, and assignees.

    This function queries the JIRA REST API to retrieve all issues for a specified project,
    including their summary, description, status, and assignee information. The data is
    stored in a JSON file in the ./data directory for further processing.

    Args:
        project_key (str): The JIRA project key to fetch data from.

    Returns:
        dict: Complete JSON response containing all project issues if successful,
              or an error dictionary if the request fails.
    """
    all_issues = []
    start_at = 0
    max_results = 100  # Increase batch size for better performance
    total_issues = None

    # Construct API endpoint URL
    url = f"{constants.JIRA_REST_URL}/search"

    # Set up authentication headers
    headers = {
        "Authorization": f"Bearer {constants.JIRA_PAT}",
        "Content-Type": "application/json",
    }

    while True:
        # Define JQL query to fetch specific fields for the project
        # Note: "key" field is included by default and contains the issue key (e.g., PROJ-123)
        # Fetch only Epic issues for the project
        query = {
            "jql": f"project = {project_key} AND issuetype = Epic",
            "fields": [
                "key",
                "summary",
                "description",
                "status",
                "assignee",
                "attachment",
                "updated",
            ],
            "expand": ["names"],
            "startAt": start_at,
            "maxResults": max_results,
        }
        logger.info("Requesting data from endpoint: {}", url)
        logger.info("Using JQL query: {}", query["jql"])
        logger.info("Requesting issues {} to {}", start_at, start_at + max_results - 1)

        try:
            response = requests.post(
                url,
                headers=headers,
                json=query,
                verify=constants.SSL_VERIFY,
                timeout=30,
            )
            logger.info("Received response with status code {}", response.status_code)
            logger.debug("Received response with status code {}", response.json())
        except requests.exceptions.ConnectionError as e:
            error_msg = f"Connection error while fetching data for Jira project {project_key}: {str(e)}"
            logger.error("{}", error_msg)
            return {"error": error_msg}
        except requests.exceptions.Timeout as e:
            error_msg = f"Timeout error while fetching data for Jira project {project_key}: {str(e)}"
            logger.error("{}", error_msg)
            return {"error": error_msg}
        except requests.exceptions.RequestException as e:
            error_msg = f"Request error while fetching data for Jira project {project_key}: {str(e)}"
            logger.error("{}", error_msg)
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Unexpected error while fetching data for Jira project {project_key}: {str(e)}"
            logger.error("{}", error_msg)
            return {"error": error_msg}

        if response.status_code != 200:
            error_msg = f"Failed to fetch data for Jira project {project_key}. Status code: {response.status_code}"
            logger.error("{}", error_msg)
            logger.error("Response: {}", response.text)
            return {"error": f"Failed to fetch data. Status: {response.status_code}"}

        data = response.json()

        # Extract issues from the response
        raw_issues = data.get("issues", [])

        # Extract only the needed fields from each issue
        for issue in raw_issues:
            # Get the issue key (always available)
            issue_key = issue.get("key", "")

            # Extract base URL from JIRA_REST_URL (remove /rest/api/latest)
            base_url = constants.JIRA_REST_URL.replace("/rest/api/latest", "")

            # Create JiraItem from the raw API data
            jira_item = JiraItem.from_jira_api_data(issue, project_key, base_url)

            # Validate the item
            validation_errors = jira_item.validate()
            if validation_errors:
                logger.warning(
                    "Validation issues for JIRA issue {}: {}",
                    issue_key,
                    ", ".join(validation_errors),
                )

            logger.debug("Processed issue: {}", jira_item.url)

            # Store JiraItem objects directly for streamlined data flow
            all_issues.append(jira_item.to_dict())

        # Get total count from first response
        if total_issues is None:
            total_issues = data.get("total", 0)
            logger.info(
                "Found {} total issues for project {}", total_issues, project_key
            )

        logger.info(
            "Fetched {} issues (batch {})", len(raw_issues), start_at // max_results + 1
        )

        # Check if we've fetched all issues
        if len(raw_issues) < max_results or len(all_issues) >= total_issues:
            break

        # Prepare for next batch
        start_at += max_results

    # Save data to JSON file in ./data directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"jira_{project_key}_issues_{timestamp}.json"
    filepath = f"{constants.DATA_DIR}/{filename}"

    try:
        # Create data directory if it doesn't exist
        os.makedirs(constants.DATA_DIR, exist_ok=True)

        # Prepare final data structure
        final_data = {
            "project_key": project_key,
            "total_issues": len(all_issues),
            "fetched_at": datetime.now().isoformat(),
            "issues": all_issues,
        }

        # Save to timestamped JSON file
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)

        # Also save to a standard filename for easy access by sync function
        standard_filepath = f"{constants.DATA_DIR}/jira_data.json"
        with open(standard_filepath, "w", encoding="utf-8") as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)

        logger.info("Successfully saved {} issues to {}", len(all_issues), filepath)
        logger.info("Also saved to standard file: {}", standard_filepath)

        # Clean up old JIRA data files, keeping only the 10 most recent
        cleanup_old_json_files(f"jira_{project_key}_issues_*.json", keep_count=10)

    except Exception as e:
        logger.error("Failed to save data to file: {}", e)
        return {"error": f"Failed to save data: {e}"}

    logger.info(
        "Successfully fetched {} total issues for project {}",
        len(all_issues),
        project_key,
    )
    return final_data


def get_airfocus_field_data(workspace_id: str) -> Optional[Dict[str, Any]]:
    """
    Get all field data from an Airfocus workspace and save to JSON file.

    This function queries the Airfocus workspace API to retrieve all available fields
    and saves them to a JSON file in the ./data directory for later use.

    Args:
        workspace_id (str): The Airfocus workspace ID to query.

    Returns:
        dict: Dictionary containing all field data if successful, or None if error occurred.
    """
    # Construct Airfocus workspace API endpoint URL
    url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}"

    # Set up authentication headers for Airfocus
    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, verify=constants.SSL_VERIFY)

        success, data = validate_api_response(
            response, f"Get workspace data for {workspace_id}"
        )
        if not success:
            return None

        logger.info("Successfully retrieved workspace data for {}", workspace_id)

        # Extract fields data from _embedded.fields (it's a dictionary, not a list)
        embedded = data.get("_embedded", {})
        fields_dict = embedded.get("fields", {})
        statuses_dict = embedded.get("statuses", {})

        # Convert fields dictionary to list for easier processing
        fields = list(fields_dict.values())
        statuses = list(statuses_dict.values())

        # Create fields mapping for easier access
        field_data = {
            "workspace_id": workspace_id,
            "fetched_at": datetime.now().isoformat(),
            "fields": fields,
            "field_mapping": {},
            "statuses": statuses,
            "status_mapping": {},
        }

        # Create name-to-id mapping for fields
        for field in fields:
            field_name = field.get("name", "")
            field_id = field.get("id", "")
            if field_name and field_id:
                field_data["field_mapping"][field_name] = field_id

        # Create name-to-id mapping for statuses
        for status in statuses:
            status_name = status.get("name", "")
            status_id = status.get("id", "")
            if status_name and status_id:
                field_data["status_mapping"][status_name] = status_id

        # Fetch workspace items to get field values using field names as keys
        field_values = {}

        # Create a reverse mapping from field ID to field name for easier lookup
        id_to_name_mapping = {}
        for field_name, field_id in field_data["field_mapping"].items():
            id_to_name_mapping[field_id] = field_name

        try:
            # Fetch items from workspace
            items_url = (
                f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/search"
            )
            search_payload = {
                "filters": {},
                "pagination": {"limit": 1000, "offset": 0},
            }

            items_response = requests.post(
                items_url,
                headers=headers,
                json=search_payload,
                verify=constants.SSL_VERIFY,
            )

            if items_response.status_code == 200:
                items_data = items_response.json()
                items = items_data.get("items", [])

                # Extract field values from each item, using field names as keys
                for item in items:
                    item_fields = item.get("fields", {})

                    # Process all fields that we have mappings for
                    for field_id, field_data_obj in item_fields.items():
                        field_name = id_to_name_mapping.get(field_id)

                        # Only process fields we recognize and have names for
                        if field_name:
                            # Initialize field values list if not exists
                            if field_name not in field_values:
                                field_values[field_name] = []

                            # Extract field value (handle different field types)
                            field_value = ""
                            if "text" in field_data_obj:
                                field_value = field_data_obj.get("text", "")
                            elif "value" in field_data_obj:
                                field_value = str(field_data_obj.get("value", ""))
                            elif "displayValue" in field_data_obj:
                                field_value = field_data_obj.get("displayValue", "")

                            # Add unique values only
                            if (
                                field_value
                                and field_value not in field_values[field_name]
                            ):
                                field_values[field_name].append(field_value)

                # Log extracted field values
                total_fields = len(field_values)

                logger.info(
                    "Extracted field values for {} fields from workspace items",
                    total_fields,
                )

            else:
                logger.warning(
                    "Failed to fetch workspace items for field values. Status code: {}",
                    items_response.status_code,
                )

        except Exception as e:
            logger.warning("Failed to fetch workspace items for field values: {}", e)

        # Add field values to field_data
        field_data["field_values"] = field_values

        # Save to JSON file
        try:
            os.makedirs(constants.DATA_DIR, exist_ok=True)
            filepath = f"{constants.DATA_DIR}/airfocus_fields.json"

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(field_data, f, indent=2, ensure_ascii=False)

            logger.info(
                "Successfully saved {} field definitions, {} statuses, and field values to {}",
                len(fields),
                len(statuses),
                filepath,
            )
            logger.debug(
                "Available fields: {}", list(field_data["field_mapping"].keys())
            )
            logger.debug(
                "Available statuses: {}", list(field_data["status_mapping"].keys())
            )
            logger.debug(
                "Field values extracted: {}", list(field_data["field_values"].keys())
            )

            return field_data

        except Exception as e:
            logger.error("Failed to save field data to file: {}", e)
            return None

    except Exception as e:
        logger.error(
            "Exception occurred while retrieving workspace data for {}: {}",
            workspace_id,
            e,
        )
        return None


def get_airfocus_project_data(workspace_id: str) -> Dict[str, Any]:
    """
    Fetch Airfocus project data including all items and their details.

    This function queries the Airfocus REST API to retrieve all items for a specified workspace,
    including their name, description, status, and custom fields. The data is stored in a
    JSON file in the ./data directory for further processing.

    Args:
        workspace_id (str): The Airfocus workspace ID to fetch data from.

    Returns:
        dict: Complete JSON response containing all workspace items if successful,
              or an error dictionary if the request fails.
    """
    all_items = []

    # Set up authentication headers
    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/json",
    }

    # Use the items/search endpoint with POST request
    url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/search"

    # Search payload to get all items (empty search criteria)
    search_payload = {"filters": {}, "pagination": {"limit": 1000, "offset": 0}}

    logger.info("Requesting data from endpoint: {}", url)
    logger.debug("Search payload: {}", json.dumps(search_payload, indent=2))
    response = requests.post(
        url, headers=headers, json=search_payload, verify=constants.SSL_VERIFY
    )

    success, data = validate_api_response(
        response, f"Fetch items from workspace {workspace_id}"
    )
    if not success:
        return data  # Return error dict

    try:
        # Extract items from the response
        raw_items = data.get("items", [])

        # Extract only the needed fields from each item
        for item in raw_items:
            # Get basic item data
            item_id = item.get("id", "")
            item_name = item.get("name", "")

            # Extract status information
            status_id = item.get("statusId", "")

            # Extract custom fields
            raw_fields = item.get("fields", {})

            # Create simplified item object with only needed data
            simplified_item = {
                "id": item_id,
                "name": item_name,
                "description": item.get("description", ""),
                "statusId": status_id,
                "color": item.get("color", ""),
                "archived": item.get("archived", False),
                "createdAt": item.get("createdAt", ""),
                "lastUpdatedAt": item.get("lastUpdatedAt", ""),
                "fields": raw_fields,
            }

            logger.debug("Processed Airfocus item: {} (ID: {})", item_name, item_id)
            all_items.append(simplified_item)

        logger.info(
            "Found {} total items in Airfocus workspace {}",
            len(all_items),
            workspace_id,
        )

        # Save data to JSON file in ./data directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"airfocus_{workspace_id}_items_{timestamp}.json"
        filepath = f"{constants.DATA_DIR}/{filename}"

        try:
            # Create data directory if it doesn't exist
            os.makedirs(constants.DATA_DIR, exist_ok=True)

            # Prepare final data structure
            final_data = {
                "workspace_id": workspace_id,
                "total_items": len(all_items),
                "fetched_at": datetime.now().isoformat(),
                "items": all_items,
            }

            # Save to timestamped JSON file
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)

            # Also save to a standard filename for easy access by sync function
            standard_filepath = f"{constants.DATA_DIR}/airfocus_data.json"
            with open(standard_filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)

            logger.info("Successfully saved {} items to {}", len(all_items), filepath)
            logger.info("Also saved to standard file: {}", standard_filepath)

            # Clean up old Airfocus data files, keeping only the 10 most recent
            cleanup_old_json_files(
                f"airfocus_{workspace_id}_items_*.json", keep_count=10
            )

        except Exception as e:
            logger.error("Failed to save data to file: {}", e)
            return {"error": f"Failed to save data: {e}"}

        logger.info(
            "Successfully fetched {} total items from Airfocus workspace {}",
            len(all_items),
            workspace_id,
        )
        return final_data

    except Exception as e:
        logger.error("Exception occurred while fetching Airfocus data: {}", e)
        return {"error": f"Exception occurred: {str(e)}"}


def create_airfocus_item(workspace_id: str, jira_item: JiraItem) -> Dict[str, Any]:
    """
    Create an item in Airfocus based on JIRA issue data.

    This function sends a POST request to the Airfocus API to create a new item
    using the data from a JiraItem object.

    Args:
        workspace_id (str): The Airfocus workspace ID where the item will be created.
        jira_item (JiraItem): JiraItem instance containing JIRA issue data

    Returns:
        dict: Airfocus API response if successful, or error dictionary if failed.
    """
    # Create AirfocusItem from JIRA data
    item = AirfocusItem.from_jira_item(jira_item)
    source_key = item.source_key

    # Validate item data before API call
    validation_errors = item.validate()
    if validation_errors:
        error_msg = f"Validation failed: {', '.join(validation_errors)}"
        logger.error("Validation failed for JIRA issue {}: {}", source_key, error_msg)
        return {"error": error_msg}

    # Generate payload using the item
    payload = item.to_create_payload()

    # Construct Airfocus API endpoint URL
    url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items"

    # Set up authentication headers for Airfocus with Markdown support
    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/vnd.airfocus.markdown+json",
    }

    logger.debug("Creating Airfocus item for JIRA issue {}", source_key)
    logger.debug("Payload: {}", json.dumps(payload, indent=2))

    try:
        response = requests.post(
            url, headers=headers, json=payload, verify=constants.SSL_VERIFY
        )

        success, result = validate_api_response(
            response, f"Create Airfocus item for JIRA issue {source_key}", [200, 201]
        )
        if success:
            team_info = (
                f" with team field '{item.team_field_value}'"
                if item.team_field_value
                else ""
            )
            logger.info(
                "Successfully created Airfocus item for JIRA issue {}{}",
                source_key,
                team_info,
            )
            return result
        else:
            team_info = (
                f" (attempted to set team field '{item.team_field_value}')"
                if item.team_field_value
                else ""
            )
            logger.error(
                "Failed to create Airfocus item for JIRA issue {}{}: {}",
                source_key,
                team_info,
                result.get("error", "Unknown error"),
            )
            return result

    except Exception as e:
        team_info = (
            f" (attempted to set team field '{item.team_field_value}')"
            if item.team_field_value
            else ""
        )
        logger.error(
            "Exception occurred while creating Airfocus item for JIRA issue {}{}: {}",
            source_key,
            team_info,
            e,
        )
        return {"error": f"Exception occurred: {str(e)}"}


def patch_airfocus_item(
    workspace_id: str, item_id: str, jira_item: JiraItem
) -> Dict[str, Any]:
    """
    Update an existing item in Airfocus based on updated JIRA issue data.

    This function sends a PATCH request to the Airfocus API to update an existing item
    using the data from a JiraItem object.

    Args:
        workspace_id (str): The Airfocus workspace ID where the item exists.
        item_id (str): The Airfocus item ID to update.
        jira_item (JiraItem): JiraItem instance containing JIRA issue data

    Returns:
        dict: Airfocus API response if successful, or error dictionary if failed.
    """
    # Create AirfocusItem from JIRA data
    item = AirfocusItem.from_jira_item(jira_item)
    source_key = item.source_key

    # Validate item data before API call
    validation_errors = item.validate()
    if validation_errors:
        error_msg = f"Validation failed: {', '.join(validation_errors)}"
        logger.error(
            "Validation failed for JIRA issue {} update: {}", source_key, error_msg
        )
        return {"error": error_msg}

    # Generate patch operations using the item
    patch_operations = item.to_patch_payload()

    # Construct Airfocus API endpoint URL for PATCH
    url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/{item_id}"

    # Set up authentication headers for Airfocus with Markdown support
    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/vnd.airfocus.markdown+json",
    }

    logger.debug(
        "Updating Airfocus item {} for JIRA issue {} with {} patch operations",
        item_id,
        source_key,
        len(patch_operations),
    )
    logger.debug("Patch operations: {}", json.dumps(patch_operations, indent=2))

    try:
        response = requests.patch(
            url, headers=headers, json=patch_operations, verify=constants.SSL_VERIFY
        )

        success, result = validate_api_response(
            response,
            f"Update Airfocus item {item_id} for JIRA issue {source_key}",
            [200, 201],
        )
        if success:
            team_info = (
                f" with team field '{item.team_field_value}'"
                if item.team_field_value
                else ""
            )
            logger.info(
                "Successfully updated Airfocus item {} for JIRA issue {}{}",
                item_id,
                source_key,
                team_info,
            )
            return result
        else:
            team_info = (
                f" (attempted to set team field '{item.team_field_value}')"
                if item.team_field_value
                else ""
            )
            logger.error(
                "Failed to update Airfocus item {} for JIRA issue {}{}: {}",
                item_id,
                source_key,
                team_info,
                result.get("error", "Unknown error"),
            )
            return result

    except Exception as e:
        team_info = (
            f" (attempted to set team field '{item.team_field_value}')"
            if item.team_field_value
            else ""
        )
        logger.error(
            "Exception occurred while updating Airfocus item {} for JIRA issue {}{}: {}",
            item_id,
            source_key,
            team_info,
            e,
        )
        return {"error": f"Exception occurred: {str(e)}"}


def _load_and_prepare_sync_data(
    jira_data_file: str, workspace_id: str
) -> Tuple[List[JiraItem], Dict[str, Any], Dict[str, Any]]:
    """
    Helper function to load and prepare data for synchronization.

    Args:
        jira_data_file (str): Path to the JSON file containing JIRA issue data.
        workspace_id (str): The Airfocus workspace ID where items will be created/updated.

    Returns:
        tuple: (jira_items, airfocus_by_source_key, sync_stats)
    """
    # Read JIRA data from JSON file
    with open(jira_data_file, "r", encoding="utf-8") as f:
        jira_data = json.load(f)

    # Read Airfocus data from JSON file
    airfocus_data_file = f"{constants.DATA_DIR}/airfocus_data.json"
    airfocus_data = {}
    if os.path.exists(airfocus_data_file):
        with open(airfocus_data_file, "r", encoding="utf-8") as f:
            airfocus_data = json.load(f)
    else:
        logger.warning(
            "Airfocus data file not found at {}. All items will be treated as new.",
            airfocus_data_file,
        )

    # Convert all issues to JiraItem objects with validation
    raw_issues = jira_data.get("issues", [])
    jira_items = []
    validation_failures = 0

    for issue_dict in raw_issues:
        try:
            jira_item = JiraItem.from_simplified_data(issue_dict)
            validation_errors = jira_item.validate()

            if validation_errors:
                logger.warning(
                    "Skipping JIRA issue {} due to validation errors: {}",
                    jira_item.key,
                    ", ".join(validation_errors),
                )
                validation_failures += 1
                continue

            jira_items.append(jira_item)

        except Exception as e:
            logger.error(
                "Failed to create JiraItem from issue data {}: {}",
                issue_dict.get("key", "Unknown"),
                e,
            )
            validation_failures += 1
            continue

    logger.info(
        "Successfully converted {} JIRA issues to JiraItem objects ({} validation failures)",
        len(jira_items),
        validation_failures,
    )

    # Build Airfocus lookup mapping
    airfocus_items = airfocus_data.get("items", [])
    airfocus_by_source_key = {}

    for item_data in airfocus_items:
        airfocus_item = AirfocusItem.from_airfocus_data(item_data)
        if airfocus_item.source_key:
            airfocus_by_source_key[airfocus_item.source_key] = airfocus_item

    logger.info(
        "Starting synchronization of {} JIRA issues to Airfocus workspace {}",
        len(jira_items),
        workspace_id,
    )
    logger.info("Found {} existing Airfocus items for comparison", len(airfocus_items))
    logger.debug(
        "Built lookup mapping for {} Airfocus items with JIRA keys",
        len(airfocus_by_source_key),
    )

    sync_stats = {
        "total_raw_issues": len(raw_issues),
        "validation_failures": validation_failures,
        "processed_issues": len(jira_items),
    }

    return jira_items, airfocus_by_source_key, sync_stats


def _perform_sync_operations(
    workspace_id: str,
    jira_items: List[JiraItem],
    airfocus_by_source_key: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Helper function to perform the actual sync operations.

    Args:
        workspace_id (str): The Airfocus workspace ID.
        jira_items (list): List of JiraItem objects.
        airfocus_by_source_key (dict): Mapping of JIRA keys to Airfocus items.

    Returns:
        dict: Results of sync operations.
    """
    success_count = 0
    error_count = 0
    updated_count = 0
    created_count = 0
    errors = []

    for jira_item in jira_items:
        source_key = jira_item.key

        try:
            # Check if item exists in Airfocus
            existing_item = airfocus_by_source_key.get(source_key)

            if existing_item:
                # Item exists - update it with JIRA data
                item_id = existing_item.item_id

                logger.info(
                    "JIRA issue {} - updating existing Airfocus item {}",
                    source_key,
                    item_id,
                )

                # Update existing item directly with JiraItem
                result = patch_airfocus_item(workspace_id, item_id, jira_item)

                if "error" in result:
                    error_count += 1
                    errors.append(
                        {
                            "source_key": source_key,
                            "action": "update",
                            "error": result["error"],
                        }
                    )
                    logger.error(
                        "Failed to update JIRA issue {}: {}",
                        source_key,
                        result["error"],
                    )
                else:
                    success_count += 1
                    updated_count += 1
                    logger.info(
                        "Successfully updated Airfocus item for JIRA issue {}",
                        source_key,
                    )
            else:
                # Item doesn't exist - create new one
                logger.info(
                    "JIRA issue {} not found in Airfocus - creating new item",
                    source_key,
                )

                # Create new item directly with JiraItem
                result = create_airfocus_item(workspace_id, jira_item)

                if "error" in result:
                    error_count += 1
                    errors.append(
                        {
                            "source_key": source_key,
                            "action": "create",
                            "error": result["error"],
                        }
                    )
                    logger.warning(
                        "Failed to create JIRA issue {}: {}",
                        source_key,
                        result["error"],
                    )
                else:
                    success_count += 1
                    created_count += 1
                    logger.info(
                        "Successfully created Airfocus item for JIRA issue {}",
                        source_key,
                    )

        except Exception as e:
            error_count += 1
            error_msg = f"Exception during sync: {str(e)}"
            errors.append(
                {"source_key": source_key, "action": "unknown", "error": error_msg}
            )
            logger.error("Exception while syncing JIRA issue {}: {}", source_key, e)

    return {
        "success_count": success_count,
        "error_count": error_count,
        "created_count": created_count,
        "updated_count": updated_count,
        "errors": errors,
    }


def sync_jira_to_airfocus(jira_data_file: str, workspace_id: str) -> Dict[str, Any]:
    """
    Synchronize JIRA issues to Airfocus by creating new items and updating existing ones.

    This function reads the JIRA data from a JSON file and creates corresponding
    items in the specified Airfocus workspace. For existing items, it always updates
    them with the current JIRA data, overwriting any changes in Airfocus.

    Args:
        jira_data_file (str): Path to the JSON file containing JIRA issue data.
        workspace_id (str): The Airfocus workspace ID where items will be created/updated.

    Returns:
        dict: Summary of the synchronization process including success and failure counts.
    """
    try:
        # Load and prepare data using helper function
        jira_items, airfocus_by_source_key, sync_stats = _load_and_prepare_sync_data(
            jira_data_file, workspace_id
        )

        # Perform sync operations
        results = _perform_sync_operations(
            workspace_id, jira_items, airfocus_by_source_key
        )

        # Log summary
        logger.info(
            "Synchronization completed. Success: {}, Errors: {} (Created: {}, Updated: {}, Validation failures: {})",
            results["success_count"],
            results["error_count"],
            results["created_count"],
            results["updated_count"],
            sync_stats["validation_failures"],
        )

        return {
            "total_issues": sync_stats["total_raw_issues"],
            "processed_issues": sync_stats["processed_issues"],
            "validation_failures": sync_stats["validation_failures"],
            "success_count": results["success_count"],
            "error_count": results["error_count"],
            "created_count": results["created_count"],
            "updated_count": results["updated_count"],
            "errors": results["errors"],
        }

    except Exception as e:
        logger.error("Failed to read JIRA data file {}: {}", jira_data_file, e)
        return {"error": f"Failed to read data file: {str(e)}"}


def cleanup_old_json_files(pattern: str, keep_count: int = 10) -> None:
    """
    Remove old JSON files matching a pattern, keeping only the most recent ones.

    Args:
        pattern (str): File pattern to match (e.g., "jira_*_issues_*.json")
        keep_count (int): Number of most recent files to keep (default: 10)
    """
    try:
        # Get all files matching the pattern in the data directory
        file_pattern = f"{constants.DATA_DIR}/{pattern}"
        files = glob.glob(file_pattern)

        if len(files) <= keep_count:
            logger.debug(
                "Found {} files matching '{}', no cleanup needed (keeping {})",
                len(files),
                pattern,
                keep_count,
            )
            return

        # Sort files by modification time (newest first)
        files.sort(key=os.path.getmtime, reverse=True)

        # Keep only the most recent files
        files_to_keep = files[:keep_count]
        files_to_delete = files[keep_count:]

        logger.info(
            "Cleaning up old files for pattern '{}': keeping {}, deleting {}",
            pattern,
            len(files_to_keep),
            len(files_to_delete),
        )

        # Delete old files
        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                logger.debug("Deleted old file: {}", file_path)
            except Exception as e:
                logger.warning("Failed to delete file {}: {}", file_path, e)

    except Exception as e:
        logger.error(
            "Exception occurred during cleanup for pattern '{}': {}", pattern, e
        )


# =============================================================================
# Azure DevOps Sync Functions
# =============================================================================


def get_azure_devops_token() -> Optional[str]:
    """
    Acquire Azure DevOps access token via Azure CLI device-code login.

    Returns:
        Access token string if successful, None otherwise.
    """
    config = AzureCliConfig(
        devops_resource=constants.AZURE_DEVOPS_RESOURCE,
        az_cli_python_exe=getattr(constants, "AZURE_CLI_PYTHON_EXE", None),
        az_cli_bat_path=getattr(constants, "AZURE_CLI_BAT_PATH", None),
    )

    logger.info("Acquiring Azure DevOps token via Azure CLI...")
    token = get_devops_token_via_azure_cli(config)

    if token:
        logger.info("Successfully acquired Azure DevOps token")
    else:
        logger.error("Failed to acquire Azure DevOps token")

    return token


def get_azure_devops_work_items(
    organization: str, project: str, work_item_type: str, token: str
) -> Dict[str, Any]:
    """
    Fetch work items from Azure DevOps.

    Args:
        organization: Azure DevOps organization name
        project: Azure DevOps project name
        work_item_type: Type of work items to fetch (e.g., "Epic", "Feature")
        token: Azure DevOps access token

    Returns:
        Dictionary containing work items data or error dict.
    """
    base_url = f"https://dev.azure.com/{organization}/{project}"
    wiql_url = f"{base_url}/_apis/wit/wiql?api-version=7.0"

    query = {
        "query": f"SELECT [System.Id], [System.Title], [System.Description], [System.State], [System.AssignedTo], [System.ChangedDate] FROM WorkItems WHERE [System.WorkItemType] = '{work_item_type}'"
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json; api-version=7.0",
    }

    logger.info("Querying Azure DevOps for {} items...", work_item_type)

    try:
        response = requests.post(
            wiql_url,
            headers=headers,
            json=query,
            verify=constants.SSL_VERIFY,
            timeout=30,
        )

        success, data = validate_api_response(response, "Azure DevOps WIQL query")
        if not success:
            return data

        work_items = data.get("workItems", [])
        if not work_items:
            logger.info("No {} items found", work_item_type)
            return {"workItems": [], "items": []}

        logger.info("Found {} work items, fetching details...", len(work_items))

        ids = [str(wi["id"]) for wi in work_items]
        batch_size = 200
        all_items = []

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            ids_url = f"{base_url}/_apis/wit/workitems?ids={','.join(batch_ids)}&fields=System.Id,System.Title,System.Description,System.State,System.AssignedTo,System.ChangedDate&$top={batch_size}&api-version=7.0"

            batch_response = requests.get(
                ids_url, headers=headers, verify=constants.SSL_VERIFY, timeout=30
            )

            success, batch_data = validate_api_response(
                batch_response, f"Fetch work item details (batch {i // batch_size + 1})"
            )
            if success:
                all_items.extend(batch_data.get("value", []))

        result = {"workItems": work_items, "items": all_items}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"azure_devops_{work_item_type.lower()}_{timestamp}.json"
        filepath = f"{constants.DATA_DIR}/{filename}"

        os.makedirs(constants.DATA_DIR, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        standard_filepath = f"{constants.DATA_DIR}/azure_devops_data.json"
        with open(standard_filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        logger.info("Saved {} items to {}", len(all_items), filepath)
        cleanup_old_json_files(
            f"azure_devops_{work_item_type.lower()}_*.json", keep_count=10
        )

        return result

    except Exception as e:
        logger.error("Error fetching Azure DevOps work items: {}", e)
        return {"error": str(e)}


def sync_azure_devops_to_airfocus(
    azure_devops_data_file: str,
    workspace_id: str,
    organization: str,
    project: str,
) -> Dict[str, Any]:
    """
    Synchronize Azure DevOps work items to Airfocus.

    Args:
        azure_devops_data_file: Path to Azure DevOps data JSON file
        workspace_id: Airfocus workspace ID
        organization: Azure DevOps organization name
        project: Azure DevOps project name

    Returns:
        Sync results dictionary.
    """
    with open(azure_devops_data_file, "r", encoding="utf-8") as f:
        azure_data = json.load(f)

    airfocus_data_file = f"{constants.DATA_DIR}/airfocus_data.json"
    airfocus_data = {}
    if os.path.exists(airfocus_data_file):
        with open(airfocus_data_file, "r", encoding="utf-8") as f:
            airfocus_data = json.load(f)

    raw_items = azure_data.get("items", [])

    airfocus_items = airfocus_data.get("items", [])
    airfocus_by_azure_id = {}

    for item_data in airfocus_items:
        af_item = AirfocusItem.from_airfocus_data(item_data)
        if af_item.azure_devops_id:
            airfocus_by_azure_id[af_item.azure_devops_id] = af_item

    logger.info(
        "Syncing {} Azure DevOps items to Airfocus workspace {}",
        len(raw_items),
        workspace_id,
    )

    created_count = 0
    updated_count = 0
    error_count = 0
    errors = []

    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/vnd.airfocus.markdown+json",
    }

    for azure_item in raw_items:
        azure_id = azure_item["id"]
        title = azure_item["fields"].get("System.Title", "")
        state = azure_item["fields"].get("System.State", "")
        assignee = azure_item["fields"].get("System.AssignedTo")

        existing = airfocus_by_azure_id.get(str(azure_id))

        item = AirfocusItem.from_azure_devops_item(
            organization,
            project,
            constants.AZURE_DEVOPS_WORK_ITEM_TYPE,
            azure_id,
            title,
            state,
            assignee,
        )

        validation_errors = item.validate()
        if validation_errors:
            logger.warning(
                "Validation failed for Azure DevOps item {}: {}",
                azure_id,
                ", ".join(validation_errors),
            )

        if existing:
            logger.info(
                "Azure DevOps item {} - updating existing Airfocus item {}",
                azure_id,
                existing.item_id,
            )

            patch_operations = item.to_patch_payload()
            url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/{existing.item_id}"

            try:
                response = requests.patch(
                    url,
                    headers=headers,
                    json=patch_operations,
                    verify=constants.SSL_VERIFY,
                )

                if response.status_code in [200, 201]:
                    updated_count += 1
                    logger.info("Updated Airfocus item for Azure DevOps {}", azure_id)
                else:
                    error_count += 1
                    errors.append(
                        {
                            "azure_id": azure_id,
                            "action": "update",
                            "error": f"Status {response.status_code}: {response.text}",
                        }
                    )
                    logger.error(
                        "Failed to update Azure DevOps {}: {}", azure_id, response.text
                    )
            except Exception as e:
                error_count += 1
                errors.append(
                    {"azure_id": azure_id, "action": "update", "error": str(e)}
                )
                logger.error("Error updating Azure DevOps {}: {}", azure_id, e)
        else:
            logger.info(
                "Azure DevOps item {} not found in Airfocus - creating new item",
                azure_id,
            )

            payload = item.to_create_payload()
            url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items"

            try:
                response = requests.post(
                    url, headers=headers, json=payload, verify=constants.SSL_VERIFY
                )

                if response.status_code in [200, 201]:
                    created_count += 1
                    logger.info("Created Airfocus item for Azure DevOps {}", azure_id)
                else:
                    error_count += 1
                    errors.append(
                        {
                            "azure_id": azure_id,
                            "action": "create",
                            "error": f"Status {response.status_code}: {response.text}",
                        }
                    )
                    logger.error(
                        "Failed to create Azure DevOps {}: {}", azure_id, response.text
                    )
            except Exception as e:
                error_count += 1
                errors.append(
                    {"azure_id": azure_id, "action": "create", "error": str(e)}
                )
                logger.error("Error creating Azure DevOps {}: {}", azure_id, e)

    return {
        "total_items": len(raw_items),
        "created_count": created_count,
        "updated_count": updated_count,
        "error_count": error_count,
        "errors": errors,
    }


def run_azure_devops_sync() -> None:
    """Execute Azure DevOps to Airfocus sync."""
    token = get_azure_devops_token()
    if not token:
        logger.error("Failed to acquire Azure DevOps token. Exiting.")
        sys.exit(1)

    organization, project = _parse_azure_devops_url(constants.AZURE_DEVOPS_URL)
    if not organization or not project:
        logger.error(
            "Invalid AZURE_DEVOPS_URL format. Expected: https://dev.azure.com/org/project"
        )
        sys.exit(1)

    logger.info(
        "Fetching Azure Devops {} items...", constants.AZURE_DEVOPS_WORK_ITEM_TYPE
    )
    azure_data = get_azure_devops_work_items(
        organization, project, constants.AZURE_DEVOPS_WORK_ITEM_TYPE, token
    )
    if "error" in azure_data:
        logger.error("Failed to fetch Azure DevOps data: {}", azure_data["error"])
        sys.exit(1)

    logger.info("Fetching Airfocus field data...")
    field_data = get_airfocus_field_data(constants.AIRFOCUS_WORKSPACE_ID)
    if field_data is None:
        logger.error("Failed to fetch Airfocus field data")
        sys.exit(1)

    logger.info("Fetching Airfocus project data...")
    airfocus_data = get_airfocus_project_data(constants.AIRFOCUS_WORKSPACE_ID)
    if airfocus_data is None:
        logger.error("Failed to fetch Airfocus project data")
        sys.exit(1)

    results = sync_azure_devops_to_airfocus(
        f"{constants.DATA_DIR}/azure_devops_data.json",
        constants.AIRFOCUS_WORKSPACE_ID,
        organization,
        project,
    )

    logger.info(
        "Azure DevOps sync completed. Created: {}, Updated: {}, Errors: {}",
        results["created_count"],
        results["updated_count"],
        results["error_count"],
    )

    cleanup_old_json_files("azure_devops_*.json", keep_count=10)


def _parse_azure_devops_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse Azure DevOps URL to extract organization and project."""
    if not url.startswith("https://dev.azure.com/"):
        return None, None

    parts = url.replace("https://dev.azure.com/", "").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


def run_jira_sync() -> None:
    """Execute JIRA to Airfocus sync."""
    logger.info("Starting JIRA sync...")

    logger.info("Fetching Airfocus field data...")
    field_data = get_airfocus_field_data(constants.AIRFOCUS_WORKSPACE_ID)
    if field_data is None:
        logger.error("Failed to fetch Airfocus field data")
        sys.exit(1)

    logger.info("Fetching JIRA project data...")
    jira_data = get_jira_project_data(constants.JIRA_PROJECT_KEY)
    if jira_data is None:
        logger.error("Failed to fetch JIRA project data")
        sys.exit(1)

    logger.info("Fetching Airfocus project data...")
    airfocus_data = get_airfocus_project_data(constants.AIRFOCUS_WORKSPACE_ID)
    if airfocus_data is None:
        logger.error("Failed to fetch Airfocus project data")
        sys.exit(1)

    sync_jira_to_airfocus(
        f"{constants.DATA_DIR}/jira_data.json", constants.AIRFOCUS_WORKSPACE_ID
    )

    cleanup_old_json_files("jira_*_issues_*.json", keep_count=10)
    cleanup_old_json_files("airfocus_*_items_*.json", keep_count=10)


def main() -> None:
    """
    Main entry point for the JIRA to Airfocus integration script.

    Handles command-line arguments and routes to the appropriate sync function.
    """
    parser = argparse.ArgumentParser(
        description="Sync JIRA or Azure DevOps issues to Airfocus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --jira              Sync JIRA issues to Airfocus
  python main.py --azure-devops      Sync Azure DevOps work items to Airfocus
        """,
    )
    parser.add_argument(
        "--jira",
        action="store_true",
        help="Sync JIRA issues to Airfocus",
    )
    parser.add_argument(
        "--azure-devops",
        action="store_true",
        help="Sync Azure DevOps work items to Airfocus",
    )

    args = parser.parse_args()

    if not args.jira and not args.azure_devops:
        parser.print_help()
        sys.exit(1)

    validation_errors = validate_constants()
    if validation_errors:
        for error in validation_errors:
            logger.error("Configuration error: {}", error)
        logger.error("Please fix the errors in constants.py and try again.")
        sys.exit(1)

    if args.jira:
        logger.info("Starting JIRA sync...")
        run_jira_sync()
    elif args.azure_devops:
        logger.info("Starting Azure DevOps sync...")
        run_azure_devops_sync()


if __name__ == "__main__":
    main()
