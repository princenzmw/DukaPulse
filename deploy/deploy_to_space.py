"""Deploy DukaPulse Kiosk to Hugging Face Spaces using HfApi."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi

ROOT_DIR = Path(__file__).resolve().parents[1]

def deploy():
    load_dotenv(ROOT_DIR / ".env")
    hf_token = os.environ.get("HF_TOKEN")
    database_url = os.environ.get("DATABASE_URL")

    if not hf_token:
        print("ERROR: HF_TOKEN not found in environment or .env", file=sys.stderr)
        sys.exit(1)
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment or .env", file=sys.stderr)
        sys.exit(1)

    api = HfApi(token=hf_token)
    user_info = api.whoami()
    username = user_info["name"]
    repo_id = f"{username}/dukapulse"
    space_url = f"https://huggingface.co/spaces/{repo_id}"
    direct_url = f"https://{username}-dukapulse.hf.space"

    print(f"Deploying to Hugging Face Space: {repo_id}")
    print(f"Space URL: {space_url}")
    print(f"Direct URL: {direct_url}")

    # 1. Create or ensure Space repository exists with docker SDK
    print("1. Creating Space repository (docker SDK)...")
    api.create_repo(
        repo_id=repo_id,
        repo_type="space",
        space_sdk="docker",
        exist_ok=True,
    )

    # 2. Configure secrets and variables
    print("2. Configuring Space secrets & variables...")
    # Normalize DATABASE_URL to postgresql+psycopg:// if needed
    db_normalized = database_url.strip()
    if db_normalized.startswith("postgres://"):
        db_normalized = "postgresql+psycopg://" + db_normalized[len("postgres://"):]
    elif db_normalized.startswith("postgresql://") and not db_normalized.startswith("postgresql+"):
        db_normalized = "postgresql+psycopg://" + db_normalized[len("postgresql://"):]

    api.add_space_secret(repo_id=repo_id, key="DATABASE_URL", value=db_normalized)
    print("  Secret DATABASE_URL: set")

    try:
        api.add_space_variable(repo_id=repo_id, key="DEV_MODE_MOCK_AUTH", value="true")
        print("  Variable DEV_MODE_MOCK_AUTH: set to 'true'")
    except Exception as e:
        print(f"  Note on variable DEV_MODE_MOCK_AUTH: {e}")
        # If variable fails (some free accounts require secret instead), set as secret
        api.add_space_secret(repo_id=repo_id, key="DEV_MODE_MOCK_AUTH", value="true")

    # 3. Upload repository contents
    print("3. Uploading repository contents to Space...")
    ignore_list = [
        ".git/**",
        ".git",
        ".venv/**",
        ".venv*/**",
        "venv/**",
        "**/__pycache__/**",
        "*.pyc",
        ".pytest_cache/**",
        ".ruff_cache/**",
        "*.db",
        "*.sqlite3",
        ".env",
        "scratch/**",
        "scratch",
    ]

    commit_info = api.upload_folder(
        repo_id=repo_id,
        repo_type="space",
        folder_path=str(ROOT_DIR),
        commit_message="Deploy DukaPulse micro-retail kiosk to Hugging Face Spaces",
        ignore_patterns=ignore_list,
    )
    print(f"  Upload successful: commit {commit_info.oid[:8] if hasattr(commit_info, 'oid') else 'complete'}")

    # 4. Monitor Space build and runtime status
    print("4. Monitoring Space runtime status...")
    max_wait_seconds = 600
    start_time = time.time()
    last_stage = None

    while time.time() - start_time < max_wait_seconds:
        runtime = api.get_space_runtime(repo_id=repo_id)
        stage = runtime.stage
        if stage != last_stage:
            print(f"  Space stage: {stage} (elapsed: {int(time.time() - start_time)}s)")
            last_stage = stage

        if stage in ("RUNNING", "APP_STARTING"):
            if stage == "RUNNING":
                print("  Space is RUNNING!")
                break
        elif stage in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR"):
            print(f"  Space entered error state: {stage}", file=sys.stderr)
            break

        time.sleep(10)

    return repo_id, space_url, direct_url

if __name__ == "__main__":
    deploy()
