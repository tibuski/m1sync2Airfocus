"""
Airfocus Item Class

This module provides a class-based approach to handling Airfocus items,
encapsulating the data transformation and API payload generation logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import re
from loguru import logger

if TYPE_CHECKING:
    from .jira_item import JiraItem

import constants
from .utils import (
    get_mapped_status_id,
    get_airfocus_field_id,
    get_airfocus_field_option_id,
)


@dataclass
class AirfocusItem:
    """
    Represents an Airfocus item with methods for creation and updates.

    This class encapsulates all the logic for handling Airfocus items,
    including field mappings, payload generation, and validation.
    """

    name: str
    source_key: str
    description: str = ""
    status_id: Optional[str] = None
    team_field_value: Optional[str] = None
    color: str = "blue"
    item_id: Optional[str] = None
    assignee_user_ids: List[str] = None
    assignee_user_group_ids: List[str] = None
    order: int = 0
    azure_devops_id: Optional[str] = None

    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.assignee_user_ids is None:
            self.assignee_user_ids = []
        if self.assignee_user_group_ids is None:
            self.assignee_user_group_ids = []

    @classmethod
    def from_jira_item(cls, jira_item: JiraItem) -> AirfocusItem:
        """
        Create AirfocusItem from JiraItem object.

        Args:
            jira_item: JiraItem instance containing JIRA issue data

        Returns:
            AirfocusItem instance populated with JIRA data
        """
        source_key = jira_item.key
        name = jira_item.summary
        description = jira_item.build_markdown_description()

        # Get status mapping using shared utility function
        jira_status_name = jira_item.get_status_name()
        status_id = get_mapped_status_id(
            jira_status_name, source_key, constants.JIRA_TO_AIRFOCUS_STATUS_MAPPING
        )

        # Get team field value from constants
        team_field_value = None
        if constants.TEAM_FIELD:
            for field_name, field_values in constants.TEAM_FIELD.items():
                team_field_value = field_values[0] if field_values else None
                break

        return cls(
            name=name,
            source_key=source_key,
            description=description,
            status_id=status_id,
            team_field_value=team_field_value,
        )

    @classmethod
    def from_azure_devops_item(
        cls,
        organization: str,
        project: str,
        work_item_type: str,
        azure_devops_id: int,
        title: str,
        state: str,
        assignee: Optional[Dict[str, Any]] = None,
    ) -> "AirfocusItem":
        """
        Create AirfocusItem from Azure DevOps work item.

        Args:
            organization: Azure DevOps organization name
            project: Azure DevOps project name
            work_item_type: Work item type (e.g., "Feature", "Epic")
            azure_devops_id: Azure DevOps work item ID
            title: Work item title
            state: Work item state
            assignee: Work item assignee dict (optional)

        Returns:
            AirfocusItem instance populated with Azure DevOps data
        """
        source_key = f"ADO-{azure_devops_id}"
        name = title

        status_id = get_mapped_status_id(
            state, source_key, constants.AZURE_DEVOPS_TO_AIRFOCUS_STATUS_MAPPING
        )

        team_field_value = None
        if constants.TEAM_FIELD:
            for field_name, field_values in constants.TEAM_FIELD.items():
                team_field_value = field_values[0] if field_values else None
                break

        ad_description = build_azure_devops_markdown_description(
            organization,
            project,
            work_item_type,
            azure_devops_id,
            assignee,
        )

        return cls(
            name=name,
            source_key=source_key,
            description=ad_description,
            status_id=status_id,
            team_field_value=team_field_value,
            azure_devops_id=str(azure_devops_id),
        )

    @classmethod
    def from_airfocus_data(cls, airfocus_data: Dict[str, Any]) -> "AirfocusItem":
        """
        Create AirfocusItem from existing Airfocus API data.

        Args:
            airfocus_data: Dictionary containing Airfocus item data

        Returns:
            AirfocusItem instance populated with Airfocus data
        """
        # Extract source key from description
        # JIRA format: JIRA-123, Azure DevOps format: Feature-123 or ADO-123
        description_raw = airfocus_data.get("description", "")
        if isinstance(description_raw, dict):
            blocks = description_raw.get("blocks", [])

            def extract_all_text(obj):
                texts = []
                if isinstance(obj, dict):
                    if obj.get("type") == "text":
                        texts.append(obj.get("content", ""))
                    else:
                        for value in obj.values():
                            texts.extend(extract_all_text(value))
                elif isinstance(obj, list):
                    for item in obj:
                        texts.extend(extract_all_text(item))
                return texts

            description_text = "".join(extract_all_text(blocks))
        else:
            description_text = str(description_raw) if description_raw else ""

        # Try ADO-123 format for Azure DevOps items (note: \d+ for any number of digits)
        ad_key_match = re.search(r"(ADO-\d+)", description_text)
        source_key = ad_key_match.group(1) if ad_key_match else ""
        azure_devops_id = ""
        if ad_key_match:
            azure_devops_id = ad_key_match.group(1).replace("ADO-", "")

        # If not found, try JIRA format: JIRA-123 (only 1-3 digits)
        if not source_key:
            source_key_match = re.search(r"([A-Z]{2,10}-\d{1,3})", description_text)
            source_key = source_key_match.group(1) if source_key_match else ""

        if source_key:
            logger.debug(
                "Extracted source key: {} from description: {}",
                source_key,
                description_text[:50],
            )
        elif description_text:
            logger.debug(
                "Could not extract source key from description: {}",
                description_text[:100],
            )

        return cls(
            name=airfocus_data.get("name", ""),
            source_key=source_key,
            description=description_text,
            status_id=airfocus_data.get("statusId", ""),
            color=airfocus_data.get("color", "blue"),
            item_id=airfocus_data.get("id", ""),
            assignee_user_ids=airfocus_data.get("assigneeUserIds", []),
            assignee_user_group_ids=airfocus_data.get("assigneeUserGroupIds", []),
            order=airfocus_data.get("order", 0),
            azure_devops_id=azure_devops_id,
        )

    def _get_team_field_configuration(
        self,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get team field configuration from constants.

        Returns:
            tuple: (field_name, field_id, team_field_value)

        Raises:
            ValueError: If multiple team fields are configured
        """
        if not constants.TEAM_FIELD:
            return None, None, None

        if len(constants.TEAM_FIELD) > 1:
            raise ValueError(
                f"Multiple team fields configured: {list(constants.TEAM_FIELD.keys())}. "
                "Only one team field is supported."
            )

        for field_name, field_values in constants.TEAM_FIELD.items():
            field_id = get_airfocus_field_id(field_name)
            if field_id:
                team_value = field_values[0] if field_values else None
                return field_name, field_id, team_value
            else:
                logger.error(
                    "Team field '{}' not found in Airfocus field mappings", field_name
                )

        return None, None, None

    def _build_fields_dict(self) -> Dict[str, Dict[str, Any]]:
        """
        Build the fields dictionary for API payloads.

        Returns:
            Dictionary containing field mappings for the API
        """
        fields_dict = {}

        # Add team field if available
        if self.team_field_value:
            field_name, team_field_id, _ = self._get_team_field_configuration()
            if team_field_id and field_name:
                team_option_id = get_airfocus_field_option_id(
                    field_name, self.team_field_value
                )
                if team_option_id:
                    fields_dict[team_field_id] = {"selection": [team_option_id]}
                    logger.debug(
                        "Added team field {}: {} (option ID: {})",
                        team_field_id,
                        self.team_field_value,
                        team_option_id,
                    )
                else:
                    logger.error(
                        "Could not find option ID for team value '{}' in field '{}'",
                        self.team_field_value,
                        field_name,
                    )

        return fields_dict

    def to_create_payload(self) -> Dict[str, Any]:
        """
        Generate payload for POST /items API call.

        Returns:
            Dictionary containing the complete payload for item creation
        """
        fields_dict = self._build_fields_dict()

        payload = {
            "name": self.name,
            "description": {"markdown": self.description, "richText": True},
            "statusId": self.status_id,
            "color": self.color,
            "assigneeUserIds": self.assignee_user_ids,
            "assigneeUserGroupIds": self.assignee_user_group_ids,
            "order": self.order,
            "fields": fields_dict,
        }

        return payload

    def to_patch_payload(self) -> List[Dict[str, Any]]:
        """
        Generate JSON Patch operations for PATCH /items/{id} API call.

        Returns:
            List of JSON Patch operations
        """
        patch_operations = []

        # Update name
        patch_operations.append({"op": "replace", "path": "/name", "value": self.name})

        # Update description (as string when using markdown media type)
        patch_operations.append(
            {"op": "replace", "path": "/description", "value": self.description}
        )

        # Update status if we have one
        if self.status_id:
            patch_operations.append(
                {"op": "replace", "path": "/statusId", "value": self.status_id}
            )

        # Update team field if available
        if self.team_field_value:
            field_name, team_field_id, _ = self._get_team_field_configuration()
            if team_field_id and field_name:
                team_option_id = get_airfocus_field_option_id(
                    field_name, self.team_field_value
                )
                if team_option_id:
                    patch_operations.append(
                        {
                            "op": "replace",
                            "path": f"/fields/{team_field_id}",
                            "value": {"selection": [team_option_id]},
                        }
                    )
                    logger.debug(
                        "Updated team field {}: {} (option ID: {})",
                        team_field_id,
                        self.team_field_value,
                        team_option_id,
                    )
                else:
                    logger.error(
                        "Could not find option ID for team value '{}' in field '{}' for update",
                        self.team_field_value,
                        field_name,
                    )

        return patch_operations

    def validate(self) -> List[str]:
        """
        Validate item data and return list of errors.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.name.strip():
            errors.append("Item name cannot be empty")

        if not self.source_key.strip() and not self.azure_devops_id:
            errors.append("Either JIRA key or Azure DevOps ID must be present")

        if not self.source_key.strip() and not self.azure_devops_id:
            errors.append("JIRA key cannot be empty")

        # Validate team field configuration if specified
        if self.team_field_value:
            field_name, team_field_id, _ = self._get_team_field_configuration()
            if not team_field_id:
                errors.append("Team field not found in Airfocus field mappings")

        return errors

    def __str__(self) -> str:
        """String representation of the item."""
        return f"AirfocusItem(source_key='{self.source_key}', name='{self.name[:50]}...', item_id='{self.item_id}')"

    def __repr__(self) -> str:
        """Detailed string representation of the item."""
        return (
            f"AirfocusItem(name='{self.name}', source_key='{self.source_key}', "
            f"status_id='{self.status_id}', item_id='{self.item_id}')"
        )


def build_azure_devops_markdown_description(
    organization: str,
    project: str,
    work_item_type: str,
    work_item_id: int,
    assignee: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build enhanced Markdown description for Airfocus from Azure DevOps data.

    Args:
        organization: Azure DevOps organization name
        project: Azure DevOps project name
        work_item_type: Work item type (e.g., "Feature", "Epic", "User Story")
        work_item_id: Azure DevOps work item ID
        assignee: Work item assignee dict with displayName (optional)

    Returns:
        Formatted Markdown content for Airfocus description
    """
    markdown_parts = []

    work_item_url = (
        f"https://dev.azure.com/{organization}/{project}/_workitems/edit/{work_item_id}"
    )

    markdown_parts.append("*---------- Do Not Edit, Used for Sync ----------*")

    markdown_parts.append(
        f"**Azure DevOps Issue:** [ADO-{work_item_id}]({work_item_url})"
    )

    markdown_parts.append(
        f"**Azure DevOps Description:** [{work_item_type}-{work_item_id}]({work_item_url})"
    )

    if assignee:
        display_name = assignee.get("displayName")
        if display_name:
            unique_name = assignee.get("uniqueName", "")
            if unique_name:
                markdown_parts.append(
                    f"**Azure DevOps Assignee:** {display_name} ({unique_name})"
                )
            else:
                markdown_parts.append(f"**Azure DevOps Assignee:** {display_name}")

    markdown_parts.append("*---------------------------------------------------*")

    return "\n".join(markdown_parts)
