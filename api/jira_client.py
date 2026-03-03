"""
JIRA API Client.

This module provides a dedicated client class for interacting with the JIRA API.
"""

import requests
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from config import get_config, get_jira_headers
from exceptions import APIConnectionError, APIResponseError


class JiraClient:
    """Client for interacting with JIRA REST API."""

    def __init__(self):
        self.config = get_config()
        self.base_url = self.config.JIRA_REST_URL.replace("/rest/api/latest", "")
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

    def get_issues(
        self, project_key: str, max_results: int = 100
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Fetch JIRA issues for a project with pagination.

        Args:
            project_key: The JIRA project key
            max_results: Number of issues per page

        Returns:
            Tuple of (success, data_or_error_dict)
        """
        all_issues = []
        start_at = 0
        total_issues = None

        url = f"{self.config.JIRA_REST_URL}/search"
        headers = get_jira_headers()

        while True:
            query = {
                "jql": f"project = {project_key} AND issuetype = Epic",
                "fields": [
                    "key",
                    "summary",
                    "description",
                    "status",
                    "assignee",
                    "attachment",
                    "updated",
                ],
                "expand": ["names"],
                "startAt": start_at,
                "maxResults": max_results,
            }

            logger.info(
                "Requesting issues {} to {}", start_at, start_at + max_results - 1
            )

            try:
                response = self.session.post(
                    url,
                    headers=headers,
                    json=query,
                    verify=self.config.SSL_VERIFY,
                    timeout=30,
                )
            except requests.exceptions.ConnectionError as e:
                raise APIConnectionError(
                    f"Connection error while fetching JIRA project {project_key}: {str(e)}"
                )
            except requests.exceptions.Timeout as e:
                raise APIConnectionError(
                    f"Timeout error while fetching JIRA project {project_key}: {str(e)}"
                )
            except requests.exceptions.RequestException as e:
                raise APIConnectionError(
                    f"Request error while fetching JIRA project {project_key}: {str(e)}"
                )

            if response.status_code != 200:
                raise APIResponseError(
                    f"Failed to fetch JIRA project {project_key}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            data = response.json()
            raw_issues = data.get("issues", [])

            for issue in raw_issues:
                all_issues.append(issue)

            if total_issues is None:
                total_issues = data.get("total", 0)
                logger.info(
                    "Found {} total issues for project {}", total_issues, project_key
                )

            if len(raw_issues) < max_results or len(all_issues) >= total_issues:
                break

            start_at += max_results

        return True, {
            "project_key": project_key,
            "total_issues": len(all_issues),
            "issues": all_issues,
        }
