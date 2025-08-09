# Changelog

## 0.1.0
  - Updated to support Jivas 2.1.0

## 0.0.3 - Refined Watcher Logic & Stability

- **Fixes:**
  - **Corrected Watcher Creation for Initial Folder Ingestion:** Resolved an issue where ingesting a folder with `auto_watch_on_ingest: true` would incorrectly attempt to create individual file watchers for each item in the folder. The logic now correctly identifies that the ingestion was for a folder and establishes a single watch on the parent folder ID itself, preventing multiple redundant file watchers. This was due to a key mismatch when checking the context of the ingestion trigger within the `ingest_drive_items` ability.
  - Ensured `default_webhook_base_url` is consistently initialized and used, including fallback to `JIVAS_BASE_URL` environment variable during `on_enable` and subsequent operations if not set in DAF.
  - Corrected usage of `self.get_label()` when interacting with `PulseAction` for scheduling `pulse` ability, ensuring the correct action instance is targeted.
- **Improvements:**
  - Added more specific logging within the watcher creation logic in `ingest_drive_items` to clarify whether a file watch or folder watch is being initiated based on the ingestion context.
  - Clarified logic in `start_watching_resource` to check for existing watches on the *exact* GDrive resource ID and *type* (file/folder) before creating a new one, further preventing duplicates.
  - Refined parameter passing for `resource_type` in `start_watching_resource` and `renew_watch_channel` to ensure consistency.
  - Minor improvements to logging messages for clarity in watch management and notification processing.
- **Chores:**
  - General code cleanup and comment consistency.

## 0.0.2 - GDrive Watcher & Enhanced Management

- **New Features:**
  - Implemented Google Drive Push Notifications (Watcher) for files.
    - Action can now start/stop watches on GDrive resources.
    - Added `gdrive_notification_receiver_walker` to process incoming change notifications from Google Drive.
    - Notifications for "change" trigger re-ingestion into DeepDoc.
    - Notifications for "trash" or "remove" trigger deletion from DeepDoc and stop the watch.
  - Automatic Watch Channel Renewal:
    - Added `pulse` ability, schedulable via `PulseAction`.
    - `pulse` periodically checks active watch channels and renews them before expiration.
  - Watch Recovery:
    - Added `recover_watches` ability, typically called on action `on_enable`.
    - Attempts to re-establish watches for resources defined in DAF config (`watched_gdrive_resources`).
  - Persistent "Intended Watches":
    - New DAF configuration `watched_gdrive_resources` (list of GDrive IDs) to specify which resources should be monitored persistently.
  - Webhook Base URL Configuration:
    - Added `default_webhook_base_url` DAF configuration.
    - Action falls back to `JIVAS_BASE_URL` environment variable if DAF config is not set.
  - Enhanced UI Walkers & App:
    - Added `manage_gdrive_watch_walker` for UI to start, stop, list, and manually renew/recover watches.
    - Updated `app/app.py` with sections to manage watchers, view active watches, and trigger watch operations.
- **Improvements:**
  - Refined `PulseAction` integration for scheduling the `pulse` ability using `self.get_label()`.
  - Improved logging for watch management and notification processing.
  - `on_enable` now attempts to recover watches and start the pulse scheduler.
  - `on_disable` now stops the pulse scheduler and attempts to clean up active Google Drive watch channels.
  - `healthcheck` ability updated slightly to be aware of webhook URL configuration needs.
- **Fixes:**
  - Corrected Jaclang syntax for block scoping (`{}`) and statement termination (`;`).
  - Ensured correct usage of `#` for comments in Jaclang code.
  - Corrected relative import paths for Python modules within the action.

## 0.0.1 - Initial Release

- **Features:**
  - Core integration with Google Drive for document ingestion.
    - `GoogleDriveHandler` Python module for API interactions (list files, get metadata, download content).
    - Service Account authentication for Google Drive.
  - Integration with `DeepDocClientAction` for document processing and vector storage.
    - `ingest_drive_items` ability to download from GDrive and queue to DeepDoc.
    - `remove_drive_item_from_vector_store` ability to remove GDrive-originated items from DeepDoc.
    - `remove_drive_folder_from_vector_store` ability.
  - Basic UI Walkers:
    - `ingest_gdrive_items_walker`
    - `remove_gdrive_item_walker`
    - `clear_gdrive_folder_walker`
    - `list_gdrive_folder_contents_walker`
    - `get_ingested_gdrive_docs_walker`
  - Streamlit UI (`app/app.py`) for:
    - Configuring Google Drive credentials.
    - Triggering ingestion of files/folders.
    - Listing and managing ingested documents (from DeepDoc manifest).
  - `healthcheck` ability for basic GDrive and DeepDoc connectivity.
  - DAF configurable Google Drive credentials and DeepDoc action label.