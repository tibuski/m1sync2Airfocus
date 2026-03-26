"""
JIRA to Airfocus Integration Script

This module provides functionality to fetch data from JIRA projects and sync them with Airfocus.
It handles authentication, data retrieval, and logging for the integration process.
"""

import sys
import argparse
import glob
import os
import urllib3

from loguru import logger

from config import validate_config, get_config
from api import AirfocusClient
from exceptions import ConfigurationError, SyncError
from sync import JiraSync, AzureDevOpsSync

logger.remove()
logger.add(sys.stderr, level="INFO", colorize=True)

constants = None


def initialize_runtime_config():
    """Load config and initialize logging/SSL behavior."""
    active_config = get_config()

    if not active_config.SSL_VERIFY:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    logger.remove()
    logger.add(
        active_config.LOG_FILE_PATH,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} - {level} - {message}",
        rotation="10 MB",
        retention="30 days",
    )
    logger.add(sys.stderr, level=active_config.LOGGING_LEVEL, colorize=True)
    return active_config


def get_snapshot_files_to_keep() -> int:
    """Return the configured number of snapshot files to retain."""
    raw_keep_count = getattr(constants, "SNAPSHOT_FILES_TO_KEEP", 3)

    try:
        keep_count = int(raw_keep_count)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid SNAPSHOT_FILES_TO_KEEP value '{}'; using default 3",
            raw_keep_count,
        )
        return 3

    if keep_count < 0:
        logger.warning(
            "SNAPSHOT_FILES_TO_KEEP cannot be negative (got {}); using default 3",
            keep_count,
        )
        return 3

    return keep_count


def cleanup_old_files(*patterns: str) -> None:
    """Delete old timestamped snapshot files from the data directory."""
    keep_count = get_snapshot_files_to_keep()

    for pattern in patterns:
        file_pattern = os.path.join(constants.DATA_DIR, pattern)
        files = glob.glob(file_pattern)

        if len(files) <= keep_count:
            continue

        files.sort(key=os.path.getmtime, reverse=True)
        files_to_delete = files[keep_count:]

        logger.info(
            "Cleaning snapshot files for pattern '{}': keeping {}, deleting {}",
            pattern,
            keep_count,
            len(files_to_delete),
        )

        for file_path in files_to_delete:
            try:
                os.remove(file_path)
                logger.debug("Deleted old snapshot file: {}", file_path)
            except OSError as exc:
                logger.warning("Failed to delete snapshot file {}: {}", file_path, exc)


def cleanup_generated_files(sync_mode: str) -> None:
    """Clean old snapshot files for the selected sync mode before syncing."""
    patterns = [f"airfocus_{constants.AIRFOCUS_WORKSPACE_ID}_items_*.json"]

    if sync_mode == "jira":
        patterns.append(f"jira_{constants.JIRA_PROJECT_KEY}_*.json")
    elif sync_mode == "azure-devops":
        work_item_type = getattr(constants, "AZURE_DEVOPS_WORK_ITEM_TYPE", "").strip()
        if work_item_type:
            patterns.append(f"azure_devops_{work_item_type.lower()}_*.json")

    cleanup_old_files(*patterns)


def run_jira_sync() -> None:
    """Execute JIRA to Airfocus sync."""
    logger.info("Starting JIRA sync...")
    cleanup_generated_files("jira")
    airfocus_client = AirfocusClient()

    logger.info("Fetching Airfocus project data...")
    success, airfocus_data = airfocus_client.get_workspace_project_data(
        constants.AIRFOCUS_WORKSPACE_ID
    )
    if not success:
        raise SyncError(
            "Failed to fetch Airfocus project data",
            details={"error": airfocus_data.get("error")},
        )

    logger.info("Fetching Airfocus field data...")
    success, field_data = airfocus_client.get_workspace_field_data(
        constants.AIRFOCUS_WORKSPACE_ID,
        workspace_items=airfocus_data.get("items", []),
    )
    if not success:
        raise SyncError(
            "Failed to fetch Airfocus field data",
            details={"error": field_data.get("error")},
        )

    jira_sync = JiraSync()

    logger.info("Fetching JIRA project data...")
    jira_data = jira_sync.fetch_data()

    results = jira_sync.sync_to_airfocus(jira_data)

    logger.info(
        "JIRA sync completed. Processed: {}, Created: {}, Updated: {}, Errors: {}",
        results.get("processed_issues"),
        results.get("created_count"),
        results.get("updated_count"),
        results.get("error_count"),
    )


def run_azure_devops_sync() -> None:
    """Execute Azure DevOps to Airfocus sync."""
    logger.info("Starting Azure DevOps sync...")
    cleanup_generated_files("azure-devops")
    airfocus_client = AirfocusClient()

    logger.info("Fetching Airfocus project data...")
    success, airfocus_data = airfocus_client.get_workspace_project_data(
        constants.AIRFOCUS_WORKSPACE_ID
    )
    if not success:
        raise SyncError(
            "Failed to fetch Airfocus project data",
            details={"error": airfocus_data.get("error")},
        )

    logger.info("Fetching Airfocus field data...")
    success, field_data = airfocus_client.get_workspace_field_data(
        constants.AIRFOCUS_WORKSPACE_ID,
        workspace_items=airfocus_data.get("items", []),
    )
    if not success:
        raise SyncError(
            "Failed to fetch Airfocus field data",
            details={"error": field_data.get("error")},
        )

    azure_sync = AzureDevOpsSync()

    logger.info("Fetching Azure DevOps data...")
    azure_data = azure_sync.fetch_data()
    logger.debug("Azure DevOps data result: {}", azure_data)

    results = azure_sync.sync_to_airfocus(azure_data)

    logger.info(
        "Azure DevOps sync completed. Created: {}, Updated: {}, Errors: {}",
        results.get("created_count"),
        results.get("updated_count"),
        results.get("error_count"),
    )


def main() -> None:
    """Main entry point for the JIRA to Airfocus integration script."""
    global constants

    try:
        constants = initialize_runtime_config()
    except ConfigurationError as exc:
        logger.error("Configuration error: {}", exc)
        sys.exit(1)

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

    try:
        if args.jira:
            run_jira_sync()
        elif args.azure_devops:
            run_azure_devops_sync()
    except SyncError as exc:
        logger.error("Sync failed: {}", exc)
        if getattr(exc, "details", None):
            logger.debug("Failure details: {}", exc.details)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected failure: {}", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
