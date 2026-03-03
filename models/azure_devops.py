"""Azure DevOps integration models.

Currently contains helpers for acquiring an AAD access token via Azure CLI.
This is primarily used for test/export scripts when PATs are disabled.

The token acquisition is intentionally implemented here (model layer) so other
scripts can reuse it without duplicating subprocess logic.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import shutil
from typing import Optional


@dataclass(frozen=True)
class AzureCliConfig:
    """Configuration required to invoke Azure CLI in this environment.

    Note: This model intentionally does not hard-code environment-specific defaults.
    Provide all values from `constants.py` (via utilities) so the same code works
    across different machines/OSes.
    """

    devops_resource: str

    # Optional. If provided and exists, we run `<python.exe> -m azure.cli ...` to
    # avoid venv/module issues under uv.
    az_cli_python_exe: Optional[str] = None

    # Optional. If provided and exists, we run `az.bat ...`.
    az_cli_bat_path: Optional[str] = None


def build_az_command(config: AzureCliConfig, args: list[str]) -> Optional[list[str]]:
    """Build a command line to execute Azure CLI."""
    if config.az_cli_python_exe and os.path.exists(config.az_cli_python_exe):
        return [config.az_cli_python_exe, "-m", "azure.cli", *args]

    if config.az_cli_bat_path and os.path.exists(config.az_cli_bat_path):
        return [config.az_cli_bat_path, *args]

    az_on_path = shutil.which("az")
    if az_on_path:
        return [az_on_path, *args]

    return None


def azure_cli_env() -> dict:
    """Environment variables to make Azure CLI less interactive."""
    env = os.environ.copy()
    env.setdefault("AZURE_CORE_DISABLE_CONFIRM_PROMPT", "1")
    env.setdefault("AZURE_CORE_NO_COLOR", "1")
    return env


def get_devops_token_via_azure_cli(config: AzureCliConfig) -> Optional[str]:
    """Login with device-code and return an access token for Azure DevOps."""

    login_args = [
        "login",
        "--use-device-code",
        "--allow-no-subscriptions",
        "--only-show-errors",
        "-o",
        "none",
    ]

    try:
        result = subprocess.run(
            ["az", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
        import json

        version_info = json.loads(result.stdout)
        cli_version = version_info.get("azure-cli", "")
        major = int(cli_version.split(".")[0]) if cli_version else 0
        if major >= 2:
            login_args.append("--skip-subscription-selection")
    except Exception:
        pass

    login_cmd = build_az_command(config, login_args)

    token_cmd = build_az_command(
        config,
        [
            "account",
            "get-access-token",
            "--resource",
            config.devops_resource,
            "--query",
            "accessToken",
            "-o",
            "tsv",
            "--only-show-errors",
        ],
    )

    if not login_cmd or not token_cmd:
        return None

    # Interactive login (will prompt for device code and tenant selection)
    subprocess.run(login_cmd, check=False, env=azure_cli_env())

    # Token retrieval
    print("Retrieving access token...")
    try:
        result = subprocess.run(
            token_cmd,
            capture_output=True,
            text=True,
            env=azure_cli_env(),
            timeout=30,
        )
        if result.returncode != 0:
            print(f"Token retrieval failed: {result.stderr}")
            return None
        token = result.stdout.strip()
        if not token:
            print("Token retrieval returned empty")
            return None
        print("Token retrieved successfully")
        return token
    except subprocess.TimeoutExpired:
        print("Token retrieval timed out")
        return None
    except Exception as e:
        print(f"Token retrieval error: {e}")
        return None
