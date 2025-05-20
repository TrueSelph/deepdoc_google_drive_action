"""Google Drive API handler for file operations."""

import io
import logging
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

logger = logging.getLogger(__name__)


class GoogleDriveHandler:
    """Google Drive API handler for file operations."""

    def __init__(self, credentials_info: dict, scopes: list) -> None:
        """
        Initializes the Google Drive API service.
        :param credentials_info: Dictionary containing service account credentials.
        :param scopes: List of scopes for API access.
        """
        try:
            self.creds = service_account.Credentials.from_service_account_info(
                credentials_info, scopes=scopes
            )
            self.service = build("drive", "v3", credentials=self.creds)
            logger.info("Google Drive API service initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive API service: {e}")
            self.service = None
            self.creds = None  # Ensure creds is also None if service init fails

    def is_healthy(self) -> bool:
        """Checks if the service object was initialized."""
        return self.service is not None

    def list_files_in_folder(
        self,
        folder_id: str,
        page_size: int = 100,
        fields: str = "nextPageToken, files(id, name, mimeType, webViewLink, modifiedTime, parents)",
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Lists files and folders within a given folder ID."""

        if not self.is_healthy():
            return {"error": "Google Drive service not initialized."}
        items = []
        page_token = None
        try:
            while True:
                response = (
                    self.service.files()
                    .list(
                        q=f"'{folder_id}' in parents and trashed=false",  # Exclude trashed files
                        pageSize=page_size,
                        fields=fields,
                        pageToken=page_token,
                    )
                    .execute()
                )
                items.extend(response.get("files", []))
                page_token = response.get("nextPageToken")
                if page_token is None:
                    break
            logger.info(f"Found {len(items)} items in folder '{folder_id}'.")
            return items
        except HttpError as error:
            logger.error(
                f"An API error occurred while listing files in folder {folder_id}: {error}"
            )
            return {"error": str(error)}
        except Exception as e:
            logger.error(f"Unexpected error listing files in folder {folder_id}: {e}")
            return {"error": str(e)}

    def get_file_metadata(
        self,
        file_id: str,
        fields: str = "id, name, mimeType, webViewLink, parents, modifiedTime",
    ) -> dict[str, Any]:
        """Gets metadata for a specific file ID."""
        if not self.is_healthy():
            return {"error": "Google Drive service not initialized."}
        try:
            file_meta = (
                self.service.files().get(fileId=file_id, fields=fields).execute()
            )
            return file_meta
        except HttpError as error:
            logger.error(
                f"An API error occurred while getting metadata for file {file_id}: {error}"
            )
            return {"error": str(error)}
        except Exception as e:
            logger.error(f"Unexpected error getting metadata for file {file_id}: {e}")
            return {"error": str(e)}

    def download_file_content(self, file_id: str) -> bytes | dict[str, Any]:
        """Downloads file content by file ID."""
        if not self.is_healthy():
            return {"error": "Google Drive service not initialized."}
        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                logger.debug(
                    f"Download progress for {file_id}: {int(status.progress() * 100)}%"
                )
            fh.seek(0)
            logger.info(f"Successfully downloaded content for file ID: {file_id}")
            return fh.read()  # Returns bytes
        except HttpError as error:
            logger.error(
                f"An API error occurred while downloading file {file_id}: {error}"
            )
            return {"error": str(error)}
        except Exception as e:
            logger.error(f"Unexpected error downloading file {file_id}: {e}")
            return {"error": str(e)}

    def delete_drive_file_permanently(self, file_id: str) -> bool | dict[str, Any]:
        """Permanently deletes a file from Google Drive."""
        if not self.is_healthy():
            return {"error": "Google Drive service not initialized."}
        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"Successfully deleted file {file_id} from Google Drive.")
            return True
        except HttpError as error:
            logger.error(
                f"An API error occurred while deleting file {file_id} from Drive: {error}"
            )
            return {"error": str(error)}
        except Exception as e:
            logger.error(f"Unexpected error deleting file {file_id} from Drive: {e}")
            return {"error": str(e)}

    def watch_file(
        self,
        file_id: str,
        channel_id: str,
        channel_token: str,
        webhook_url: str,
        expiration_ms: int,
    ) -> dict[str, Any]:
        """Creates a watch on a file."""
        if not self.is_healthy():
            return {"error": "Google Drive service not initialized."}

        channel_body = {
            "id": channel_id,  # Your UUID for the channel
            "type": "web_hook",
            "address": webhook_url,  # Your publicly accessible webhook URL
            "token": channel_token,  # Optional: Your token to verify notifications
            "expiration": str(
                expiration_ms
            ),  # Expiration time in milliseconds since epoch
        }
        try:
            logger.info(
                f"Attempting to watch file {file_id} with channel_id {channel_id}, webhook {webhook_url}, expiration {expiration_ms}"
            )
            response = (
                self.service.files()
                .watch(
                    fileId=file_id,
                    body=channel_body,
                    supportsAllDrives=True,  # Add if dealing with Shared Drives
                )
                .execute()
            )
            logger.info(f"Successfully created watch for file {file_id}: {response}")
            return response  # Contains 'id', 'resourceId', 'resourceUri', 'expiration' from Google
        except HttpError as error:
            logger.error(f"API error creating watch for file {file_id}: {error}")
            return {
                "error": str(error),
                "details": error.resp.status,
                "reason": error._get_reason(),
            }
        except Exception as e:
            logger.error(f"Unexpected error creating watch for file {file_id}: {e}")
            return {"error": str(e)}

    def stop_channel(self, channel_id: str, resource_id: str) -> dict[str, Any]:
        """Stops a notification channel."""
        if not self.is_healthy():
            return {"error": "Google Drive service not initialized."}

        channel_body = {"id": channel_id, "resourceId": resource_id}
        try:
            logger.info(
                f"Attempting to stop channel: ID={channel_id}, ResourceID={resource_id}"
            )
            self.service.channels().stop(body=channel_body).execute()
            logger.info(
                f"Successfully stopped channel: ID={channel_id}, ResourceID={resource_id}"
            )
            return {"status": "success"}
        except HttpError as error:
            logger.error(f"API error stopping channel {channel_id}: {error}")
            return {
                "error": str(error),
                "details": error.resp.status,
                "reason": error._get_reason(),
            }
        except Exception as e:
            logger.error(f"Unexpected error stopping channel {channel_id}: {e}")
            return {"error": str(e)}

    def get_initial_start_page_token(
        self, drive_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Gets the starting page token for listing future changes.
        This token represents the current state of the account.
        :param drive_id: Optional ID of the Shared Drive to get the start page token for.
                         If None, gets for the user's account.
        :return: The startPageToken string or None if an error occurs.
        """
        if not self.is_healthy():
            logger.error(
                "Google Drive service not initialized. Cannot get start page token."
            )
            return None
        try:
            request_args: dict[str, Any] = {}
            if drive_id:
                request_args["driveId"] = drive_id
                request_args["supportsAllDrives"] = (
                    True  # Required if driveId is specified
                )

            token_response = (
                self.service.changes().getStartPageToken(**request_args).execute()
            )
            start_page_token = token_response.get("startPageToken")
            logger.info(
                f"Successfully retrieved initial startPageToken: {start_page_token}"
            )
            return start_page_token
        except HttpError as error:
            logger.error(
                f"An API error occurred while getting start page token: {error}"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting start page token: {e}")
            return None

    def get_latest_changes(
        self,
        page_token: str,  # Input page_token must be a string
        drive_id: Optional[str] = None,
        fields: str = "nextPageToken, newStartPageToken, changes(fileId, time, removed, teamDriveId, driveId, file(id, name, mimeType, parents, modifiedTime, trashed))",
    ) -> tuple[Optional[List[Dict[str, Any]]], str]:  # Return type for token is str
        """
        Lists all changes since the last provided page token.
        Handles pagination internally to retrieve all changes in the current batch.
        :param page_token: The pageToken from which to retrieve changes.
        :param drive_id: Optional ID of the Shared Drive to list changes for.
        :param fields: The fields to include in the change resources.
        :return: A tuple: (list_of_changes, new_start_page_token_for_next_call).
                 Returns (None, page_token) if an error occurs.
        """
        if (
            not self.is_healthy() or self.service is None
        ):  # Added self.service is None for mypy
            logger.error("Google Drive service not initialized. Cannot get changes.")
            return None, page_token

        all_changes: List[Dict[str, Any]] = []
        current_page_token: Optional[str] = page_token

        # Initialize new_start_page_token_for_next_call with the current page_token.
        # It will only be updated if a valid new token is received from the API.
        new_start_page_token_for_next_call: str = page_token

        try:
            while current_page_token is not None:
                request_args: Dict[str, Any] = {  # Explicitly type request_args
                    "pageToken": current_page_token,
                    "spaces": "drive",
                    "fields": fields,
                    "includeRemoved": True,
                    "supportsAllDrives": True,
                }
                if drive_id:
                    request_args["driveId"] = drive_id

                logger.debug(f"Fetching changes with pageToken: {current_page_token}")
                response = self.service.changes().list(**request_args).execute()

                changes_in_page: List[Dict[str, Any]] = response.get(
                    "changes", []
                )  # Explicitly type
                all_changes.extend(changes_in_page)
                logger.info(
                    f"Fetched {len(changes_in_page)} changes in this page. Total so far: {len(all_changes)}."
                )

                # Update new_start_page_token_for_next_call if a new one is provided in this response page
                potential_new_start_token: Optional[str] = response.get(
                    "newStartPageToken"
                )
                if potential_new_start_token is not None:
                    new_start_page_token_for_next_call = potential_new_start_token

                # Determine the token for the next page *within the current batch of changes*
                next_page_for_this_batch: Optional[str] = response.get("nextPageToken")
                if next_page_for_this_batch:
                    current_page_token = next_page_for_this_batch
                    logger.debug(
                        f"More changes available in this batch, next page token: {current_page_token}"
                    )
                else:
                    # This was the last page of the current batch of changes
                    logger.info(
                        f"End of changes for this batch. New startPageToken for the *next poll* will be: {new_start_page_token_for_next_call}"
                    )
                    current_page_token = None  # Exit the while loop

            return (
                all_changes,
                new_start_page_token_for_next_call,
            )  # new_start_page_token_for_next_call is guaranteed str

        except HttpError as error:
            logger.error(
                f"An API error occurred while listing changes: {error}. Initial pageToken for this call: {page_token}"
            )
            return None, page_token  # page_token is str
        except Exception as e:
            logger.error(
                f"Unexpected error listing changes: {e}. Initial pageToken for this call: {page_token}"
            )
            return None, page_token

    # page_token is str# You can add more methods like create_folder, upload_file if needed for other functionalities
    # For now, focusing on reading for ingestion.
