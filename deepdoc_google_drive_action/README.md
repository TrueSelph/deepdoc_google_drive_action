# DeepDoc Google Drive Integration Action (with Watcher)

## Package Information

- **Name:** jivas/deepdoc_google_drive_action
- **Author:** AA
- **Architype:** DeepDocGoogleDriveAction
- **Version:** 0.0.3

## Meta Information

- **Title:** DeepDoc Google Drive Integration Action (with Watcher)
- **Description:** Ingests, manages, and watches documents/folders from Google Drive using the DeepDoc client for vector storage and processing. Automatically reacts to changes in watched Google Drive resources.
- **Group:** integration
- **Type:** action

## Features (Version 0.0.3)

- **Google Drive Document Ingestion:**
  - Ingests individual files or all files within specified Google Drive folders.
  - Downloads content and queues it to a configured `DeepDocClientAction` for processing and vector storage.
  - Stores Google Drive metadata (file ID, folder ID, filename, MIME type) with the document in DeepDoc, ensuring correct folder association even for webhook-triggered re-ingestions.
- **Google Drive Watcher (Push Notifications):**
  - **Start/Stop Watching:** Allows starting and stopping watches on specific Google Drive files or folders.
    - **Corrected Watcher Logic (v0.0.3):** Ensures that when ingesting a folder (either initially or due to a webhook for a watched folder), a single watch is correctly established on the *folder itself*, rather than creating multiple watchers for individual files within it.
  - **Webhook Receiver:** Includes `gdrive_notification_receiver_walker` to handle incoming change notifications from Google Drive.
  - **Automatic Re-ingestion/Deletion:**
    - On "change" notification for a watched resource, automatically re-ingests the updated file/folder contents into DeepDoc.
    - On "trash" or "remove" notification, automatically removes the corresponding document(s) from DeepDoc and stops the watch if appropriate.
  - **Channel Renewal:** A `pulse` ability, schedulable via `PulseAction`, automatically renews active watch channels before they expire.
  - **Watch Recovery:** An `on_enable` hook and `recover_watches` ability attempt to re-establish watches for resources listed in the DAF configuration (`watched_gdrive_resources`) after an agent restart.
- **Vector Store Management:**
  - Remove individual Google Drive files or entire folders (and their contents) from the DeepDoc vector store, including managing associated watchers.
