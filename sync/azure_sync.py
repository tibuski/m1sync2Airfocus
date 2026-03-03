"""
Azure DevOps synchronization module.

This module provides functionality to sync Azure DevOps work items to Airfocus.
"""

from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from sync.base import BaseSync
from api import AzureDevOpsClient
from models import AirfocusItem
from models.azure_devops import AzureCliConfig, get_devops_token_via_azure_cli


class AzureDevOpsSync(BaseSync):
    """Handles synchronization from Azure DevOps to Airfocus."""

    def __init__(self):
        super().__init__()

    def get_token(self) -> Optional[str]:
        """Acquire Azure DevOps access token via Azure CLI."""
        config = AzureCliConfig(
            devops_resource=self.config.AZURE_DEVOPS_RESOURCE,
            az_cli_python_exe=getattr(self.config, "AZURE_CLI_PYTHON_EXE", None),
            az_cli_bat_path=getattr(self.config, "AZURE_CLI_BAT_PATH", None),
        )

        tenant_id = getattr(self.config, "AZURE_TENANT_ID", None)
        if tenant_id:
            logger.info("Using tenant: {}", tenant_id)

        logger.info("Acquiring Azure DevOps token via Azure CLI...")
        token = get_devops_token_via_azure_cli(config, tenant_id)

        if token:
            logger.info(
                "Successfully acquired Azure DevOps token (length: {})", len(token)
            )
        else:
            logger.error("Failed to acquire Azure DevOps token")

        return token

    def parse_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse Azure DevOps URL to extract organization and project."""
        if not url.startswith("https://dev.azure.com/"):
            return None, None

        parts = url.replace("https://dev.azure.com/", "").split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        return None, None

    def fetch_data(self) -> Dict[str, Any]:
        """Fetch Azure DevOps work items."""
        token = self.get_token()
        if not token:
            return {"error": "Failed to acquire Azure DevOps token"}

        organization, project = self.parse_url(self.config.AZURE_DEVOPS_URL)
        if not organization or not project:
            return {"error": "Invalid AZURE_DEVOPS_URL format"}

        work_item_type = self.config.AZURE_DEVOPS_WORK_ITEM_TYPE
        logger.info("Fetching Azure DevOps {} items...", work_item_type)
        logger.info("Organization: {}, Project: {}", organization, project)

        client = AzureDevOpsClient(organization, project, token)
        logger.info("Calling Azure DevOps API...")
        success, data = client.get_work_items(work_item_type)
        logger.info(
            "API call result - success: {}, data keys: {}",
            success,
            list(data.keys()) if data else "None",
        )

        if not success:
            logger.error("Failed to fetch Azure DevOps data: {}", data.get("error"))
            return data

        result = {
            "organization": organization,
            "project": project,
            "work_item_type": work_item_type,
            "total_items": len(data.get("items", [])),
            "workItems": data.get("workItems", []),
            "items": data.get("items", []),
        }

        self.save_to_json(result, "azure_devops", work_item_type.lower())
        self.cleanup_old_files(
            f"azure_devops_{work_item_type.lower()}_*.json", keep_count=10
        )

        logger.info(
            "Successfully fetched {} Azure DevOps items", len(data.get("items", []))
        )
        return result

    def sync_to_airfocus(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sync Azure DevOps work items to Airfocus."""
        workspace_id = self.config.AIRFOCUS_WORKSPACE_ID
        organization = data.get("organization")
        project = data.get("project")
        raw_items = data.get("items", [])

        airfocus_data = self.load_airfocus_items()
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

        to_create = []
        to_update = []

        for azure_item in raw_items:
            azure_id = azure_item["id"]
            title = azure_item["fields"].get("System.Title", "")
            state = azure_item["fields"].get("System.State", "")
            assignee = azure_item["fields"].get("System.AssignedTo")

            existing = airfocus_by_azure_id.get(str(azure_id))

            airfocus_item = AirfocusItem.from_azure_devops_item(
                organization,
                project,
                self.config.AZURE_DEVOPS_WORK_ITEM_TYPE,
                azure_id,
                title,
                state,
                assignee,
            )

            validation_errors = airfocus_item.validate()
            if validation_errors:
                logger.warning(
                    "Validation failed for Azure DevOps item {}: {}",
                    azure_id,
                    ", ".join(validation_errors),
                )

            if existing:
                to_update.append(
                    {
                        "item_id": existing.item_id,
                        "azure_id": str(azure_id),
                        "operations": airfocus_item.to_patch_payload(),
                    }
                )
            else:
                to_create.append(
                    {
                        "item": airfocus_item,
                        "azure_id": str(azure_id),
                    }
                )

        batch_size = 50

        for i in range(0, len(to_create), batch_size):
            batch = to_create[i : i + batch_size]
            payloads = [item["item"].to_create_payload() for item in batch]
            azure_ids = [item["azure_id"] for item in batch]

            try:
                success, result = self.airfocus_client.create_items_bulk(
                    workspace_id, payloads
                )
                if success:
                    created_count += len(batch)
                    logger.info("Bulk created {} items", len(batch))
                else:
                    error_count += len(batch)
                    for az_id in azure_ids:
                        errors.append(
                            {
                                "azure_id": az_id,
                                "action": "create",
                                "error": result.get("error"),
                            }
                        )
            except Exception as e:
                error_count += len(batch)
                for az_id in azure_ids:
                    errors.append(
                        {"azure_id": az_id, "action": "create", "error": str(e)}
                    )
                logger.error("Bulk create failed: {}", e)

        for i in range(0, len(to_update), batch_size):
            batch = to_update[i : i + batch_size]
            item_updates = [
                {"item_id": item["item_id"], "operations": item["operations"]}
                for item in batch
            ]
            azure_ids = [item["azure_id"] for item in batch]

            try:
                success, result = self.airfocus_client.patch_items_bulk(
                    workspace_id, item_updates
                )
                if success:
                    updated_count += len(batch)
                    logger.info("Bulk updated {} items", len(batch))
                else:
                    error_count += len(batch)
                    for az_id in azure_ids:
                        errors.append(
                            {
                                "azure_id": az_id,
                                "action": "update",
                                "error": result.get("error"),
                            }
                        )
            except Exception as e:
                error_count += len(batch)
                for az_id in azure_ids:
                    errors.append(
                        {"azure_id": az_id, "action": "update", "error": str(e)}
                    )
                logger.error("Bulk update failed: {}", e)

        logger.info(
            "Sync completed. Created: {}, Updated: {}, Errors: {}",
            created_count,
            updated_count,
            error_count,
        )

        return {
            "total_items": len(raw_items),
            "created_count": created_count,
            "updated_count": updated_count,
            "error_count": error_count,
            "errors": errors,
        }
