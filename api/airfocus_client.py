"""
Airfocus API Client.

This module provides a dedicated client class for interacting with the Airfocus API.
"""

import requests
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from config import get_config, get_airfocus_headers
from exceptions import APIConnectionError, APIResponseError


class AirfocusClient:
    """Client for interacting with Airfocus REST API."""

    def __init__(self):
        self.config = get_config()
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

    def get_workspace(self, workspace_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Get workspace data including fields and statuses.

        Args:
            workspace_id: The Airfocus workspace ID

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        url = f"{self.config.AIRFOCUS_REST_URL}/workspaces/{workspace_id}"
        headers = get_airfocus_headers()

        try:
            response = self.session.get(
                url, headers=headers, verify=self.config.SSL_VERIFY
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(
                f"Failed to fetch workspace {workspace_id}: {str(e)}"
            )

        return self.validate_response(response, f"Get workspace {workspace_id}")

    def get_items(self, workspace_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Get all items from a workspace.

        Args:
            workspace_id: The Airfocus workspace ID

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        url = f"{self.config.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/search"
        headers = get_airfocus_headers()

        search_payload = {"filters": {}, "pagination": {"limit": 1000, "offset": 0}}

        try:
            response = self.session.post(
                url,
                headers=headers,
                json=search_payload,
                verify=self.config.SSL_VERIFY,
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(
                f"Failed to fetch items for workspace {workspace_id}: {str(e)}"
            )

        return self.validate_response(
            response, f"Get items for workspace {workspace_id}"
        )

    def create_item(
        self, workspace_id: str, payload: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Create a new item in a workspace.

        Args:
            workspace_id: The Airfocus workspace ID
            payload: Item creation payload

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        url = f"{self.config.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items"
        headers = get_airfocus_headers()

        logger.debug("Creating Airfocus item with payload: {}", payload)

        try:
            response = self.session.post(
                url, headers=headers, json=payload, verify=self.config.SSL_VERIFY
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(
                f"Failed to create item in workspace {workspace_id}: {str(e)}"
            )

        return self.validate_response(response, "Create Airfocus item", [200, 201])

    def patch_item(
        self, workspace_id: str, item_id: str, payload: List[Dict[str, Any]]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Update an existing item in a workspace.

        Args:
            workspace_id: The Airfocus workspace ID
            item_id: The item ID to update
            payload: Patch operations list

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        url = (
            f"{self.config.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/{item_id}"
        )
        headers = get_airfocus_headers()

        logger.debug(
            "Updating Airfocus item {} with {} patch operations", item_id, len(payload)
        )

        try:
            response = self.session.patch(
                url, headers=headers, json=payload, verify=self.config.SSL_VERIFY
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"Failed to patch item {item_id}: {str(e)}")

        return self.validate_response(
            response, f"Update Airfocus item {item_id}", [200, 201]
        )

    def create_items_bulk(
        self, workspace_id: str, payloads: List[Dict[str, Any]]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Create multiple items using bulk API.

        Args:
            workspace_id: The Airfocus workspace ID
            payloads: List of item creation payloads

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        url = f"{self.config.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/bulk"
        headers = get_airfocus_headers()

        actions = [{"type": "create", "resource": p} for p in payloads]

        logger.info("Bulk creating {} items", len(payloads))

        try:
            response = self.session.post(
                url, headers=headers, json=actions, verify=self.config.SSL_VERIFY
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"Failed to bulk create items: {str(e)}")

        return self.validate_response(response, "Bulk create items", [200])

    def patch_items_bulk(
        self, workspace_id: str, item_updates: List[Dict[str, Any]]
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Update multiple items using bulk API.

        Args:
            workspace_id: The Airfocus workspace ID
            item_updates: List of dicts with item_id and patch operations

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        url = f"{self.config.AIRFOCUS_REST_URL}/workspaces/{workspace_id}/items/bulk"
        headers = get_airfocus_headers()

        actions = [
            {"type": "patch", "id": u["item_id"], "transform": u["operations"]}
            for u in item_updates
        ]

        logger.info("Bulk updating {} items", len(item_updates))

        try:
            response = self.session.post(
                url, headers=headers, json=actions, verify=self.config.SSL_VERIFY
            )
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"Failed to bulk update items: {str(e)}")

        return self.validate_response(response, "Bulk update items", [200])
