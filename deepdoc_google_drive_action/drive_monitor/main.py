"""Driver Monitor Sandbox Server"""

import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from flask import Flask, jsonify, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("drive_monitor.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Flask app for webhook receiver
app = Flask(__name__)

# Global variables
active_channels = {}  # Dictionary to track active notification channels
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
WEBHOOK_URL = "https://example.com/notifications"  # Replace with your domain


# Load service account credentials
def get_credentials() -> service_account.Credentials:
    """Get service account credentials

    Returns:
        Credentials: Service account credentials object
    """

    try:
        credentials = service_account.Credentials.from_service_account_info(
            SERVICE_ACCOUNT_INFO, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return credentials
    except Exception as e:
        logger.error(f"Failed to load credentials: {e}")
        return None


# Create Drive service
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


# Create a notification channel to watch a resource (file or folder)
def create_watch_channel(
    resource_id: str, resource_type: str = "file"
) -> Optional[dict]:
    """
    Creates a notification channel for a Drive resource

    Args:
        resource_id: The ID of the Drive resource to monitor
        resource_type: Either "file" or "folder" (both are treated as files in the API)

    Returns:
        The notification channel information if successful, None otherwise
    """

    service = get_drive_service()
    if not service:
        return None

    channel_id = str(uuid.uuid4())
    channel_token = f"resource={resource_id}-{int(time.time())}"

    # Set expiration to 1 day from now (in milliseconds)
    expiration = int((datetime.now() + timedelta(days=1)).timestamp() * 1000)

    # Create channel request body
    channel_body = {
        "id": channel_id,
        "type": "web_hook",
        "address": WEBHOOK_URL,
        "token": channel_token,
        "expiration": expiration,
    }

    try:
        # Watch the resource
        response = (
            service.files().watch(fileId=resource_id, body=channel_body).execute()
        )

        # Store channel information for later management
        active_channels[channel_id] = {
            "resource_id": resource_id,
            "resource_type": resource_type,
            "channel_id": channel_id,
            "resource_uri": response.get("resourceUri"),
            "expiration": expiration,
            "created_at": datetime.now().isoformat(),
        }

        logger.info(
            f"Created watch channel for {resource_type} {resource_id}: {channel_id}"
        )
        return response
    except HttpError as e:
        logger.error(
            f"Failed to create watch channel for {resource_type} {resource_id}: {e}"
        )
        return None


# Stop a notification channel
def stop_watch_channel(channel_id: str) -> bool:
    """
    Stops an active notification channel

    Args:
        channel_id: The ID of the channel to stop

    Returns:
        True if successful, False otherwise
    """

    service = get_drive_service()
    if not service:
        return False

    logger.warning(f"Channel {active_channels} {channel_id}")

    # channel_info = {"id": "60aed5c0-0f97-4307-87f2-ac18b47f41f0", "resource_id": "qbIPQ8g2L141USt9S1U9N5rkryQ"}
    # active_channels[channel_id] = channel_info

    if channel_id not in active_channels:
        logger.warning(f"Channel {channel_id} not found in active channels")
        return False

    channel_info = active_channels[channel_id]

    logger.warning(f"channel_info {channel_info}")

    stop_body = {"id": channel_id, "resourceId": channel_info["resource_id"]}

    try:
        service.channels().stop(body=stop_body).execute()
        logger.info(
            f"Stopped watch channel {channel_id} for resource {channel_info['resource_id']}"
        )

        # Remove from active channels
        del active_channels[channel_id]
        return True
    except HttpError as e:
        logger.error(f"Failed to stop watch channel {channel_id}: {e}")
        return False


# List all active channels
def list_active_channels() -> dict[Any, Any]:
    """Returns all currently active notification channels"""

    return active_channels


# Check if a resource still exists
def check_resource_exists(resource_id: str) -> bool:
    """
    Checks if a Drive resource still exists

    Args:
        resource_id: The ID of the resource to check

    Returns:
        True if the resource exists, False otherwise
    """

    service = get_drive_service()
    if not service:
        return False

    try:
        # Try to get metadata for the resource
        service.files().get(fileId=resource_id, fields="id").execute()
        return True
    except HttpError as e:
        if e.resp.status == 404:
            # Resource not found
            logger.info(f"Resource {resource_id} no longer exists")
            return False
        else:
            logger.error(f"Error checking resource {resource_id}: {e}")
            # For other errors, assume resource still exists
            return True


# Clean up expired or invalid channels
def cleanup_channels() -> int:
    """Checks all active channels and removes those that are expired or have deleted resources"""

    channels_to_remove = []

    for channel_id, channel_info in active_channels.items():
        # Check if resource still exists
        if not check_resource_exists(channel_info["resource_id"]):
            logger.info(
                f"Resource {channel_info['resource_id']} no longer exists, removing channel {channel_id}"
            )
            stop_watch_channel(channel_id)
            channels_to_remove.append(channel_id)
            continue

        # Check if channel has expired
        expiration = channel_info["expiration"]
        current_time = int(datetime.now().timestamp() * 1000)
        if current_time > expiration:
            logger.info(f"Channel {channel_id} has expired, stopping it")
            stop_watch_channel(channel_id)
            channels_to_remove.append(channel_id)

    # Remove channels from the active_channels dictionary
    for channel_id in channels_to_remove:
        if channel_id in active_channels:
            del active_channels[channel_id]

    return len(channels_to_remove)


# Flask routes for webhook receiver and API
@app.route("/notifications", methods=["POST"])
def receive_notification() -> tuple[Any, int]:
    """Webhook endpoint to receive Drive change notifications"""

    # Extract headers
    channel_id = request.headers.get("X-Goog-Channel-ID")
    resource_id = request.headers.get("X-Goog-Resource-ID")
    resource_state = request.headers.get("X-Goog-Resource-State")
    channel_token = request.headers.get("X-Goog-Channel-Token")
    changed = request.headers.get("X-Goog-Changed", "")
    message_number = request.headers.get("X-Goog-Message-Number")

    # Create a dictionary with all request information
    request_data = {
        "timestamp": datetime.now().isoformat(),
        "method": request.method,
        "url": request.url,
        "path": request.path,
        "endpoint": request.endpoint,
        "headers": dict(request.headers),
        "args": dict(request.args),
        "form": dict(request.form),
        "cookies": dict(request.cookies),
        "remote_addr": request.remote_addr,
    }

    notification_data = {
        "channel_id": channel_id,
        "resource_id": resource_id,
        "resource_state": resource_state,
        "channel_token": channel_token,
        "changed_properties": changed.split(",") if changed else [],
        "message_number": message_number,
        "timestamp": datetime.now().isoformat(),
    }

    logger.info(f"Received notification: {json.dumps(notification_data)}")
    logger.info(f"Full notification: {request_data}")

    # Handle resource deletion
    if resource_state in ["trash", "remove"]:
        logger.info(
            f"Resource {resource_id} was {resource_state}d, stopping channel {channel_id}"
        )
        # Find all channels watching this resource
        channels_to_stop = [
            cid
            for cid, info in active_channels.items()
            if info["resource_id"] == resource_id
        ]

        for cid in channels_to_stop:
            stop_watch_channel(cid)

    # Return success to Google's notification service
    return "", 200


@app.route("/api/channels", methods=["GET"])
def get_channels() -> tuple[Any, int]:
    """API endpoint to list all active channels"""

    return jsonify(active_channels)


@app.route("/api/watch", methods=["POST"])
def watch_resource() -> tuple[Any, int]:
    """API endpoint to start watching a resource"""

    data = request.json
    resource_id = data.get("resource_id")
    resource_type = data.get("resource_type", "file")

    if not resource_id:
        return jsonify({"error": "resource_id is required"}), 400

    result = create_watch_channel(resource_id, resource_type)
    if result:
        return jsonify(result), 201
    else:
        return jsonify({"error": "Failed to create watch channel"}), 500


@app.route("/api/stop", methods=["POST"])
def stop_channel() -> tuple[Any, int]:
    """API endpoint to stop a channel"""

    data = request.json
    channel_id = data.get("channel_id")

    if not channel_id:
        return jsonify({"error": "channel_id is required"}), 400

    result = stop_watch_channel(channel_id)
    if result:
        return jsonify({"success": True}), 200
    else:
        return jsonify({"error": "Failed to stop channel"}), 500


@app.route("/api/cleanup", methods=["POST"])
def cleanup() -> tuple[Any, int]:
    """API endpoint to clean up expired channels"""

    count = cleanup_channels()
    return jsonify({"removed_channels_count": count}), 200


if __name__ == "__main__":
    # On startup, clean up any expired channels
    cleanup_channels()

    # Start the Flask server
    app.run(host="0.0.0.0", port=5000, debug=True)
