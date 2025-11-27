# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import jwt
import os
import logging
from pathlib import Path
from iatoolkit.common.exceptions import IAToolkitException


class LicenseService:
    """
    Manages system restrictions and features based on a license (JWT).
    If no license or an invalid license is provided, Community Edition limits apply.
    """

    def __init__(self):
        self.public_key = self._load_public_key()
        self.limits = self._load_limits()

    def _load_public_key(self) -> str | None:
        """
        Loads the public key from the file distributed with the package.
        Expected location: src/iatoolkit/public_key.pem
        """
        try:
            # Assuming this file is located in iatoolkit/services/
            # We navigate up to the package root (iatoolkit/)
            current_dir = Path(__file__).parent.parent
            key_path = current_dir / 'public_key.pem'

            if not key_path.exists():
                logging.error(f"❌ Public key file not found at: {key_path}")
                return None

            return key_path.read_text().strip()
        except Exception as e:
            logging.error(f"❌ Error reading public key: {e}")
            return None

    def _load_limits(self):
        # 1. Define default limits (Community Edition)
        default_limits = {
            "plan": "Open Source (Community Edition)",
            "max_companies": 1,
            "max_tools": 3,
            "features": {
                "multi_tenant": False,
                "rag_advanced": False,
            }
        }

        # 2. Look for License Key in environment variable
        token = os.getenv('IAT_LICENSE_KEY')

        if not token:
            logging.info("ℹ️  No Enterprise license detected. Using Community limits.")
            return default_limits

        if not self.public_key:
            logging.warning("⚠️  Public key missing. Cannot validate license. Fallback to Community limits.")
            return default_limits

        # 3. Cryptographically validate the license
        try:
            # Validate signature (RS256) and expiration (exp) automatically
            payload = jwt.decode(token, self.public_key, algorithms=["ES256"])

            # validate some payload data
            logging.info(f"🚀 Valid Enterprise License: {payload.get('client_name')} ({payload.get('plan')})")
            return payload

        except jwt.ExpiredSignatureError:
            logging.warning("⚠️  Enterprise license has expired. Reverting to Community mode.")
            return default_limits
        except jwt.InvalidTokenError as e:
            logging.error(f"❌ Invalid license: {str(e)}. Reverting to Community mode.")
            return default_limits

    # --- Information Getters ---

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