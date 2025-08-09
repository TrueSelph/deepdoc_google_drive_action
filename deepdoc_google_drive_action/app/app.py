"""DeepDoc Google Drive Action App"""

import json
import math
from typing import Any

import requests
import streamlit as st
from jvclient.lib.utils import (
    call_api,
    get_reports_payload,
)
from jvclient.lib.widgets import app_header, app_update_action


# --- Helper Functions (keep as is) ---
def get_gdrive_action_config_keys() -> list:
    """Get the keys for Google Drive action configuration"""

    return [
        "default_folder_id",
        "deepdoc_action_label",
        "project_id",
        "private_key_id",
        "private_key",
        "client_email",
        "client_id",
        "auth_uri",
        "token_uri",
        "auth_provider_x509_cert_url",
        "client_x509_cert_url",
        "universe_domain",
    ]


def load_config_from_json(model_key: str) -> None:
    """Load service account credentials from a JSON file"""
    uploaded_file = st.file_uploader(
        "Upload Service Account JSON", type="json", key=f"{model_key}_sa_json"
    )
    if uploaded_file is not None:
        try:
            creds_data = json.load(uploaded_file)
            st.session_state[model_key]["project_id"] = creds_data.get("project_id", "")
            st.session_state[model_key]["private_key_id"] = creds_data.get(
                "private_key_id", ""
            )
            st.session_state[model_key]["private_key"] = creds_data.get(
                "private_key", ""
            ).replace("\n", "\\n")
            st.session_state[model_key]["client_email"] = creds_data.get(
                "client_email", ""
            )
            st.session_state[model_key]["client_id"] = creds_data.get("client_id", "")
            st.session_state[model_key]["auth_uri"] = creds_data.get(
                "auth_uri", "https://accounts.google.com/o/oauth2/auth"
            )
            st.session_state[model_key]["token_uri"] = creds_data.get(
                "token_uri", "https://oauth2.googleapis.com/token"
            )
            st.session_state[model_key]["auth_provider_x509_cert_url"] = creds_data.get(
                "auth_provider_x509_cert_url",
                "https://www.googleapis.com/oauth2/v1/certs",
            )
            st.session_state[model_key]["client_x509_cert_url"] = creds_data.get(
                "client_x509_cert_url", ""
            )
            st.session_state[model_key]["universe_domain"] = creds_data.get(
                "universe_domain", "googleapis.com"
            )
            st.success("Service account credentials loaded from JSON.")
            st.rerun()
        except Exception as e:
            st.error(f"Error loading service account JSON: {e}")


