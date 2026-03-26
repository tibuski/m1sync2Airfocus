"""
JIRA to Airfocus Integration Script

This module provides functionality to fetch data from JIRA projects and sync them with Airfocus.
It handles authentication, data retrieval, and logging for the integration process.
"""

import sys
import argparse
import urllib3

from loguru import logger

from config import validate_config, get_config
from api import AirfocusClient
from sync import JiraSync, AzureDevOpsSync

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


def run_jira_sync() -> None:
    """Execute JIRA to Airfocus sync."""
    logger.info("Starting JIRA sync...")
    airfocus_client = AirfocusClient()

    logger.info("Fetching Airfocus project data...")
    success, airfocus_data = airfocus_client.get_workspace_project_data(
        constants.AIRFOCUS_WORKSPACE_ID
    )
    if not success:
        logger.error("Failed to fetch Airfocus project data: {}", airfocus_data["error"])
        sys.exit(1)

    logger.info("Fetching Airfocus field data...")
    success, field_data = airfocus_client.get_workspace_field_data(
        constants.AIRFOCUS_WORKSPACE_ID,
        workspace_items=airfocus_data.get("items", []),
    )
    if not success:
        logger.error("Failed to fetch Airfocus field data: {}", field_data.get("error"))
        sys.exit(1)

    jira_sync = JiraSync()

    logger.info("Fetching JIRA project data...")
    jira_data = jira_sync.fetch_data()
    if "error" in jira_data:
        logger.error("Failed to fetch JIRA project data: {}", jira_data["error"])
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
    airfocus_client = AirfocusClient()

    logger.info("Fetching Airfocus project data...")
    success, airfocus_data = airfocus_client.get_workspace_project_data(
        constants.AIRFOCUS_WORKSPACE_ID
    )
    if not success:
        logger.error("Failed to fetch Airfocus project data: {}", airfocus_data["error"])
        sys.exit(1)

    logger.info("Fetching Airfocus field data...")
    success, field_data = airfocus_client.get_workspace_field_data(
        constants.AIRFOCUS_WORKSPACE_ID,
        workspace_items=airfocus_data.get("items", []),
    )
    if not success:
        logger.error("Failed to fetch Airfocus field data: {}", field_data.get("error"))
        sys.exit(1)

    azure_sync = AzureDevOpsSync()

    logger.info("Fetching Azure DevOps data...")
    azure_data = azure_sync.fetch_data()
    logger.debug("Azure DevOps data result: {}", azure_data)
    if "error" in azure_data:
        logger.error("Failed to fetch Azure DevOps data: {}", azure_data["error"])
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