- **Configuration & UI:**
  - Configurable via agent DAF for Google Cloud Service Account credentials, DeepDoc action label, default GDrive folder, and comprehensive watcher settings.
  - Streamlit UI (`app/app.py`) for:
    - Managing Google Drive credentials.
    - Triggering manual ingestion.
    - Managing Google Drive watchers (start, stop, list active, trigger manual renewal/recovery).
    - Viewing and managing documents ingested from Google Drive (via DeepDoc's manifest).

## Configuration (To be set in Agent DAF context for this action)

- **`watched_gdrive_resources`** (List[Dict], default: `[]`):
  - A list of Google Drive resources that the action should persistently try to watch.
  - Each item is a dictionary, e.g., `{"gdrive_id": "your_folder_or_file_id", "type": "folder"}`. The `type` field ("file" or "folder") is now used by the watcher logic to determine how to watch the resource.
- **`default_webhook_base_url`** (str, default: `""` or `JIVAS_BASE_URL` env var):
  - Your Jiva instance's publicly accessible base URL (e.g., `https://my-jiva.example.com`). **Crucial for Google Drive to send notifications.**
- **`auto_watch_on_ingest`** (bool, default: `true`):
  - Whether to automatically attempt to start watching a GDrive resource after it has been ingested.
- **`pulse_interval_seconds`** (int, default: `3600`):
  - How often the `pulse` ability runs to check and renew watch channels.
- **`renew_threshold_hours`** (int, default: `6`):
  - If a watch channel's expiration is within this many hours, it will be renewed.
- **`default_folder_id`** (str, optional): Default Google Drive folder ID for operations if not specified.
- **`deepdoc_action_label`** (str, default: `"DeepDocClientAction"`): Label of the `DeepDocClientAction` used.
- **`scopes`** (list, default: `["https://www.googleapis.com/auth/drive.readonly"]`): Google API scopes.
- **Service Account Credentials:** (All string values, `private_key` is multiline)
  - `project_id`, `private_key_id`, `private_key`, `client_email`, `client_id`, `auth_uri`, `token_uri`, `auth_provider_x509_cert_url`, `client_x509_cert_url`, `universe_domain`.

## Core Abilities (Callable via Walkers or Internally)

- **`ingest_drive_items(drive_ids: List[str], item_type: str, user_metadata: Optional[Dict])`**: Ingests from GDrive to DeepDoc and manages `auto_watch_on_ingest`.
- **`remove_drive_item_from_vector_store(google_drive_file_id: str)`**: Removes a GDrive file from DeepDoc and its watch.
- **`remove_drive_folder_from_vector_store(google_drive_folder_id: str)`**: Removes GDrive folder contents from DeepDoc and its watch.
- **`start_watching_resource(gdrive_resource_id: str, resource_type: str, webhook_base_url: Optional[str])`**: Starts a new watch (for "file" or "folder").
- **`stop_watching_resource(jiva_channel_uuid: str, initiated_by_user: bool)`**: Stops an active watch.
- **`renew_watch_channel(jiva_channel_uuid: str)`**: Manually triggers renewal of a watch.
- **`list_active_watches()`**: Returns a list of Jiva-managed active watches.
- **`process_drive_notification(headers: Dict, body_str: str)`**: Handles GDrive webhook events.
- **`pulse()`**: Scheduled ability to renew watch channels.
- **`recover_watches(webhook_base_url: Optional[str])`**: Re-establishes watches from DAF config.
- **`healthcheck()`**: Checks GDrive/DeepDoc/Webhook URL connectivity.
- **UI Helpers:** `list_gdrive_folder_contents`, `get_ingested_documents_from_drive`.

## Walkers

- **`gdrive_notification_receiver_walker`**: Webhook endpoint for Google Drive push notifications.
- **`manage_gdrive_watch_walker`**: UI walker to start/stop/list/renew/recover watches.
- (Existing walkers for ingestion and direct management: `ingest_gdrive_items_walker`, `remove_gdrive_item_walker`, `clear_gdrive_folder_walker`, `list_gdrive_folder_contents_walker`, `get_ingested_gdrive_docs_walker`).

## Dependencies

- **Jiva Actions:**
  - `jivas/deepdoc_client_action`: For interacting with the DeepDoc service.
  - `jivas/pulse_action`: For scheduling the watch renewal `pulse`.
- **Python Libraries:**
  - `google-api-python-client` (>=2.80.0 recommended)
  - `google-auth` (>=2.14.0 recommended)
  - `google-auth-httplib2` (>=0.1.0 recommended)
  - (Ensure these are in the Jiva environment's `requirements.txt` or specified in the action's `info.yaml` pip dependencies).

## Setup Notes

1.  **Google Cloud Project:** Ensure the Google Drive API is enabled.
2.  **Service Account:** Create and download a Service Account key JSON. Configure credentials in the agent's DAF for this action.
3.  **Public Jiva URL:** The `default_webhook_base_url` (or `JIVAS_BASE_URL` env var) **must** point to your publicly accessible Jiva instance for Google to send notifications.
4.  **DAF Configuration:**
    - Populate all Google Service Account credentials.
    - Set `default_webhook_base_url`.
    - Configure `watched_gdrive_resources` with resources (and their `type`: "file" or "folder") to monitor automatically upon agent startup. Example: `{"gdrive_id": "your_id", "type": "folder"}`.
5.  **Dependent Actions:** Ensure `DeepDocClientAction` and `PulseAction` are correctly configured and enabled for the agent.
6.  **Google Drive Changes API:** This action now utilizes the `changes().watch()` and `files().watch()` API for push notifications. The `page_token` for `changes` API is managed internally to process changes since the last notification.