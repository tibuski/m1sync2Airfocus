"""
JIRA Item Class

This module provides a class-based approach to handling JIRA items,
encapsulating the data parsing, validation, and transformation logic.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import re


@dataclass
class JiraAssignee:
    """Represents a JIRA assignee."""

    display_name: str = ""
    email_address: str = ""
    account_id: str = ""

    @classmethod
    def from_jira_data(
        cls, assignee_data: Optional[Dict[str, Any]]
    ) -> Optional["JiraAssignee"]:
        """Create JiraAssignee from JIRA API data."""
        if not assignee_data:
            return None

        return cls(
            display_name=assignee_data.get("displayName", ""),
            email_address=assignee_data.get("emailAddress", ""),
            account_id=assignee_data.get("accountId", ""),
        )

    def to_markdown(self) -> str:
        """Convert assignee to markdown format."""
        if not self.display_name:
            return ""

        text = self.display_name
        if self.email_address:
            text += f" ({self.email_address})"
        return text


@dataclass
class JiraStatus:
    """Represents a JIRA status."""

    name: str = ""
    id: str = ""
    category_key: str = ""
    category_name: str = ""

    @classmethod
    def from_jira_data(
        cls, status_data: Optional[Dict[str, Any]]
    ) -> Optional["JiraStatus"]:
        """Create JiraStatus from JIRA API data."""
        if not status_data:
            return None

        status_category = status_data.get("statusCategory", {})

        return cls(
            name=status_data.get("name", ""),
            id=status_data.get("id", ""),
            category_key=status_category.get("key", "") if status_category else "",
            category_name=status_category.get("name", "") if status_category else "",
        )


@dataclass
class JiraAttachment:
    """Represents a JIRA attachment."""

    filename: str = ""
    url: str = ""
    thumbnail: Optional[str] = None

    @classmethod
    def from_jira_data(cls, attachment_data: Dict[str, Any]) -> "JiraAttachment":
        """Create JiraAttachment from JIRA API data or simplified data."""
        # Handle both raw JIRA API format (uses 'content') and simplified format (uses 'url')
        attachment_url = attachment_data.get("url") or attachment_data.get(
            "content", ""
        )

        return cls(
            filename=attachment_data.get("filename", ""),
            url=attachment_url,
            thumbnail=attachment_data.get("thumbnail")
            if attachment_data.get("thumbnail")
            else None,
        )

    def to_markdown(self) -> str:
        """Convert attachment to markdown link."""
        if not self.url:
            # If no URL, just show filename without link
            return f"- {self.filename}"
        return f"- [{self.filename}]({self.url})"

    def is_valid(self) -> bool:
        """Check if the attachment has both filename and URL."""
        return bool(self.filename and self.url)

    def __str__(self) -> str:
        """String representation of the attachment."""
        return f"JiraAttachment(filename='{self.filename}', url='{self.url}')"


@dataclass
class JiraItem:
    """
    Represents a JIRA item with methods for data processing and transformation.

    This class encapsulates all the logic for handling JIRA items,
    including field extraction, data validation, and format conversion.
    """

    key: str
    url: str
    summary: str = ""
    description: str = ""
    status: Optional[JiraStatus] = None
    assignee: Optional[JiraAssignee] = None
    attachments: List[JiraAttachment] = None
    updated: str = ""
    project_key: str = ""

    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.attachments is None:
            self.attachments = []

    @classmethod
    def from_jira_api_data(
        cls, issue_data: Dict[str, Any], project_key: str, base_url: str
    ) -> "JiraItem":
        """
        Create JiraItem from raw JIRA API response data.

        Args:
            issue_data: Raw JIRA issue data from API
            project_key: JIRA project key
            base_url: JIRA base URL for constructing issue URL

        Returns:
            JiraItem instance populated with JIRA data
        """
        issue_key = issue_data.get("key", "")
        fields = issue_data.get("fields", {})

        # Process attachments
        raw_attachments = fields.get("attachment", [])
        attachments = [JiraAttachment.from_jira_data(att) for att in raw_attachments]

        # Process the updated timestamp - clean format
        raw_updated = fields.get("updated", "")
        clean_updated = cls._clean_timestamp(raw_updated)

        # Create status and assignee objects
        status = JiraStatus.from_jira_data(fields.get("status"))
        assignee = JiraAssignee.from_jira_data(fields.get("assignee"))

        return cls(
            key=issue_key,
            url=f"{base_url}/browse/{issue_key}",
            summary=fields.get("summary", ""),
            description=fields.get("description", ""),
            status=status,
            assignee=assignee,
            attachments=attachments,
            updated=clean_updated,
            project_key=project_key,
        )

    @classmethod
    def from_simplified_data(cls, simplified_issue: Dict[str, Any]) -> "JiraItem":
        """
        Create JiraItem from simplified issue dictionary structure.

        Args:
            simplified_issue: Dictionary containing simplified JIRA issue data

        Returns:
            JiraItem instance populated with simplified data
        """
        # Process attachments
        raw_attachments = simplified_issue.get("attachments", [])
        attachments = [JiraAttachment.from_jira_data(att) for att in raw_attachments]

        # Create status and assignee objects
        status = JiraStatus.from_jira_data(simplified_issue.get("status"))
        assignee = JiraAssignee.from_jira_data(simplified_issue.get("assignee"))

        return cls(
            key=simplified_issue.get("key", ""),
            url=simplified_issue.get("url", ""),
            summary=simplified_issue.get("summary", ""),
            description=simplified_issue.get("description", ""),
            status=status,
            assignee=assignee,
            attachments=attachments,
            updated=simplified_issue.get("updated", ""),
            project_key="",  # Not available in simplified format
        )

    @staticmethod
    def _clean_timestamp(raw_timestamp: str) -> str:
        """
        Clean JIRA timestamp format.

        Args:
            raw_timestamp: Raw timestamp from JIRA API

        Returns:
            Cleaned timestamp string
        """
        if not raw_timestamp:
            return ""

        # Remove .000 milliseconds and timezone info to get standard format
        # Convert "2025-05-09T12:05:52.000+0200" to "2025-05-09T12:05:52"
        return re.sub(r"\.000\+\d{4}$", "", raw_timestamp)

    def build_markdown_description(self) -> str:
        """
        Build enhanced Markdown description for Airfocus.

        Returns:
            Formatted Markdown content for Airfocus description
        """
        markdown_parts = []

        # Add sync warning in italic
        markdown_parts.append("*---------- Do Not Edit, Used for Sync ----------*")

        # Add JIRA Issue with link
        markdown_parts.append(f"**JIRA Issue:** [{self.key}]({self.url})")

        # Add JIRA Description URL as link
        markdown_parts.append(f"**JIRA Description:** [{self.url}]({self.url})")

        # Add assignee if available
        if self.assignee and self.assignee.display_name:
            assignee_text = self.assignee.to_markdown()
            markdown_parts.append(f"**JIRA Assignee:** {assignee_text}")

        # Add attachments if there are any
        if self.attachments:
            valid_attachments = [att for att in self.attachments if att.is_valid()]
            if valid_attachments:
                markdown_parts.append("**JIRA Attachments:**")
                for attachment in valid_attachments:
                    markdown_parts.append(
                        f"- [{attachment.filename}]({attachment.url})"
                    )

        # Add closing separator in italic (just dashes)
        markdown_parts.append("*---------------------------------------------------*")

        return "\n".join(markdown_parts)

    def get_status_name(self) -> str:
        """Get the status name, or empty string if no status."""
        return self.status.name if self.status else ""

    def get_assignee_display_name(self) -> str:
        """Get the assignee display name, or empty string if no assignee."""
        return self.assignee.display_name if self.assignee else ""

    def has_attachments(self) -> bool:
        """Check if the item has any attachments."""
        return bool(self.attachments)

    def get_valid_attachments(self) -> List[JiraAttachment]:
        """Get only the valid attachments (those with both filename and URL)."""
        return [att for att in self.attachments if att.is_valid()]

    def get_invalid_attachments(self) -> List[JiraAttachment]:
        """Get invalid attachments (those missing filename or URL)."""
        return [att for att in self.attachments if not att.is_valid()]

    def validate(self) -> List[str]:
        """
        Validate the JIRA item data.

        Returns:
            List of validation error messages, empty if valid
        """
        errors = []

        if not self.key:
            errors.append("JIRA key is required")

        if not self.summary:
            errors.append("Summary is required")

        if not self.url:
            errors.append("URL is required")

        # Validate key format (basic check)
        if self.key and not re.match(r"^[A-Z]+-\d+$", self.key):
            errors.append(f"Invalid JIRA key format: {self.key}")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert JiraItem back to dictionary format for compatibility.

        Returns:
            Dictionary representation of the JIRA item
        """
        return {
            "key": self.key,
            "url": self.url,
            "summary": self.summary,
            "description": self.description,
            "status": {
                "name": self.status.name,
                "id": self.status.id,
                "statusCategory": {
                    "key": self.status.category_key,
                    "name": self.status.category_name,
                }
                if self.status.category_key
                else None,
            }
            if self.status
            else None,
            "assignee": {
                "displayName": self.assignee.display_name,
                "emailAddress": self.assignee.email_address,
                "accountId": self.assignee.account_id,
            }
            if self.assignee
            else None,
            "attachments": [
                {"filename": att.filename, "url": att.url, "thumbnail": att.thumbnail}
                for att in self.attachments
            ],
            "updated": self.updated,
        }

    def __str__(self) -> str:
        """String representation of the JIRA item."""
        return f"JiraItem({self.key}: {self.summary})"

    def __repr__(self) -> str:
        """Detailed string representation of the JIRA item."""
        return f"JiraItem(key='{self.key}', summary='{self.summary}', status='{self.get_status_name()}')"
