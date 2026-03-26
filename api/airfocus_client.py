"""
Airfocus API Client.

This module provides a dedicated client class for interacting with the Airfocus API.
"""

import json
import os
import time
from datetime import datetime
import requests
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from config import get_config, get_airfocus_headers
from exceptions import APIConnectionError


class AirfocusClient:
    """Client for interacting with Airfocus REST API."""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.config = get_config()
        self.session = requests.Session()
        self.max_retries = max_retries
        self.base_delay = base_delay

    @staticmethod
    def _summarize_response_data(data: Any) -> str:
        """Return a compact summary of a parsed JSON payload for debug logging."""
        if isinstance(data, dict):
            keys = list(data.keys())
            summary_parts = [f"keys={keys[:10]}"]

            for count_key in ["items", "issues", "workItems", "value", "fields"]:
                value = data.get(count_key)
                if isinstance(value, (list, dict)):
                    summary_parts.append(f"{count_key}={len(value)}")

            embedded = data.get("_embedded")
            if isinstance(embedded, dict):
                summary_parts.append(f"_embedded_keys={list(embedded.keys())[:10]}")

            return ", ".join(summary_parts)

        if isinstance(data, list):
            return f"list_len={len(data)}"

        return f"type={type(data).__name__}"

    def _request_with_retry(
        self,
        method: str,
        url: str,
        retry_on: Optional[List[int]] = None,
        **kwargs,
    ) -> requests.Response:
        """Make HTTP request with exponential backoff retry."""
        if retry_on is None:
            retry_on = [429, 500, 502, 503, 504]

        delay = self.base_delay

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)

                if response.status_code in retry_on:
                    if attempt < self.max_retries:
                        logger.warning(
                            "Request to {} failed with status {}, retrying in {:.1f}s (attempt {}/{})",
                            url,
                            response.status_code,
                            delay,
                            attempt + 1,
                            self.max_retries + 1,
                        )
                        time.sleep(delay)
                        delay *= 2
                        continue

                return response

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries:
                    logger.warning(
                        "Request exception for {}: {}, retrying in {:.1f}s",
                        url,
                        str(e),
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise

        raise APIConnectionError(f"Max retries exceeded for {url}")

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
                logger.debug(
                    "{} successful. Response summary: {}",
                    operation_name,
                    self._summarize_response_data(data),
                )
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

    def _save_data_file(self, data: Dict[str, Any], filename: str) -> str:
        """Persist JSON data in the configured data directory."""
        os.makedirs(self.config.DATA_DIR, exist_ok=True)
        filepath = f"{self.config.DATA_DIR}/{filename}"

        with open(filepath, "w", encoding="utf-8") as file_handle:
            json.dump(data, file_handle, indent=2, ensure_ascii=False)

        return filepath

    @staticmethod
    def _extract_field_value(field_data: Dict[str, Any]) -> str:
        """Normalize a field value for field metadata extraction."""
        if "text" in field_data:
            return field_data.get("text", "")
        if "value" in field_data:
            return str(field_data.get("value", ""))
        if "displayValue" in field_data:
            return field_data.get("displayValue", "")
        return ""

    @staticmethod
    def _simplify_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the item fields needed by the sync process."""
        return {
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

    def get_workspace_field_data(
        self,
        workspace_id: str,
        workspace_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Fetch workspace field metadata, derive field values, and persist it."""
        success, data = self.get_workspace(workspace_id)
        if not success:
            return False, data

        logger.info("Successfully retrieved workspace data for {}", workspace_id)

        embedded = data.get("_embedded", {})
        fields = list(embedded.get("fields", {}).values())
        statuses = list(embedded.get("statuses", {}).values())

        field_data: Dict[str, Any] = {
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

        field_values: Dict[str, List[str]] = {}
        id_to_name_mapping = {
            field_id: field_name
            for field_name, field_id in field_data["field_mapping"].items()
        }

        try:
            items = workspace_items
            if items is None:
                items_success, items_data = self.get_items(workspace_id)
                if not items_success:
                    return False, items_data
                items = items_data.get("items", [])

            for item in items:
                for field_id, field_data_obj in item.get("fields", {}).items():
                    field_name = id_to_name_mapping.get(field_id)
                    if not field_name:
                        continue

                    field_values.setdefault(field_name, [])
                    field_value = self._extract_field_value(field_data_obj)
                    if field_value and field_value not in field_values[field_name]:
                        field_values[field_name].append(field_value)

            logger.info(
                "Extracted field values for {} fields from workspace items",
                len(field_values),
            )
        except Exception as exc:
            logger.warning("Failed to derive workspace field values: {}", exc)

        field_data["field_values"] = field_values

        try:
            filepath = self._save_data_file(field_data, "airfocus_fields.json")
            logger.info(
                "Successfully saved {} field definitions, {} statuses, and field values to {}",
                len(fields),
                len(statuses),
                filepath,
            )
            return True, field_data
        except Exception as exc:
            error_msg = f"Failed to save field data: {exc}"
            logger.error(error_msg)
            return False, {"error": error_msg}

    def get_workspace_project_data(self, workspace_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Fetch workspace items, simplify them, and persist snapshot files."""
        logger.info("Requesting Airfocus items for workspace {}", workspace_id)

        success, data = self.get_items(workspace_id)
        if not success:
            return False, data

        try:
            raw_items = data.get("items", [])
            all_items = [self._simplify_item(item) for item in raw_items]

            logger.info(
                "Found {} total items in Airfocus workspace {}",
                len(all_items),
                workspace_id,
            )

            final_data = {
                "workspace_id": workspace_id,
                "total_items": len(all_items),
                "fetched_at": datetime.now().isoformat(),
                "items": all_items,
            }

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"airfocus_{workspace_id}_items_{timestamp}.json"
            filepath = self._save_data_file(final_data, filename)
            self._save_data_file(final_data, "airfocus_data.json")

            logger.info("Successfully saved {} items to {}", len(all_items), filepath)
            return True, final_data
        except Exception as exc:
            error_msg = f"Exception occurred while fetching Airfocus data: {exc}"
            logger.error(error_msg)
            return False, {"error": error_msg}

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

        response = self._request_with_retry(
            "GET", url, headers=headers, verify=self.config.SSL_VERIFY
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

        limit = 1000
        offset = 0
        all_items: List[Dict[str, Any]] = []
        last_response_data: Dict[str, Any] = {}

        while True:
            search_payload = {"filters": {}, "pagination": {"limit": limit, "offset": offset}}

            response = self._request_with_retry(
                "POST",
                url,
                headers=headers,
                json=search_payload,
                verify=self.config.SSL_VERIFY,
            )

            success, data = self.validate_response(
                response, f"Get items for workspace {workspace_id} (offset {offset})"
            )
            if not success:
                return False, data

            page_items = data.get("items", [])
            all_items.extend(page_items)
            last_response_data = data

            logger.debug(
                "Fetched {} Airfocus items at offset {} for workspace {}",
                len(page_items),
                offset,
                workspace_id,
            )

            if len(page_items) < limit:
                break

            offset += limit

        paginated_data = dict(last_response_data)
        paginated_data["items"] = all_items
        paginated_data["totalItems"] = len(all_items)
        return True, paginated_data

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

        response = self._request_with_retry(
            "POST", url, headers=headers, json=payload, verify=self.config.SSL_VERIFY
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

        response = self._request_with_retry(
            "PATCH", url, headers=headers, json=payload, verify=self.config.SSL_VERIFY
        )

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

        response = self._request_with_retry(
            "POST", url, headers=headers, json=actions, verify=self.config.SSL_VERIFY
        )

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

        response = self._request_with_retry(
            "POST", url, headers=headers, json=actions, verify=self.config.SSL_VERIFY
        )

        return self.validate_response(response, "Bulk update items", [200])
