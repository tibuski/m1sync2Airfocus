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
from typing import Dict, List, Tuple, Optional, Any

from loguru import logger

from config import validate_config, get_config
from api import AirfocusClient
from sync import JiraSync, AzureDevOpsSync
from models import AirfocusItem

constants = get_config()

if not constants.SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger.remove()
logger.add(
    constants.LOG_FILE_PATH,
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}",
    rotation="10 MB",
    retention="30 days",
)
logger.add(sys.stderr, level=constants.LOGGING_LEVEL, colorize=True)


def get_airfocus_field_data(workspace_id: str) -> Optional[Dict[str, Any]]:
    """Get all field data from an Airfocus workspace and save to JSON file."""
    client = AirfocusClient()
    url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}"

    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, verify=constants.SSL_VERIFY)

        success, data = client.validate_response(
            response, f"Get workspace data for {workspace_id}"
        )
        if not success:
            return None

        logger.info("Successfully retrieved workspace data for {}", workspace_id)

        embedded = data.get("_embedded", {})
        fields_dict = embedded.get("fields", {})
        statuses_dict = embedded.get("statuses", {})

        fields = list(fields_dict.values())
        statuses = list(statuses_dict.values())

        field_data = {
            "workspace_id": workspace_id,
            "fetched_at": datetime.now().isoformat(),
            "fields": fields,
            "field_mapping": {},
            "statuses": statuses,
            "status_mapping": {},
        }

        for field in fields:
            field_name = field.get("name", "")
            field_id = field.get("id", "")
            if field_name and field_id:
                field_data["field_mapping"][field_name] = field_id

        for status in statuses:
            status_name = status.get("name", "")
            status_id = status.get("id", "")
            if status_name and status_id:
                field_data["status_mapping"][status_name] = status_id

        field_values = {}

        id_to_name_mapping = {}
        for field_name, field_id in field_data["field_mapping"].items():
            id_to_name_mapping[field_id] = field_name

        try:
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

                for item in items:
                    item_fields = item.get("fields", {})

                    for field_id, field_data_obj in item_fields.items():
                        field_name = id_to_name_mapping.get(field_id)

                        if field_name:
                            if field_name not in field_values:
                                field_values[field_name] = []

                            field_value = ""
                            if "text" in field_data_obj:
                                field_value = field_data_obj.get("text", "")
                            elif "value" in field_data_obj:
                                field_value = str(field_data_obj.get("value", ""))
                            elif "displayValue" in field_data_obj:
                                field_value = field_data_obj.get("displayValue", "")

                            if (
                                field_value
                                and field_value not in field_values[field_name]
                            ):
                                field_values[field_name].append(field_value)

                logger.info(
                    "Extracted field values for {} fields from workspace items",
                    len(field_values),
                )

        except Exception as e:
            logger.warning("Failed to fetch workspace items for field values: {}", e)

        field_data["field_values"] = field_values

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
    """Fetch Airfocus project data including all items and their details."""
    client = AirfocusClient()

    url = f"{constants.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/search"
    search_payload = {"filters": {}, "pagination": {"limit": 1000, "offset": 0}}

    logger.info("Requesting data from endpoint: {}", url)

    headers = {
        "Authorization": f"Bearer {constants.AIRFOCUS_API_KEY}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        url, headers=headers, json=search_payload, verify=constants.SSL_VERIFY
    )

    success, data = client.validate_response(
        response, f"Fetch items from workspace {workspace_id}"
    )
    if not success:
        return data

    try:
        raw_items = data.get("items", [])
        all_items = []

        for item in raw_items:
            simplified_item = {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "statusId": item.get("statusId", ""),
                "color": item.get("color", ""),
                "archived": item.get("archived", False),
                "createdAt": item.get("createdAt", ""),
                "lastUpdatedAt": item.get("lastUpdatedAt", ""),
                "fields": item.get("fields", {}),
            }

            logger.debug(
                "Processed Airfocus item: {} (ID: {})",
                simplified_item["name"],
                simplified_item["id"],
            )
            all_items.append(simplified_item)

        logger.info(
            "Found {} total items in Airfocus workspace {}",
            len(all_items),
            workspace_id,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"airfocus_{workspace_id}_items_{timestamp}.json"
        filepath = f"{constants.DATA_DIR}/{filename}"

        try:
            os.makedirs(constants.DATA_DIR, exist_ok=True)

            final_data = {
                "workspace_id": workspace_id,
                "total_items": len(all_items),
                "fetched_at": datetime.now().isoformat(),
                "items": all_items,
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)

            standard_filepath = f"{constants.DATA_DIR}/airfocus_data.json"
            with open(standard_filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)

            logger.info("Successfully saved {} items to {}", len(all_items), filepath)

        except Exception as e:
            logger.error("Failed to save data to file: {}", e)
            return {"error": f"Failed to save data: {e}"}

        return final_data

    except Exception as e:
        logger.error("Exception occurred while fetching Airfocus data: {}", e)
        return {"error": f"Exception occurred: {str(e)}"}


def run_jira_sync() -> None:
    """Execute JIRA to Airfocus sync."""
    logger.info("Starting JIRA sync...")

    logger.info("Fetching Airfocus field data...")
    field_data = get_airfocus_field_data(constants.AIRFOCUS_WORKSPACE_ID)
    if field_data is None:
        logger.error("Failed to fetch Airfocus field data")
        sys.exit(1)

    jira_sync = JiraSync()

    logger.info("Fetching JIRA project data...")
    jira_data = jira_sync.fetch_data()
    if "error" in jira_data:
        logger.error("Failed to fetch JIRA project data: {}", jira_data["error"])
        sys.exit(1)

    logger.info("Fetching Airfocus project data...")
    airfocus_data = get_airfocus_project_data(constants.AIRFOCUS_WORKSPACE_ID)
    if "error" in airfocus_data:
        logger.error(
            "Failed to fetch Airfocus project data: {}", airfocus_data["error"]
        )
        sys.exit(1)

    results = jira_sync.sync_to_airfocus(jira_data)

    logger.info(
        "JIRA sync completed. Processed: {}, Created: {}, Updated: {}, Errors: {}",
        results.get("processed_issues"),
        results.get("created_count"),
        results.get("updated_count"),
        results.get("error_count"),
    )

    jira_sync.cleanup_old_files(
        f"jira_{constants.JIRA_PROJECT_KEY}_issues_*.json", keep_count=10
    )
    jira_sync.cleanup_old_files("airfocus_*_items_*.json", keep_count=10)


def run_azure_devops_sync() -> None:
    """Execute Azure DevOps to Airfocus sync."""
    logger.info("Starting Azure DevOps sync...")

    logger.info("Fetching Airfocus field data...")
    field_data = get_airfocus_field_data(constants.AIRFOCUS_WORKSPACE_ID)
    if field_data is None:
        logger.error("Failed to fetch Airfocus field data")
        sys.exit(1)

    azure_sync = AzureDevOpsSync()

    logger.info("Fetching Azure DevOps data...")
    azure_data = azure_sync.fetch_data()
    logger.debug("Azure DevOps data result: {}", azure_data)
    if "error" in azure_data:
        logger.error("Failed to fetch Azure DevOps data: {}", azure_data["error"])
        sys.exit(1)

    logger.info("Fetching Airfocus project data...")
    airfocus_data = get_airfocus_project_data(constants.AIRFOCUS_WORKSPACE_ID)
    if "error" in airfocus_data:
        logger.error(
            "Failed to fetch Airfocus project data: {}", airfocus_data["error"]
        )
        sys.exit(1)

    results = azure_sync.sync_to_airfocus(azure_data)

    logger.info(
        "Azure DevOps sync completed. Created: {}, Updated: {}, Errors: {}",
        results.get("created_count"),
        results.get("updated_count"),
        results.get("error_count"),
    )

    azure_sync.cleanup_old_files("azure_devops_*.json", keep_count=10)


def main() -> None:
    """Main entry point for the JIRA to Airfocus integration script."""
    logger.info(
        "Logger configuration - file: DEBUG to {}, console: {}",
        constants.LOG_FILE_PATH,
        constants.LOGGING_LEVEL,
    )

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
        sys.exit(0)

    sync_mode = "jira" if args.jira else "azure-devops"
    validation_errors = validate_config(sync_mode)
    if validation_errors:
        for error in validation_errors:
            logger.error("Configuration error: {}", error)
        logger.error("Please fix the errors in constants.py and try again.")
        sys.exit(1)

    if args.jira:
        run_jira_sync()
    elif args.azure_devops:
        run_azure_devops_sync()


if __name__ == "__main__":
    main()
