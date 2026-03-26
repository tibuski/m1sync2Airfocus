# m1sync2Airfocus

Python sync utility that synchronizes JIRA issues or Azure DevOps work items with Airfocus workspace items.

## Prerequisites

- Python (3.10+)
- `uv` installed (dependency management / runner)
- Azure CLI installed (only needed for Azure DevOps sync)
- Ability to complete `az login` (device-code/MFA) in your tenant (only needed for Azure DevOps sync)

## Installation

```powershell
# Clone the repository locally
git clone https://github.com/tibuski/m1sync2Airfocus.git

# Enter the project folder
cd m1sync2Airfocus

# Create/update virtual environment and install dependencies
uv sync

# Create your local configuration file from the template
Copy-Item .\constants.py.example .\constants.py
```

Then edit `constants.py` and fill in the required values:
- `JIRA_REST_URL` - Your JIRA instance URL
- `JIRA_PROJECT_KEY` - Your JIRA project key
- `JIRA_PAT` - Your JIRA API token
- `AIRFOCUS_WORKSPACE_ID` - From Airfocus URL
- `AIRFOCUS_API_KEY` - Your Airfocus API key

## Getting API Credentials

**JIRA Personal Access Token:**
1. Go to JIRA → Account Settings → Security → API tokens
2. Create API token and copy it

**Airfocus API Key:**
1. Go to Airfocus → Settings → API Keys
2. Generate new API key and copy it

**Airfocus Workspace ID:**
- Find it in your Airfocus workspace URL: `https://app.airfocus.com/workspaces/YOUR-WORKSPACE-ID/...`

## Usage

Run the sync with either `--jira` or `--azure-devops` flag:

```powershell
# Sync JIRA issues to Airfocus
uv run .\main.py --jira

# Sync Azure DevOps work items to Airfocus
uv run .\main.py --azure-devops
```

Run without arguments to display help:
```powershell
# Show CLI help
uv run .\main.py
```

## Azure DevOps Configuration

In `constants.py`:
- `AZURE_DEVOPS_URL` (required) - Azure DevOps URL (e.g., `https://dev.azure.com/org/project`)
- `AZURE_DEVOPS_WORK_ITEM_TYPE` (required) - Work item type to export (e.g. `"Epic"`, `"User Story"`)
- `AZURE_TENANT_ID` (optional) - Tenant ID used for Azure CLI login token acquisition (helps avoid tenant selection prompts)
- `AZURE_DEVOPS_RESOURCE` (required) - Azure DevOps audience GUID (static; normally do not change)
- `AZURE_CLI_PYTHON_EXE` / `AZURE_CLI_BAT_PATH` (optional) - Azure CLI locations (helps when running under `uv run`)
- `DATE_RANGE_FIELD` (optional) - Airfocus date-range field name to populate from Azure DevOps dates

Example:
```python
DATE_RANGE_FIELD = "Date range"
```

Azure DevOps source fields are handled internally (`Microsoft.VSTS.Scheduling.StartDate` and `Microsoft.VSTS.Scheduling.TargetDate`, with fallback to `Microsoft.VSTS.Scheduling.DueDate`).

The Azure DevOps sync will:
- Perform `az login --use-device-code` (interactive)
- Export the configured work item type from the configured org/project
- Sync to Airfocus (source of truth: Azure DevOps)

## Setup Requirements

No custom fields required in Airfocus. The source key is stored in the item description with a sync warning header for duplicate detection.

## Configuration Options

All configuration is done in `constants.py`. Here are the available options:

| Variable | Description | Default |
|----------|-------------|---------|
| `JIRA_REST_URL` | JIRA API endpoint | Required |
| `JIRA_PROJECT_KEY` | JIRA project key to sync | Required |
| `JIRA_PAT` | JIRA Personal Access Token | Required |
| `AZURE_DEVOPS_URL` | Azure DevOps URL | Required (for --azure-devops) |
| `AZURE_DEVOPS_WORK_ITEM_TYPE` | Azure DevOps work item type | Required (for --azure-devops) |
| `AZURE_TENANT_ID` | Azure tenant ID for Azure CLI auth | Optional |
| `AZURE_DEVOPS_RESOURCE` | Azure DevOps audience GUID | `499b84ac-1321-427f-aa17-267ca6975798` |
| `AIRFOCUS_REST_URL` | Airfocus API endpoint | `https://app.airfocus.com/api` |
| `AIRFOCUS_WORKSPACE_ID` | Airfocus workspace ID | Required |
| `AIRFOCUS_API_KEY` | Airfocus API Key | Required |
| `LOGGING_LEVEL` | Console log verbosity (DEBUG, INFO, WARNING, ERROR) | `WARNING` |
| `LOG_FILE_PATH` | Path to log file (always stores DEBUG logs) | `data/jira2airfocus.log` |
| `SSL_VERIFY` | Enable SSL certificate verification | `False` |
| `DATA_DIR` | Directory for data files | `data` |
| `JIRA_TO_AIRFOCUS_STATUS_MAPPING` | Map JIRA statuses to Airfocus | Optional |
| `AZURE_DEVOPS_TO_AIRFOCUS_STATUS_MAPPING` | Map Azure DevOps statuses to Airfocus | Optional |
| `TEAM_FIELD` | Auto-assign team to items | Optional |
| `AZURE_CLI_PYTHON_EXE` | Azure CLI bundled python.exe path | Optional |
| `AZURE_CLI_BAT_PATH` | Azure CLI az.bat path | Optional |
| `DATE_RANGE_FIELD` | Airfocus date-range field name to populate | Optional |
