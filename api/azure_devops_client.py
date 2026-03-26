"""
Azure DevOps API Client.

This module provides a dedicated client class for interacting with the Azure DevOps API.
"""

import requests
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from config import get_config, get_azure_devops_headers
from exceptions import APIConnectionError, APIResponseError


class AzureDevOpsClient:
    """Client for interacting with Azure DevOps REST API."""

    def __init__(self, organization: str, project: str, token: str):
        self.config = get_config()
        self.organization = organization
        self.project = project
        self.token = token
        self.base_url = f"https://dev.azure.com/{organization}/{project}"
        self.session = requests.Session()

    def validate_response(
        self,
        response: requests.Response,
        operation_name: str,
        expected_status_codes: Optional[List[int]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate API response and return standardized result.

        Args:
            response: requests.Response object
            operation_name: Name of the operation for logging
            expected_status_codes: List of acceptable status codes

        Returns:
            tuple: (success: bool, data: dict or error_dict)
        """
        if expected_status_codes is None:
            expected_status_codes = [200]

        if response.status_code in expected_status_codes:
            try:
                data = response.json()
                logger.debug("{} successful. Response: {}", operation_name, data)
                return True, data
            except Exception as e:
                error_msg = (
                    f"Failed to parse JSON response for {operation_name}: {str(e)}"
                )
                logger.error(error_msg)
                return False, {"error": error_msg}
        else:
            error_msg = f"{operation_name} failed. Status code: {response.status_code}"
            logger.error(error_msg)
            logger.error("Response: {}", response.text)
            return False, {"error": error_msg, "response": response.text}

    def get_work_items(self, work_item_type: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Fetch work items of a specific type from Azure DevOps.

        Args:
            work_item_type: Type of work items (e.g., "Epic", "Feature")

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        wiql_url = f"{self.base_url}/_apis/wit/wiql?api-version=7.0"
        headers = get_azure_devops_headers(self.token)

        query = {
            "query": f"SELECT [System.Id], [System.Title], [System.Description], [System.State], [System.AssignedTo], [System.ChangedDate], [Microsoft.VSTS.Scheduling.StartDate], [Microsoft.VSTS.Scheduling.TargetDate], [Microsoft.VSTS.Scheduling.DueDate] FROM WorkItems WHERE [System.WorkItemType] = '{work_item_type}'"
        }

        logger.info("Querying Azure DevOps for {} items...", work_item_type)

        try:
            response = self.session.post(
                wiql_url,
                headers=headers,
                json=query,
                verify=self.config.SSL_VERIFY,
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"Failed to query Azure DevOps: {str(e)}")

        success, data = self.validate_response(response, "Azure DevOps WIQL query")
        if not success:
            return False, data

        work_items = data.get("workItems", [])
        if not work_items:
            logger.info("No {} items found", work_item_type)
            return True, {"workItems": [], "items": []}

        logger.info("Found {} work items, fetching details...", len(work_items))

        ids = [str(wi["id"]) for wi in work_items]
        batch_size = 200
        all_items = []

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            ids_url = f"{self.base_url}/_apis/wit/workitems?ids={','.join(batch_ids)}&fields=System.Id,System.Title,System.Description,System.State,System.AssignedTo,System.ChangedDate,Microsoft.VSTS.Scheduling.StartDate,Microsoft.VSTS.Scheduling.TargetDate,Microsoft.VSTS.Scheduling.DueDate&$top={batch_size}&api-version=7.0"

            try:
                batch_response = self.session.get(
                    ids_url, headers=headers, verify=self.config.SSL_VERIFY, timeout=30
                )
            except requests.exceptions.RequestException as e:
                raise APIConnectionError(f"Failed to fetch work item details: {str(e)}")

            success, batch_data = self.validate_response(
                batch_response, f"Fetch work item details (batch {i // batch_size + 1})"
            )
            if success:
                all_items.extend(batch_data.get("value", []))

        return True, {"workItems": work_items, "items": all_items}
