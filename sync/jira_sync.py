"""
JIRA synchronization module.

This module provides functionality to sync JIRA issues to Airfocus.
"""

from typing import Any, Dict, List
from loguru import logger

from sync.base import BaseSync
from api import JiraClient
from models import JiraItem, AirfocusItem


class JiraSync(BaseSync):
    """Handles synchronization from JIRA to Airfocus."""

    def __init__(self):
        super().__init__()
        self.jira_client = JiraClient()

    def fetch_data(self) -> Dict[str, Any]:
        """Fetch JIRA project data."""
        project_key = self.config.JIRA_PROJECT_KEY
        logger.info("Fetching JIRA project data for {}...", project_key)

        success, data = self.jira_client.get_issues(project_key)

        if not success:
            logger.error("Failed to fetch JIRA data: {}", data.get("error"))
            return {"error": data.get("error")}

        issues_data = data.get("issues", [])
        all_issues = []

        for issue in issues_data:
            base_url = self.config.JIRA_REST_URL.replace("/rest/api/latest", "")
            jira_item = JiraItem.from_jira_api_data(issue, project_key, base_url)

            validation_errors = jira_item.validate()
            if validation_errors:
                logger.warning(
                    "Validation issues for JIRA issue {}: {}",
                    jira_item.key,
                    ", ".join(validation_errors),
                )

            all_issues.append(jira_item.to_dict())

        result = {
            "project_key": project_key,
            "total_issues": len(all_issues),
            "issues": all_issues,
        }

        self.save_to_json(result, "jira", project_key)

        logger.info("Successfully fetched {} JIRA issues", len(all_issues))
        return result

    def sync_to_airfocus(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sync JIRA issues to Airfocus."""
        workspace_id = self.config.AIRFOCUS_WORKSPACE_ID
        jira_data = data

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

        logger.info(
            "Starting sync of {} JIRA issues to Airfocus ({} validation failures)",
            len(jira_items),
            validation_failures,
        )

        airfocus_data = self.load_airfocus_items()
        airfocus_items = airfocus_data.get("items", [])
        airfocus_by_source_key = {}

        for item_data in airfocus_items:
            af_item = AirfocusItem.from_airfocus_data(item_data)
            if af_item.source_key:
                airfocus_by_source_key[af_item.source_key] = {
                    "parsed": af_item,
                    "raw": item_data,
                }

        to_create = []
        to_update = []
        unchanged_count = 0

        created_count = 0
        updated_count = 0
        error_count = 0
        errors = []

        for jira_item in jira_items:
            source_key = jira_item.key
            existing_item = airfocus_by_source_key.get(source_key)
            airfocus_item = AirfocusItem.from_jira_item(jira_item)

            if existing_item:
                if airfocus_item.has_changes(existing_item["raw"]):
                    to_update.append(
                        {
                            "item_id": existing_item["parsed"].item_id,
                            "source_key": source_key,
                            "operations": airfocus_item.to_patch_payload(),
                        }
                    )
                else:
                    unchanged_count += 1
            else:
                to_create.append(
                    {
                        "item": airfocus_item,
                        "source_key": source_key,
                    }
                )

        batch_size = 50

        for i in range(0, len(to_create), batch_size):
            batch = to_create[i : i + batch_size]
            payloads = [item["item"].to_create_payload() for item in batch]
            source_keys = [item["source_key"] for item in batch]

            try:
                success, result = self.airfocus_client.create_items_bulk(
                    workspace_id, payloads
                )
                if success:
                    created_count += len(batch)
                    logger.info("Bulk created {} items", len(batch))
                else:
                    error_count += len(batch)
                    for sk in source_keys:
                        errors.append(
                            {
                                "source_key": sk,
                                "action": "create",
                                "error": result.get("error"),
                            }
                        )
            except Exception as e:
                error_count += len(batch)
                for sk in source_keys:
                    errors.append(
                        {"source_key": sk, "action": "create", "error": str(e)}
                    )
                logger.error("Bulk create failed: {}", e)

        for i in range(0, len(to_update), batch_size):
            batch = to_update[i : i + batch_size]
            item_updates = [
                {"item_id": item["item_id"], "operations": item["operations"]}
                for item in batch
            ]
            source_keys = [item["source_key"] for item in batch]

            try:
                success, result = self.airfocus_client.patch_items_bulk(
                    workspace_id, item_updates
                )
                if success:
                    updated_count += len(batch)
                    logger.info("Bulk updated {} items", len(batch))
                else:
                    error_count += len(batch)
                    for sk in source_keys:
                        errors.append(
                            {
                                "source_key": sk,
                                "action": "update",
                                "error": result.get("error"),
                            }
                        )
            except Exception as e:
                error_count += len(batch)
                for sk in source_keys:
                    errors.append(
                        {"source_key": sk, "action": "update", "error": str(e)}
                    )
                logger.error("Bulk update failed: {}", e)

        logger.info(
            "Sync completed. Created: {}, Updated: {}, Unchanged: {}, Errors: {}",
            created_count,
            updated_count,
            unchanged_count,
            error_count,
        )

        return {
            "total_issues": len(raw_issues),
            "processed_issues": len(jira_items),
            "validation_failures": validation_failures,
            "created_count": created_count,
            "updated_count": updated_count,
            "unchanged_count": unchanged_count,
            "error_count": error_count,
            "errors": errors,
        }