def render(
    router: st.delta_generator.DeltaGenerator, agent_id: str, action_id: str, info: dict
) -> None:
    """Render the Google Drive action app"""

    (model_key, module_root) = app_header(agent_id, action_id, info)

    if "gdrive_folder_to_ingest" not in st.session_state:
        st.session_state.gdrive_folder_to_ingest = st.session_state[model_key].get(
            "default_folder_id", ""
        )
    if "gdrive_files_to_ingest" not in st.session_state:
        st.session_state.gdrive_files_to_ingest = ""
    if (
        "gdrive_watch_resource_type" not in st.session_state
    ):  # Add new session state for resource type
        st.session_state.gdrive_watch_resource_type = "file"
    if "gdrive_watch_resource_id" not in st.session_state:
        st.session_state.gdrive_watch_resource_id = ""
    if "gdrive_jiva_channel_uuid_to_stop" not in st.session_state:
        st.session_state.gdrive_jiva_channel_uuid_to_stop = ""
    if f"{model_key}_active_watches_cache" not in st.session_state:
        st.session_state[f"{model_key}_active_watches_cache"] = (
            None  # For caching list response
        )
    # ... (other session state initializations)

    with st.expander("Google Drive & DeepDoc Configuration", expanded=False):
        st.subheader("Service Account Credentials")
        load_config_from_json(model_key)
        st.session_state[model_key]["project_id"] = st.text_input(
            "Project ID", value=st.session_state[model_key].get("project_id", "")
        )
        st.session_state[model_key]["client_email"] = st.text_input(
            "Client Email", value=st.session_state[model_key].get("client_email", "")
        )
        st.session_state[model_key]["private_key"] = st.text_area(
            "Private Key",
            value=st.session_state[model_key]
            .get("private_key", "")
            .replace("\\n", "\n"),
            height=150,
            help="Paste private key here. Newlines will be preserved.",
        )

        # Update how default_folder_id and deepdoc_action_label are retrieved and set
        default_folder_id_val = st.session_state[model_key].get("default_folder_id", "")
        st.session_state[model_key]["default_folder_id"] = st.text_input(
            "Default Google Drive Folder ID (Optional)",
            value=default_folder_id_val,
            key=f"{model_key}_default_folder_id_input",
        )

        deepdoc_label_val = st.session_state[model_key].get(
            "deepdoc_action_label", "DeepDocClientAction"
        )
        st.session_state[model_key]["deepdoc_action_label"] = st.text_input(
            "DeepDoc Client Action Label",
            value=deepdoc_label_val,
            key=f"{model_key}_deepdoc_label_input",
        )

        # New Config items for watcher
        st.markdown("---")
        st.markdown(
            "**Watcher Configuration (Restart agent after changing webhook base URL here)**"
        )
        st.session_state[model_key]["default_webhook_base_url"] = st.text_input(
            "Default Jiva Webhook Base URL (e.g., https://your-jiva.com)",
            value=st.session_state[model_key].get("default_webhook_base_url", ""),
            help="Your publicly accessible Jiva instance URL. Needed for Google to send notifications.",
        )
        st.session_state[model_key]["pulse_interval_seconds"] = st.number_input(
            "Pulse Interval for Renewals (seconds)",
            min_value=60,
            value=st.session_state[model_key].get("pulse_interval_seconds", 3600),
        )
        st.session_state[model_key]["renew_threshold_hours"] = st.number_input(
            "Renew Watch Threshold (hours before expiry)",
            min_value=1,
            value=st.session_state[model_key].get("renew_threshold_hours", 6),
        )
        # For 'watched_gdrive_resources', direct YAML editing in DAF is better.
        # UI could show current configured list if read-only from DAF.
        current_watched_resources = st.session_state[model_key].get(
            "watched_gdrive_resources", []
        )
        st.write("Watched GDrive Resources (configured in DAF):")
        if current_watched_resources:
            st.json(current_watched_resources)
        else:
            st.caption("No GDrive resources configured for automatic watching in DAF.")

        app_update_action(agent_id, action_id)  # Save config changes

    st.subheader("Ingest Documents from Google Drive")
    with st.form("ingest_form"):
        ingest_type = st.radio(
            "Ingest Type:",
            ("Folder", "Specific Files"),
            horizontal=True,
            key=f"{model_key}_ingest_type",
        )
        drive_ids_input_key = f"{model_key}_drive_ids_input"
        st.text_area(
            f"Google Drive {'Folder ID(s)' if ingest_type == 'Folder' else 'File ID(s)'} (comma-separated)",
            height=80,
            key=drive_ids_input_key,
        )
        user_metadata_input_key = f"{model_key}_user_metadata_input"
        st.text_area(
            "Optional User Metadata (JSON string for all items in this batch)",
            value="{}",
            height=80,
            help='Example: {"project": "Alpha", "status": "draft"}',
            key=user_metadata_input_key,
        )
        submitted_ingest = st.form_submit_button("Start Ingestion")

    if submitted_ingest and st.session_state[drive_ids_input_key]:
        ids_list = [
            id.strip()
            for id in st.session_state[drive_ids_input_key].split(",")
            if id.strip()
        ]
        item_type_arg = "folder" if ingest_type == "Folder" else "file"
        parsed_user_metadata = None
        try:
            parsed_user_metadata = (
                json.loads(st.session_state[user_metadata_input_key])
                if st.session_state[user_metadata_input_key]
                else {}
            )
        except json.JSONDecodeError:
            st.error("Invalid JSON format for User Metadata.")
            parsed_user_metadata = None  # Ensure it's None if parsing fails

        if ids_list and (
            parsed_user_metadata is not None
        ):  # Check if parsed_user_metadata is not None
            with st.spinner(f"Ingesting {ingest_type}(s): {', '.join(ids_list)}..."):
                result_data = call_api(
                    endpoint="action/walker/deepdoc_google_drive_action/ingest_gdrive_items_walker",
                    json_data={
                        "agent_id": agent_id,
                        "drive_ids": ids_list,
                        "item_type": item_type_arg,
                        "user_metadata": parsed_user_metadata,
                    },
                )
                result: dict[str, Any] = {}
                if result_data and result_data.status_code == 200:
                    result_payload = get_reports_payload(result_data)
                    result = (
                        result_payload
                        if result_payload and isinstance(result_payload, dict)
                        else {}
                    )

                if result:
                    st.write("Ingestion Results:")
                    if result.get("succeeded"):
                        st.success(
                            f"Successfully initiated ingestion for: {result['succeeded']}"
                        )
                    if result.get("failed"):
                        st.error(
                            f"Failed to initiate ingestion for: {result['failed']}"
                        )
                    if result.get("job_ids"):
                        st.info(f"DeepDoc Job ID(s) created: {result['job_ids']}")

                    # Rerun with reloaded UI
                    del st.session_state[f"{model_key}_all_ingested_docs"]
                    st.session_state[f"{model_key}_active_watches_cache"] = (
                        None  # Invalidate cache
                    )
                    st.rerun()  # Rerun to fetch fresh list
                else:
                    st.error(
                        f"Failed to trigger ingestion walker or walker returned no/unexpected response. Full walker response: {result_data}"
                    )
        elif not ids_list:
            st.warning("Please enter at least one Drive ID.")
        # Added else for when parsed_user_metadata is None due to JSON error
        elif parsed_user_metadata is None:
            st.warning("Ingestion aborted due to invalid User Metadata JSON.")

    st.markdown("---")
    st.subheader("Manage Google Drive Watchers")

    col_watch1, col_watch2 = st.columns(2)
    with col_watch1:
        with st.form("start_watch_form"):
            st.markdown("**Start Watching a Resource**")
            st.session_state.gdrive_watch_resource_id = st.text_input(
                "Google Drive File/Folder ID to Watch",
                value=st.session_state.gdrive_watch_resource_id,
            )
            # Add a resource type radio selection
            resource_type_options = ["file", "folder"]
            resource_type_index = (
                resource_type_options.index(st.session_state.gdrive_watch_resource_type)
                if st.session_state.gdrive_watch_resource_type in resource_type_options
                else 0
            )
            st.session_state.gdrive_watch_resource_type = st.radio(
                "Resource Type:",
                options=resource_type_options,
                index=resource_type_index,
                horizontal=True,
                help="Specify whether this is a file or folder resource",
            )

            webhook_base_for_start = st.text_input(
                "Jiva Webhook Base URL (if different from default)",
                value=st.session_state[model_key].get("default_webhook_base_url", ""),
                help="Overrides default if set. Ensure it's publicly accessible.",
            )
            submitted_start_watch = st.form_submit_button("Start Watch")

        if submitted_start_watch and st.session_state.gdrive_watch_resource_id:
            with st.spinner(
                f"Attempting to start watch on {st.session_state.gdrive_watch_resource_id}..."
            ):
                payload = {
                    "agent_id": agent_id,
                    "operation": "start",
                    "gdrive_resource_id": st.session_state.gdrive_watch_resource_id,
                    "resource_type": st.session_state.gdrive_watch_resource_type,  # Add the resource type to the payload
                    "webhook_base_url": webhook_base_for_start
                    or st.session_state[model_key].get("default_webhook_base_url"),
                }
                if not payload["webhook_base_url"]:
                    st.error(
                        "Webhook Base URL is required to start a watch. Configure it in the section above or provide here."
                    )
                else:
                    result = {}
                    result_data = call_api(
                        endpoint="action/walker/deepdoc_google_drive_action/manage_gdrive_watch_walker",
                        json_data=payload,
                    )
                    if result_data and result_data.status_code == 200:
                        result_payload = get_reports_payload(result_data)
                        result = (
                            result_payload
                            if result_payload and isinstance(result_payload, dict)
                            else {}
                        )

                    if result.get("status") == "succeeded":
                        st.success(
                            f"Watch started successfully! Jiva UUID: {result.get('jiva_channel_uuid')}"
                        )
                        st.json(result.get("details", {}))
                        st.session_state[f"{model_key}_active_watches_cache"] = (
                            None  # Invalidate cache
                        )
                    else:
                        st.error(
                            f"Failed to start watch: {result.get('message', 'Unknown error')}"
                        )
                        if result.get("details"):
                            st.json(
                                result.get("details")
                            )  # Show Google's error if present

    with col_watch2:
        with st.form("stop_watch_form"):
            st.markdown("**Stop Watching a Resource**")
            st.session_state.gdrive_jiva_channel_uuid_to_stop = st.text_input(
                "Jiva Watch Channel UUID to Stop",
                value=st.session_state.gdrive_jiva_channel_uuid_to_stop,
                help="This is the UUID generated by Jiva when the watch was started.",
            )
            submitted_stop_watch = st.form_submit_button("Stop Watch")

        if submitted_stop_watch and st.session_state.gdrive_jiva_channel_uuid_to_stop:
            with st.spinner(
                f"Attempting to stop watch {st.session_state.gdrive_jiva_channel_uuid_to_stop}..."
            ):
                payload = {
                    "agent_id": agent_id,
                    "operation": "stop",
                    "jiva_channel_uuid": st.session_state.gdrive_jiva_channel_uuid_to_stop,
                }
                result = {}
                result_data = call_api(
                    endpoint="action/walker/deepdoc_google_drive_action/manage_gdrive_watch_walker",
                    json_data=payload,
                )
                if result_data and result_data.status_code == 200:
                    result_payload = get_reports_payload(result_data)
                    result = (
                        result_payload
                        if result_payload and isinstance(result_payload, dict)
                        else {}
                    )

                if result.get("status") == "succeeded":
                    st.success(result.get("message", "Watch stopped successfully."))
                    st.session_state[f"{model_key}_active_watches_cache"] = (
                        None  # Invalidate cache
                    )
                else:
                    st.error(
                        f"Failed to stop watch: {result.get('message', 'Unknown error')}"
                    )

    st.markdown("---")
    st.markdown("**Active Google Drive Watchers**")
    if st.button("🔄 Refresh Active Watchers List", key=f"{model_key}_refresh_watches"):
        st.session_state[f"{model_key}_active_watches_cache"] = None  # Invalidate cache
        st.rerun()  # Rerun to fetch fresh list

    # Use cached list if available
    if st.session_state.get(f"{model_key}_active_watches_cache") is None:
        with st.spinner("Fetching active watchers list..."):
            list_payload = {"agent_id": agent_id, "operation": "list"}
            result = {}
            result_data = call_api(
                endpoint="action/walker/deepdoc_google_drive_action/manage_gdrive_watch_walker",
                json_data=list_payload,
            )

            if result_data and result_data.status_code == 200:
                result_payload = get_reports_payload(result_data)
                result = (
                    result_payload
                    if result_payload and isinstance(result_payload, dict)
                    else {}
                )

            st.session_state[f"{model_key}_active_watches_cache"] = result.get(
                "active_watches", []
            )

    active_watches = st.session_state[f"{model_key}_active_watches_cache"]

    if active_watches:
        st.write(f"Found {len(active_watches)} active Jiva-managed watch channels:")
        for watch in active_watches:
            col_disp1, col_disp2, col_disp3 = st.columns([3, 2, 1])
            with col_disp1:
                st.markdown(f"**GDrive ID:** `{watch.get('gdrive_resource_id')}`")
                st.caption(f"Jiva UUID: `{watch.get('jiva_channel_uuid')}`")
            with col_disp2:
                st.caption(f"Google CH ID: `{watch.get('google_channel_id')}`")
                st.caption(f"Expires: {watch.get('expires_at_iso')}")
            with col_disp3:
                if st.button(
                    "Force Renew",
                    key=f"renew_{watch.get('jiva_channel_uuid')}",
                    help="Manually trigger renewal for this watch.",
                ):
                    with st.spinner(
                        f"Renewing watch {watch.get('jiva_channel_uuid')}..."
                    ):
                        renew_payload = {
                            "agent_id": agent_id,
                            "operation": "renew",
                            "jiva_channel_uuid": watch.get("jiva_channel_uuid"),
                        }
                        renew_res: dict[str, Any] = {}

                        renew_res_data = call_api(
                            endpoint="action/walker/deepdoc_google_drive_action/manage_gdrive_watch_walker",
                            json_data=renew_payload,
                        )
                        if renew_res_data and renew_res_data.status_code == 200:
                            result_payload = get_reports_payload(renew_res_data)
                            renew_res = (
                                result_payload
                                if result_payload and isinstance(result_payload, dict)
                                else {}
                            )

                        if renew_res.get("status") == "succeeded":
                            st.success(
                                f"Renewal initiated for {watch.get('jiva_channel_uuid')}. New Jiva UUID: {renew_res.get('jiva_channel_uuid')}"
                            )
                        else:
                            st.error(f"Renewal failed: {renew_res.get('message')}")
                        st.session_state[f"{model_key}_active_watches_cache"] = (
                            None  # Invalidate cache
                        )
                        st.rerun()

            st.divider()
    elif (
        isinstance(active_watches, list) and not active_watches
    ):  # Empty list explicitly
        st.info("No active Google Drive watchers managed by Jiva currently.")
    else:  # Error or unexpected response from walker
        st.error("Could not retrieve active watchers list or an error occurred.")
        if active_watches:
            st.json(active_watches)  # Show raw response if it's not the expected list

    if st.button(
        "Attempt to Recover All Configured Watches",
        key=f"{model_key}_recover_watches_btn",
    ):
        with st.spinner("Attempting to recover watches based on DAF configuration..."):
            webhook_base_for_recovery = st.session_state[model_key].get(
                "default_webhook_base_url"
            )
            if not webhook_base_for_recovery:
                st.error(
                    "Default Webhook Base URL must be configured in the 'Configuration' section above to attempt recovery."
                )
            else:
                recover_payload = {
                    "agent_id": agent_id,
                    "operation": "recover",
                    "webhook_base_url": webhook_base_for_recovery,
                }

                recover_result: dict[str, Any] = {}

                recover_result_data = call_api(
                    endpoint="action/walker/deepdoc_google_drive_action/manage_gdrive_watch_walker",
                    json_data=recover_payload,
                )

                if recover_result_data and recover_result_data.status_code == 200:
                    result_payload = get_reports_payload(recover_result_data)
                    recover_result = (
                        result_payload
                        if result_payload and isinstance(result_payload, dict)
                        else {}
                    )

                st.write("Recovery Attempt Results:")
                st.json(recover_result)
                st.session_state[f"{model_key}_active_watches_cache"] = (
                    None  # Invalidate cache
                )
                st.rerun()

    # --- Management Section ---
    st.subheader("Manage Ingested Drive Documents")

    # Fetch all documents once
    if f"{model_key}_all_ingested_docs" not in st.session_state:
        with st.spinner("Loading all ingested Google Drive documents..."):
            ingested_data: list[str] = []

            ingested_result: requests.Response = call_api(
                endpoint="action/walker/deepdoc_google_drive_action/get_ingested_gdrive_docs_walker",
                json_data={"agent_id": agent_id},
            )
            if ingested_result and ingested_result.status_code == 200:
                result_payload = get_reports_payload(ingested_result)
                ingested_data = (
                    result_payload
                    if result_payload and isinstance(result_payload, list)
                    else []
                )

            # Store the full list in session state
            st.session_state[f"{model_key}_all_ingested_docs"] = ingested_data
            # Reset current page if data is reloaded
            st.session_state[f"{model_key}_current_page_ingested"] = 1

    all_ingested_docs = st.session_state.get(f"{model_key}_all_ingested_docs", [])

    if all_ingested_docs and not (
        isinstance(all_ingested_docs, list)
        and len(all_ingested_docs) > 0
        and "error" in all_ingested_docs[0]
    ):
        # --- Pagination Controls ---
        items_per_page_key = f"{model_key}_items_per_page_ingested"
        current_page_key = f"{model_key}_current_page_ingested"

        items_per_page = st.selectbox(
            "Items per page:",
            options=[5, 10, 20, 50, 100],
            index=[5, 10, 20, 50, 100].index(
                st.session_state.get(items_per_page_key, 10)
            ),
            key=f"{items_per_page_key}_selector",  # Unique key for the selectbox
        )
        # Update session state if selectbox changes
        if st.session_state.get(items_per_page_key) != items_per_page:
            st.session_state[items_per_page_key] = items_per_page
            st.session_state[current_page_key] = (
                1  # Reset to first page on items_per_page change
            )
            st.rerun()  # Rerun to apply new items_per_page

        total_items = len(all_ingested_docs)
        total_pages = (
            math.ceil(total_items / items_per_page) if items_per_page > 0 else 1
        )

        # Ensure current_page is within valid bounds
        st.session_state[current_page_key] = max(
            1, min(st.session_state.get(current_page_key, 1), total_pages)
        )

        # Calculate slice for current page
        start_idx = (st.session_state[current_page_key] - 1) * items_per_page
        end_idx = start_idx + items_per_page
        paginated_docs = all_ingested_docs[start_idx:end_idx]

        st.write(
            f"Showing {len(paginated_docs)} of {total_items} Google Drive items in DeepDoc manifest (Page {st.session_state[current_page_key]}/{total_pages})"
        )

        # Navigation buttons
        col_nav1, col_nav2, col_nav3, col_nav4 = st.columns(
            [1, 1, 5, 1]
        )  # Adjusted layout
        with col_nav1:
            if st.button(
                "⬅️ Prev",
                key=f"{model_key}_prev_page",
                disabled=(st.session_state[current_page_key] <= 1),
            ):
                st.session_state[current_page_key] -= 1
                st.rerun()
        with col_nav2:
            if st.button(
                "Next ➡️",
                key=f"{model_key}_next_page",
                disabled=(st.session_state[current_page_key] >= total_pages),
            ):
                st.session_state[current_page_key] += 1
                st.rerun()
        # col_nav3 for spacing
        with col_nav4:
            if st.button("🔄 Refresh List", key=f"{model_key}_refresh_docs"):
                # Clear the cached list to force a reload
                if f"{model_key}_all_ingested_docs" in st.session_state:
                    del st.session_state[f"{model_key}_all_ingested_docs"]
                st.rerun()

        # --- Display Paginated Documents ---
        for doc_idx, doc in enumerate(paginated_docs):
            # Unique key for elements within the loop, incorporating page and item index
            # This is crucial if the content of `doc` can change between pages but idx might repeat
            # A more robust key would be based on a unique ID from the doc itself (e.g., gdrive_file_id)
            item_unique_id = doc.get("metadata", {}).get(
                "google_drive_file_id", f"item_{start_idx + doc_idx}"
            )

            gdrive_file_id = doc.get("metadata", {}).get("google_drive_file_id", "N/A")
            gdrive_filename = doc.get("metadata", {}).get(
                "google_drive_filename", doc.get("filename", "N/A")
            )
            deepdoc_job_id = doc.get("job_id", "N/A")

            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.markdown(f"**{gdrive_filename}** (GDrive ID: `{gdrive_file_id}`)")
                st.caption(
                    f"DeepDoc Job: `{deepdoc_job_id}`, Orig. Filename: `{doc.get('filename')}`"
                )
            with col2:
                if st.button("Re-ingest (Update)", key=f"update_{item_unique_id}"):
                    with st.spinner(
                        f"Requesting re-ingestion for {gdrive_filename}..."
                    ):
                        del_payload = {
                            "google_drive_file_id": gdrive_file_id,
                            "agent_id": agent_id,
                        }
                        del_res = {}
                        del_result_data = call_api(
                            endpoint="action/walker/deepdoc_google_drive_action/remove_gdrive_item_walker",
                            payload=del_payload,
                        )
                        if del_result_data and del_result_data.status_code == 200:
                            del_res = get_reports_payload(del_result_data)
                            del_res = (
                                result_payload
                                if result_payload and isinstance(result_payload, dict)
                                else {}
                            )

                        if del_res and del_res.get("status") == "succeeded":
                            st.info(
                                f"Old version of {gdrive_filename} removed. Starting re-ingestion..."
                            )
                            # Pass original metadata for consistency during re-ingestion
                            original_metadata = doc.get("metadata", {})
                            # Remove GDrive specific fields if they are re-added by ingest_drive_items to avoid deep nesting
                            original_metadata.pop("google_drive_file_id", None)
                            original_metadata.pop("google_drive_filename", None)
                            original_metadata.pop("google_drive_mimetype", None)
                            original_metadata.pop("google_drive_folder_id", None)
                            original_metadata.pop("source_system", None)

                            ingest_payload = {
                                "agent_id": agent_id,
                                "drive_ids": [gdrive_file_id],
                                "item_type": "file",
                                "user_metadata": original_metadata,
                            }

                            ingest_res: dict[str, Any] = {}
                            ingest_result_data = call_api(
                                endpoint="action/walker/deepdoc_google_drive_action/ingest_gdrive_items_walker",
                                json_data=ingest_payload,
                            )
                            if (
                                ingest_result_data
                                and ingest_result_data.status_code == 200
                            ):
                                del_res = get_reports_payload(ingest_result_data)
                                ingest_res = (
                                    result_payload
                                    if result_payload
                                    and isinstance(result_payload, dict)
                                    else {}
                                )

                            if ingest_res and ingest_res.get("succeeded"):
                                st.success(
                                    f"Re-ingestion started for {gdrive_filename}."
                                )
                            else:
                                st.error(
                                    f"Failed to start re-ingestion for {gdrive_filename}: {ingest_res}"
                                )
                        else:
                            st.error(
                                f"Failed to remove old version of {gdrive_filename} for update: {del_res}"
                            )
                        # Clear cache and rerun to see changes
                        if f"{model_key}_all_ingested_docs" in st.session_state:
                            del st.session_state[f"{model_key}_all_ingested_docs"]
                        st.rerun()
            with col3:
                if st.button("Remove from Store", key=f"delete_{item_unique_id}"):
                    with st.spinner(f"Removing {gdrive_filename} from vector store..."):
                        payload = {
                            "google_drive_file_id": gdrive_file_id,
                            "agent_id": agent_id,
                        }

                        delete_result: dict[str, Any] = {}
                        delete_result_data = call_api(
                            endpoint="action/walker/deepdoc_google_drive_action/remove_gdrive_item_walker",
                            json_data=payload,
                        )
                        if delete_result_data and delete_result_data.status_code == 200:
                            del_res = get_reports_payload(delete_result_data)
                            delete_result = (
                                result_payload
                                if result_payload and isinstance(result_payload, dict)
                                else {}
                            )

                        if delete_result and delete_result.get("status") == "succeeded":
                            st.success(delete_result.get("message"))
                        else:
                            st.error(
                                delete_result.get("message", "Failed to remove item.")
                            )
                        # Clear cache and rerun
                        if f"{model_key}_all_ingested_docs" in st.session_state:
                            del st.session_state[f"{model_key}_all_ingested_docs"]

                        st.session_state[f"{model_key}_active_watches_cache"] = (
                            None  # Invalidate cache
                        )
                        st.rerun()
            st.divider()

    elif (
        all_ingested_docs
        and isinstance(all_ingested_docs, list)
        and len(all_ingested_docs) > 0
        and "error" in all_ingested_docs[0]
    ):
        st.error(
            f"Error fetching ingested documents: {all_ingested_docs[0].get('error', 'Unknown error')}"
        )
    else:  # Handles empty list or other non-error but non-list cases
        st.info("No Google Drive documents found in DeepDoc manifest.")

    # --- Remove Entire Folder Section (remains largely the same) ---
    st.markdown("---")
    st.write("Remove All Items from a Google Drive Folder (from Vector Store Only)")
    gdrive_folder_to_clear_input_key = f"{model_key}_gdrive_folder_to_clear_input"
    st.text_input(
        "Google Drive Folder ID to Clear", key=gdrive_folder_to_clear_input_key
    )
    if st.button("Clear Folder from Vector Store"):
        if st.session_state[gdrive_folder_to_clear_input_key]:
            with st.spinner(
                f"Removing all items from folder {st.session_state[gdrive_folder_to_clear_input_key]} from vector store..."
            ):
                payload = {
                    "google_drive_folder_id": st.session_state[
                        gdrive_folder_to_clear_input_key
                    ],
                    "agent_id": agent_id,
                }
                clear_result_data = call_api(
                    endpoint="action/walker/deepdoc_google_drive_action/clear_gdrive_folder_walker",
                    json_data=payload,
                )

                if clear_result_data and clear_result_data.status_code == 200:
                    del_res = get_reports_payload(clear_result_data)
                    clear_result = (
                        result_payload
                        if result_payload and isinstance(result_payload, dict)
                        else {}
                    )

                if clear_result:
                    st.info(clear_result.get("message", "Clear operation finished."))
                    if clear_result.get("deleted_files"):
                        st.write(
                            f"Removed: {len(clear_result['deleted_files'])} files."
                        )
                    if clear_result.get("failed_files"):
                        st.warning(
                            f"Failed to remove: {len(clear_result['failed_files'])} files."
                        )
                else:
                    st.error("Failed to trigger folder clearing operation.")
                # Clear cache and rerun
                if f"{model_key}_all_ingested_docs" in st.session_state:
                    del st.session_state[f"{model_key}_all_ingested_docs"]

                st.session_state[f"{model_key}_active_watches_cache"] = (
                    None  # Invalidate cache
                )
                st.rerun()
        else:
            st.warning("Please enter a Google Drive Folder ID to clear.")
