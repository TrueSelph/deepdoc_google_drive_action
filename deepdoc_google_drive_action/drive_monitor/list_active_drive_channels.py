#!/usr/bin/env python3
"""
Google Drive Notification Channels Lister

This script lists all active notification channels for Google Drive resources.
"""

import argparse
import json
import logging
from typing import Any, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Replace with your service account file path or info
SERVICE_ACCOUNT_INFO = {
    "type": "",
    "project_id": "",
    "private_key_id": "",
    "private_key": "",  # Handle escaped newlines from YAML
    "client_email": "",
    "client_id": "",
    "auth_uri": "",
    "token_uri": "",
    "auth_provider_x509_cert_url": "",
    "client_x509_cert_url": "",
    "universe_domain": "",
}  # Dictionary represention your service account key file
# SERVICE_ACCOUNT_INFO = {...}  # Your service account JSON data


def get_credentials() -> service_account.Credentials:
    """Load service account credentials"""
    try:
        credentials = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_INFO, scopes=["https://www.googleapis.com/auth/drive"]
        )
        # Alternatively, use this if you have the service account info in code
        # credentials = service_account.Credentials.from_service_account_info(
        #     SERVICE_ACCOUNT_INFO,
        #     scopes=['https://www.googleapis.com/auth/drive']
        # )
        return credentials
    except Exception as e:
        logger.error(f"Failed to load credentials: {e}")
        return None


def get_drive_service() -> Optional[Any]:
    """Create a Drive API service"""
    credentials = get_credentials()
    if not credentials:
        return None

    try:
        service = build("drive", "v3", credentials=credentials)
        return service
    except Exception as e:
        logger.error(f"Failed to build Drive service: {e}")
        return None


def list_active_channels() -> Optional[dict]:
    """List all active notification channels for the authenticated service account"""
    service = get_drive_service()
    if not service:
        logger.error("Failed to create Drive service")
        return None

    try:
        # Try to get all active channels
        # Note: Google Drive API doesn't have a direct method to list channels
        # We need to use the channels.list method under the Drive API

        # Unfortunately, there's no direct API method to list all active channels
        # The best practice is to maintain your own database of active channels
        logger.info(
            "Google Drive API doesn't provide a direct way to list all active channels."
        )
        logger.info("Checking for channels in local storage...")

        # Try to read stored channels from a file
        try:
            with open("active_channels.json", "r") as f:
                active_channels = json.load(f)
                logger.info(f"Found {len(active_channels)} channels in local storage")
                return active_channels
        except FileNotFoundError:
            logger.warning("No local active_channels.json file found")
        except json.JSONDecodeError:
            logger.error("Error parsing active_channels.json")

        logger.info(
            "To properly track channels, store channel information when you create them"
        )
        return {}
    except Exception as e:
        logger.error(f"Error listing channels: {e}")
        return None


def get_channel_status(channel_id: str, resource_id: str) -> dict:
    """
    Check if a specific channel is still active

    Args:
        channel_id: The ID of the channel
        resource_id: The resource ID this channel is monitoring

    Returns:
        Dictionary with status information
    """
    service = get_drive_service()
    if not service:
        return {"status": "unknown", "error": "Failed to create Drive service"}

    # Unfortunately, there's no direct API method to get the status of a specific channel
    # The best approach is to try to stop the channel and see if it succeeds

    logger.info(f"Checking status for channel {channel_id} on resource {resource_id}")

    # If you want to verify if the channel is still active, you'd need to attempt
    # a stop operation, which would be destructive if you just want to check status

    # For this script, we'll just return what we know about the channel
    return {
        "channel_id": channel_id,
        "resource_id": resource_id,
        "status": "presumed active",
        "note": "Google Drive API doesn't provide a method to check channel status without stopping it",
    }


def list_watched_files() -> list:
    """List files being watched based on stored channels"""
    active_channels = list_active_channels()
    if not active_channels:
        return []

    service = get_drive_service()
    if not service:
        return []

    watched_files = []
    for channel_id, channel_info in active_channels.items():
        try:
            resource_id = channel_info.get("resource_id")
            if not resource_id:
                continue

            file_info = (
                service.files()
                .get(fileId=resource_id, fields="id, name, mimeType, modifiedTime")
                .execute()
            )

            watched_files.append(
                {
                    "file_id": file_info.get("id"),
                    "name": file_info.get("name"),
                    "type": file_info.get("mimeType"),
                    "last_modified": file_info.get("modifiedTime"),
                    "channel_id": channel_id,
                    "expiration": channel_info.get("expiration"),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to get info for file {resource_id}: {e}")

    return watched_files


def main() -> None:
    """Main function to handle command line arguments and execute the script"""

    parser = argparse.ArgumentParser(
        description="List Google Drive notification channels"
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--check-file", action="store_true", help="Check watched files")
    args = parser.parse_args()

    # Get active channels
    active_channels = list_active_channels()

    if args.json:
        print(json.dumps(active_channels, indent=2))
    else:
        print("\n=== Active Google Drive Notification Channels ===\n")
        if not active_channels:
            print("No active channels found or unable to retrieve channels.")
            print(
                "Note: Google Drive API doesn't provide a direct method to list all channels."
            )
            print("Channels must be tracked when they are created.")
        else:
            for channel_id, channel_info in active_channels.items():
                print(f"Channel ID: {channel_id}")
                print(f"Resource ID: {channel_info.get('resource_id', 'unknown')}")
                print(f"Resource Type: {channel_info.get('resource_type', 'unknown')}")
                print(f"Expiration: {channel_info.get('expiration', 'unknown')}")
                print(f"Created At: {channel_info.get('created_at', 'unknown')}")
                print("-" * 40)

    # If requested, check watched files
    if args.check_file:
        watched_files = list_watched_files()
        if args.json:
            print(json.dumps(watched_files, indent=2))
        else:
            print("\n=== Files Being Watched ===\n")
            if not watched_files:
                print("No watched files found or unable to retrieve file information.")
            else:
                for file in watched_files:
                    print(f"File Name: {file.get('name', 'unknown')}")
                    print(f"File ID: {file.get('file_id', 'unknown')}")
                    print(f"File Type: {file.get('type', 'unknown')}")
                    print(f"Last Modified: {file.get('last_modified', 'unknown')}")
                    print(f"Channel ID: {file.get('channel_id', 'unknown')}")
                    print(f"Channel Expiration: {file.get('expiration', 'unknown')}")
                    print("-" * 40)


if __name__ == "__main__":
    main()
