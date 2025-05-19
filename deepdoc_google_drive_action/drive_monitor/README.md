# Google Drive Resource Monitoring Sandbox - Setup Guide

This sandbox allows you to test Google Drive resource monitoring using service accounts. It specifically focuses on watching files and folders and handling deletion events automatically.

## Prerequisites

1. A Google Cloud project with the Google Drive API enabled
2. A service account with appropriate permissions
3. A publicly accessible server to receive webhooks (or use ngrok for testing)
4. Python 3.6+ installed

## Setup Instructions

### 1. Create a Service Account

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **IAM & Admin** > **Service Accounts**
3. Click **Create Service Account**
4. Enter a name and description for your service account
5. Grant the service account the **Drive API > Drive API File Scope** permission
6. Click **Create Key** and select JSON
7. Save the key file as `service-account-key.json` in the same directory as the sandbox code

### 2. Set Up Webhook Endpoint

The sandbox requires a publicly accessible HTTPS endpoint to receive notifications. For development, you can use [ngrok](https://ngrok.com/):

```bash
# Install ngrok if you haven't already
pip install pyngrok

# Start ngrok to expose your local Flask server
ngrok http 8080
```

Update the `WEBHOOK_URL` in the code with your ngrok URL (or your permanent webhook URL).

### 3. Share Drive Resources with the Service Account

For the service account to monitor resources:

1. Get the service account email from the service-account-key.json file
2. Share the Google Drive files/folders you want to monitor with this email address
3. Grant at least "Viewer" permission

### 4. Install Dependencies

```bash
pip install flask google-api-python-client google-auth-httplib2 google-auth-oauthlib pyopenssl
```

### 5. Run the Sandbox

```bash
python drive_monitor_sandbox.py
```

## Using the Sandbox

### Start Watching a Resource

Use the `/api/watch` endpoint:

```bash
curl -X POST http://localhost:8080/api/watch \
  -H "Content-Type: application/json" \
  -d '{"resource_id": "your-drive-file-or-folder-id", "resource_type": "file"}'
```

### List Active Channels

```bash
curl http://localhost:8080/api/channels
```

### Stop a Specific Channel

```bash
curl -X POST http://localhost:8080/api/stop \
  -H "Content-Type: application/json" \
  -d '{"channel_id": "the-channel-id-to-stop"}'
```

### Clean Up Expired or Invalid Channels

```bash
curl -X POST http://localhost:8080/api/cleanup
```

## Monitoring Events

The sandbox logs all notifications to `drive_monitor.log`. You can monitor this file to see events in real-time:

```bash
tail -f drive_monitor.log
```

## Key Features

1. **Automatic Channel Cleanup**: When a resource is deleted or moved to trash, the corresponding notification channel is automatically stopped
2. **Webhook Receiver**: Processes incoming notifications from Google Drive API
3. **Channel Management**: Track active notification channels and their expiration
4. **Resource Verification**: Periodically checks if monitored resources still exist

## Testing Scenarios

1. **File Update**: Edit a monitored file and save it
2. **File Deletion**: Delete a monitored file
3. **Folder Changes**: Add or remove files from a monitored folder
4. **Permission Changes**: Change sharing settings for a monitored resource

## Notes

- Notification channels expire after 1 day (maximum allowed by the Google Drive API for files)
- The sandbox includes a cleanup routine to remove expired channels
- For production use, implement proper authentication for the API endpoints