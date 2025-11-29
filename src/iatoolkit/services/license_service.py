# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import jwt
import os
import logging
from pathlib import Path
from iatoolkit.common.exceptions import IAToolkitException
from injector import inject, singleton


@singleton
class LicenseService:
    """
    Manages system restrictions and features based on a license (JWT).
    If no license or an invalid license is provided, Community Edition limits apply.
    """
    @inject
    def __init__(self):
        self.limits = self._load_limits()

    def _load_limits(self):
        # 1. Define default limits (Community Edition)
        default_limits = {
            "license_type": "Community Edition",
            "plan": "Open Source (Community Edition)",
            "max_companies": 1,
            "max_tools": 3,
            "features": {
                "multi_tenant": False,
                "rag_advanced": False,
            }
        }
        return default_limits


    # --- Information Getters ---
    def get_license_type(self) -> str:
        return self.limits.get("license_type", "Community Edition")

    def get_plan_name(self) -> str:
        return self.limits.get("plan", "Unknown")

    def get_max_companies(self) -> int:
        return self.limits.get("max_companies", 1)

    def get_max_tools_per_company(self) -> int:
        return self.limits.get("max_tools", 3)

    def get_license_info(self) -> str:
        return f"Plan: {self.get_plan_name()}, Companies: {self.get_max_companies()}, Tools: {self.get_max_tools_per_company()}"

    # --- Restriction Validators ---

    def validate_company_limit(self, current_count: int):
        """Raises exception if the limit of active companies is exceeded."""
        limit = self.get_max_companies()
        # -1 means unlimited
        if limit != -1 and current_count > limit:
            raise IAToolkitException(
                IAToolkitException.ErrorType.PERMISSION,
                f"Company limit ({limit}) reached for plan '{self.get_plan_name()}'."
            )


    def validate_tool_config_limit(self, tools_config: list):
        """Validates a configuration list before processing it."""
        limit = self.get_max_tools_per_company()
        if limit != -1 and len(tools_config) > limit:
            raise IAToolkitException(
                IAToolkitException.ErrorType.PERMISSION,
                f"Configuration defines {len(tools_config)} tools, but limit is {limit}."
            )

    # --- Feature Gating Validators ---

    def has_feature(self, feature_key: str) -> bool:
        """Checks if a specific feature is enabled in the license."""
        features = self.limits.get("features", {})
        return features.get(feature_key, False)