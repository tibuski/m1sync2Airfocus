"""
Base synchronization module.

This module provides common utilities and base class for sync operations.
"""

import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod
from loguru import logger

from config import get_config
from api import AirfocusClient
from exceptions import DataSaveError


class BaseSync(ABC):
    """Base class for synchronization operations."""

    def __init__(self):
        self.config = get_config()
        self.airfocus_client = AirfocusClient()

    @abstractmethod
    def fetch_data(self) -> Dict[str, Any]:
        """Fetch data from source system."""
        pass

    @abstractmethod
    def sync_to_airfocus(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sync data to Airfocus."""
        pass

    def save_to_json(
        self, data: Dict[str, Any], prefix: str, workspace_id: str = None
    ) -> str:
        """
        Save data to JSON file in data directory.

        Args:
            data: Data to save
            prefix: Filename prefix (e.g., "jira", "airfocus")
            workspace_id: Optional workspace ID for the filename

        Returns:
            Path to the saved file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if workspace_id:
            filename = f"{prefix}_{workspace_id}_{timestamp}.json"
        else:
            filename = f"{prefix}_{timestamp}.json"

        filepath = f"{self.config.DATA_DIR}/{filename}"

        try:
            os.makedirs(self.config.DATA_DIR, exist_ok=True)

            final_data = {
                "fetched_at": datetime.now().isoformat(),
                **data,
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)

            standard_filepath = f"{self.config.DATA_DIR}/{prefix}_data.json"
            with open(standard_filepath, "w", encoding="utf-8") as f:
                json.dump(final_data, f, indent=2, ensure_ascii=False)

            logger.info("Saved data to {} (standard: {})", filepath, standard_filepath)
            return filepath

        except Exception as e:
            logger.error("Failed to save data to file: {}", e)
            raise DataSaveError("Failed to save data to file", details={"error": str(e)}) from e

    def load_airfocus_items(self) -> Dict[str, Any]:
        """Load existing Airfocus items from JSON file."""
        airfocus_data_file = f"{self.config.DATA_DIR}/airfocus_data.json"
        if os.path.exists(airfocus_data_file):
            with open(airfocus_data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
