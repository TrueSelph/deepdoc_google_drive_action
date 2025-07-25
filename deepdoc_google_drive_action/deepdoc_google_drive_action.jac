import logging;
import os;
import json; # For metadata string conversion if needed
import uuid; # For generating Jiva channel UUIDs
import time; # For expiration calculations
import from logging { Logger }
import from datetime { datetime, timedelta, timezone } # For expiration calculations
import from typing { Union, List, Dict, Optional }
import from jivas.agent.action.action { Action }
import from jivas.agent.action.agent_graph_walker { agent_graph_walker }
import from .modules.google_drive_handler { GoogleDriveHandler }
import from jivas.agent.modules.agentlib.utils { Utils }
import from jvserve.lib.agent_interface { encrypt_webhook_key_exec }


node DeepDocGoogleDriveAction(Action) {
    has description:str = "Integrates with Google Drive to ingest documents into DeepDoc.";
    has scopes:list = ["https://www.googleapis.com/auth/drive.readonly"]; # Start with readonly, expand if needed
    has default_folder_id:str = ""; # Can be overridden by agent config

    # Service account credentials (to be set in DAF)
    has info_type:str = "";
    has project_id:str = "";
    has private_key_id:str = "";
    has private_key:str = ""; # Multiline string in YAML
    has client_email:str = "";
    has client_id:str = "";
    has auth_uri:str = "";
    has token_uri:str = "";
    has auth_provider_x509_cert_url:str = "https://www.googleapis.com/oauth2/v1/certs";
    has client_x509_cert_url:str = "";
    has universe_domain:str = "googleapis.com";

    has active_watch_channels: dict = {}; # {jiva_channel_uuid: {g_channel_id, g_resource_id, gdrive_id, expiration_ms, token}}

    has pulse_interval_seconds: int = 3600; # e.g., check every hour
    has renew_threshold_hours: int = 6; # Renew if expiration is within this many hours

    # To be configured in DAF: List of {'gdrive_id': '...', 'type': 'file'/'folder'}
    has watched_gdrive_resources: list[dict] = [];
    has default_webhook_base_url: str = ""; # e.g., "https://your-jiva-instance.com" - SET IN DAF

    has auto_watch_on_ingest: bool = True; # Default to True, can be overridden in DAF
    has page_token: str = "";

    has deepdoc_action_label: str = "DeepDocClientAction"; # Label of the DeepDoc action

    # --- Internal State (Logger only) ---
    static has logger:Logger = logging.getLogger(__name__);

    def on_register() {
        if self.enabled {
            self.on_enable();
        }
    }

    def on_enable() { # Called when agent becomes active or action is enabled
        self.logger.info("DeepDocGoogleDriveAction enabled. Initializing...");

        if(not self.page_token) {
            drive_handler = self.get_drive_handler();
            if (not drive_handler) { self.logger.error("GDrive Handler not available."); }

            self.page_token = drive_handler.get_initial_start_page_token();
        }

        if (not self.default_webhook_base_url) {
            self.default_webhook_base_url = os.environ.get('JIVAS_BASE_URL');
        }

        webhook_base = self.default_webhook_base_url;
        if (not webhook_base) {
             self.logger.error("JIVAS_BASE_URL environment variable or default_webhook_base_url DAF config not set. Watch recovery and new watches may fail.");
        } else {
            # Store for later use if it came from ENV
            if (not self.default_webhook_base_url) { self.default_webhook_base_url = webhook_base; }
            self.recover_watches(webhook_base_url=webhook_base);
        }
        self.start_pulse_scheduler();
    }

    def on_disable() {
        self.logger.info("DeepDocGoogleDriveAction disabling. Stopping pulse and watches.");
        self.stop_pulse_scheduler();
        jiva_uuids_to_stop = list(self.active_watch_channels.keys());
        for jiva_uuid in jiva_uuids_to_stop {
            self.stop_watching_resource(jiva_channel_uuid=jiva_uuid, initiated_by_user=False);
        }
        self.active_watch_channels = {};
    }

    def get_drive_handler() -> Optional[GoogleDriveHandler] {
        credentials_info = {
            "type": self.info_type, "project_id": self.project_id,
            "private_key_id": self.private_key_id, "private_key": self.private_key.replace('\\n', '\n'),
            "client_email": self.client_email, "client_id": self.client_id,
            "auth_uri": self.auth_uri, "token_uri": self.token_uri,
            "auth_provider_x509_cert_url": self.auth_provider_x509_cert_url,
            "client_x509_cert_url": self.client_x509_cert_url, "universe_domain": self.universe_domain
        };
        if (not self.project_id or not self.private_key or not self.client_email) {
            self.logger.error("GDrive credentials not fully configured."); return None;
        }
        try {
            handler = GoogleDriveHandler(credentials_info=credentials_info, scopes=self.scopes);
            return handler if handler.is_healthy() else None;
        } except Exception as e {
            self.logger.error(f"Exception creating GDriveHandler: {e}"); return None;
        }
    }

    def get_deepdoc_action() {
        dd_action = self.get_agent().get_actions().get(action_label=self.deepdoc_action_label);
        if (not dd_action) {
            self.logger.error(f"DeepDocClientAction '{self.deepdoc_action_label}' not found.");
            return None;
        }
        return dd_action;
    }

    def start_watching_resource(gdrive_resource_id: str, resource_type: str, webhook_base_url: Optional[str] = None) -> Dict {
        # resource_type: 'file' or 'folder' (this is for our tracking, Google API always uses fileId)
        effective_webhook_base_url = webhook_base_url if webhook_base_url else self.default_webhook_base_url;
        if (not effective_webhook_base_url) {
             effective_webhook_base_url = os.environ.get('JIVAS_BASE_URL');
             if (not effective_webhook_base_url) {
                 self.logger.error("Webhook base URL not configured. Cannot start watch.");
                 return {"status": "failed", "message": "Webhook base URL not configured."};
             }
             if (not self.default_webhook_base_url) { self.default_webhook_base_url = effective_webhook_base_url; }
        }

        drive_handler = self.get_drive_handler();
        if (not drive_handler) { return {"status": "failed", "message": "GDrive Handler not available."}; }

        # Check if this exact gdrive_resource_id is already being watched
        for (j_uuid, watch_info) in self.active_watch_channels.items() {
            if (watch_info.get("gdrive_id_watched") == gdrive_resource_id) {
                self.logger.info(f"GDrive resource {gdrive_resource_id} already actively watched by Jiva UUID {j_uuid}. Checking expiration.");
                # If it's nearing expiration, renew it, otherwise confirm it's active
                if (watch_info.get("expiration_ms", 0) < (int(datetime.now(timezone.utc).timestamp() * 1000) + (self.renew_threshold_hours * 3600 * 1000))) {
                    return self.renew_watch_channel(jiva_channel_uuid=j_uuid);
                } else {
                    return {"status": "already_active", "jiva_channel_uuid": j_uuid, "details": watch_info};
                }
            }
        }

        jiva_channel_uuid = str(uuid.uuid4());
        webhook_token = f"jiva_watch_token_{jiva_channel_uuid}"; # To validate incoming notifications
        agent_id = self.get_agent().id;

        if (effective_webhook_base_url.endswith('/')) { effective_webhook_base_url = effective_webhook_base_url[:-1]; }

        webhook_key = encrypt_webhook_key_exec(
            agent_id=agent_id, module_root=self.get_module_root(), walker="gdrive_notification_receiver_walker"
        );
        full_webhook_url = f"{effective_webhook_base_url}/action/webhook/{webhook_key}";

        expiration_dt = datetime.now(timezone.utc) + timedelta(days=1); # Google's default max is often 1 day
        expiration_ms = int(expiration_dt.timestamp() * 1000);

        self.logger.info(f"Starting watch for GDrive ID: {gdrive_resource_id} (Type: {resource_type}), Jiva UUID: {jiva_channel_uuid}, Callback: {full_webhook_url}");

        watch_response = drive_handler.watch_file(
            file_id=gdrive_resource_id, channel_id=jiva_channel_uuid,
            channel_token=webhook_token, webhook_url=full_webhook_url, expiration_ms=expiration_ms
        );

        if (watch_response and "id" in watch_response and "resourceId" in watch_response) {
            self.active_watch_channels[jiva_channel_uuid] = {
                "jiva_channel_uuid": jiva_channel_uuid,
                "google_channel_id": watch_response["id"], # Google's ID for this channel instance
                "google_resource_id": watch_response["resourceId"], # Google's opaque ID for the watched GDrive resource
                "gdrive_id_watched": gdrive_resource_id, # The actual GDrive ID we are watching
                "type": resource_type, # 'file' or 'folder' - our classification
                "expiration_ms": int(watch_response.get("expiration", expiration_ms)),
                "webhook_token": webhook_token,
                "webhook_url": full_webhook_url,
                "created_at_iso": datetime.now(timezone.utc).isoformat()
            };
            self.logger.info(f"Watch started: Jiva UUID {jiva_channel_uuid}, GDrive ID {gdrive_resource_id}, Google CH ID {watch_response['id']}.");
            return {"status": "succeeded", "jiva_channel_uuid": jiva_channel_uuid, "details": self.active_watch_channels[jiva_channel_uuid]};
        } else {
            error_detail = watch_response.get("error", "Unknown GDrive API error during watch.");
            if (isinstance(watch_response, dict) and "reason" in watch_response){
                error_detail = f"{error_detail} (Reason: {watch_response.get('reason')}, Status: {watch_response.get('details')})";
            }

            self.logger.error(f"Failed to start watch for GDrive ID {gdrive_resource_id}: {error_detail}");
            return {"status": "failed", "message": f"Google API error: {error_detail}"};
        }
    }

    def stop_watching_resource(jiva_channel_uuid: str, initiated_by_user: bool = False) -> Dict {
        drive_handler = self.get_drive_handler();
        if (not drive_handler) {
            return {"status": "failed", "message": "Google Drive Handler not available."};
        }

        watch_info = self.active_watch_channels.get(jiva_channel_uuid);
        if (not watch_info) {
            self.logger.warning(f"Attempted to stop non-existent Jiva watch UUID: {jiva_channel_uuid}");
            return {"status": "not_found", "message": f"Jiva watch UUID {jiva_channel_uuid} not found."};
        }

        google_channel_id = watch_info["google_channel_id"];
        google_resource_id = watch_info["google_resource_id"];

        self.logger.info(f"Stopping watch: Jiva UUID {jiva_channel_uuid}, Google CH ID {google_channel_id}");

        stop_response = drive_handler.stop_channel(
            channel_id=google_channel_id, resource_id=google_resource_id
        );

        remove_from_active = False;
        if (initiated_by_user) { remove_from_active = True; }
        elif (stop_response and stop_response.get("status") == "success") { remove_from_active = True; }
        elif (stop_response and "error" in stop_response and stop_response.get("details") == 404) {
             self.logger.warning(f"Google channel {google_channel_id} (404) during stop. Removing from Jiva active list.");
             remove_from_active = True;
        }

        if (remove_from_active and jiva_channel_uuid in self.active_watch_channels) {
            del self.active_watch_channels[jiva_channel_uuid];
            self.logger.info(f"Removed Jiva watch UUID {jiva_channel_uuid} from active list.");
        }

        if (stop_response and stop_response.get("status") == "success") {
            return {"status": "succeeded", "message": f"Stopped watch for Jiva UUID {jiva_channel_uuid}."};
        } else {
            error_detail = stop_response.get("error", "Unknown error stopping channel.");
            return {"status": "failed", "message": f"Failed to stop watch {jiva_channel_uuid}: {error_detail}"};
        }
    }

    def renew_watch_channel(jiva_channel_uuid: str) -> Dict {
        watch_info = self.active_watch_channels.get(jiva_channel_uuid);
        if (not watch_info) {
            self.logger.warning(f"Cannot renew non-existent Jiva watch UUID: {jiva_channel_uuid}");
            return {"status": "not_found", "message": "Watch not found."};
        }
        gdrive_resource_id_to_watch = watch_info["gdrive_id_watched"];
        resource_type_to_watch = watch_info["type"]; # 'file' or 'folder'

        self.logger.info(f"Renewing watch for Jiva UUID {jiva_channel_uuid}, GDrive ID {gdrive_resource_id_to_watch}.");

        stop_result = self.stop_watching_resource(jiva_channel_uuid=jiva_channel_uuid, initiated_by_user=False);
        # We proceed even if stop fails slightly (e.g. 404), as the old channel might be dead anyway.
        # Critical failure in stop might be logged by stop_watching_resource.
        if (stop_result.get("status") == "failed" and stop_result.get("message") != f"Jiva watch channel UUID {jiva_channel_uuid} not found.") {
            self.logger.warning(f"Attempted to stop old channel {jiva_channel_uuid} during renewal, but it might have failed or was already gone: {stop_result.get('message')}. Proceeding with new watch attempt.");
        }

        return self.start_watching_resource(
            gdrive_resource_id=gdrive_resource_id_to_watch,
            resource_type=resource_type_to_watch, # Pass the type
            webhook_base_url=None # Let start_watching_resource use default/ENV
        );
    }

    def list_active_watches() -> List[Dict] {
        return [
            {
                "jiva_channel_uuid": j_uuid,
                "gdrive_id_watched": info.get("gdrive_id_watched"),
                "type": info.get("type"),
                "google_channel_id": info.get("google_channel_id"),
                "expires_at_iso": datetime.fromtimestamp(info.get("expiration_ms", 0)/1000, tz=timezone.utc).isoformat()
            } for (j_uuid, info) in self.active_watch_channels.items()
        ];
    }

    def pulse() {
        self.logger.debug(f"Pulse: Checking {len(self.active_watch_channels)} GDrive watches.");
        current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000);
        renew_limit_ms = current_time_ms + (self.renew_threshold_hours * 3600 * 1000);
        jiva_uuids_to_check = list(self.active_watch_channels.keys());
        for jiva_uuid in jiva_uuids_to_check {
            watch_info = self.active_watch_channels.get(jiva_uuid);
            if (not watch_info) { continue; }
            if (watch_info.get("expiration_ms", 0) < renew_limit_ms) {
                self.logger.info(f"Watch {jiva_uuid} (GDrive ID: {watch_info.get('gdrive_id_watched')}) needs renewal.");
                self.renew_watch_channel(jiva_channel_uuid=jiva_uuid);
            }
        }
        self.logger.debug("Pulse check for GDrive watches complete.");
    }

    def recover_watches(webhook_base_url: Optional[str] = None) -> Dict {
        self.logger.info(f"Recovering watches for {len(self.watched_gdrive_resources)} DAF-configured resources.");
        results = {"succeeded": [], "failed": []};
        base_url = webhook_base_url if webhook_base_url else self.default_webhook_base_url;
        if (not base_url) {
             base_url = os.environ.get('JIVAS_BASE_URL');
             if (not base_url) {
                self.logger.error("Recovery failed: Webhook base URL not configured.");
                return {"status": "failed", "message": "Webhook base URL not configured."};
             }
             if (not self.default_webhook_base_url) { self.default_webhook_base_url = base_url; }
        }

        for res_conf in self.watched_gdrive_resources {
            gdrive_id = res_conf.get("gdrive_id");
            res_type = res_conf.get("type", "file"); # Default to 'file' if type not specified
            if (gdrive_id) {
                if (not any([info.get("gdrive_id_watched") == gdrive_id for info in self.active_watch_channels.values()])) {
                    start_res = self.start_watching_resource(gdrive_id, res_type, base_url);
                    if (start_res.get("status") == "succeeded") {
                        results["succeeded"].append({"gdrive_id": gdrive_id, "jiva_channel_uuid": start_res.get("jiva_channel_uuid")});
                    } else {
                        results["failed"].append({"gdrive_id": gdrive_id, "reason": start_res.get("message")});
                    }
                } else {
                     results["succeeded"].append({"gdrive_id": gdrive_id, "status": "already_active"});
                }
            }
        }
        return results;
    }

    def start_pulse_scheduler() {
        if (pulse_action := self.get_agent().get_actions().get(action_label="PulseAction")) {
            action_node_label = self.label; # Get the label of this action instance
            interval_string = f'every({self.pulse_interval_seconds}).seconds';

            # Remove existing schedule for this action label first to prevent duplicates
            pulse_action.remove_schedule(action_label=action_node_label); # Use action_label here

            # Add new schedule
            pulse_action.add_schedule(
                action_label=action_node_label, # Pass this action's label
                interval_spec=interval_string   # Pass the interval string
            );
            self.logger.info(f"Pulse schedule added for '{action_node_label}' with interval '{interval_string}'.");
        } else {
            self.logger.warning("PulseAction not found or not enabled. Cannot start GDrive watch renewal pulse.");
        }
    }

    def stop_pulse_scheduler() {
        if (pulse_action := self.get_agent().get_actions().get(action_label="PulseAction")) {
            action_node_label = self.label; # Get the label of this action instance
            pulse_action.remove_schedule(action_label=action_node_label); # Use action_label here
            self.logger.info(f"Pulse schedule removed for '{action_node_label}'.");
        }
    }

    def ingest_drive_items(drive_ids: List[str], item_type: str = "file", user_metadata: Optional[dict] = None) -> dict {
        results = {"succeeded_deepdoc": [], "failed_deepdoc": [], "job_ids": [], "watches_managed": []};
        drive_handler = self.get_drive_handler();
        deepdoc_action = self.get_deepdoc_action();
        if (not drive_handler or not deepdoc_action) {
            msg = "GDrive Handler or DeepDoc action not available.";
            self.logger.error(msg);
            results["failed_deepdoc"] = [{"id": id, "reason": msg} for id in drive_ids];
            return results;
        }

        files_for_deepdoc_payload = []; # List of dicts for DeepDoc: {"name", "content", "type"}
        files_processed_details = [];   # List of dicts: {"id", "name", "mimeType", "parents", "original_item_type"}
                                        # original_item_type is 'file' or 'folder' if drive_id was a folder

        for gdrive_id_or_folder_id in drive_ids {
            original_item_type_for_id = item_type; # 'file' or 'folder' as passed to this ability

            current_files_for_id = []; # Files from this specific gdrive_id_or_folder_id
            if (original_item_type_for_id == "file") {
                file_meta = drive_handler.get_file_metadata(file_id=gdrive_id_or_folder_id);
                if ("error" not in file_meta) {
                    current_files_for_id.append({
                        "id": gdrive_id_or_folder_id, "name": file_meta.get("name"),
                        "mimeType": file_meta.get("mimeType"), "parents": file_meta.get("parents", [])
                    });
                } else { results["failed_deepdoc"].append({"id": gdrive_id_or_folder_id, "reason": f"Metadata error: {file_meta['error']}"}); continue; }
            } elif (original_item_type_for_id == "folder") {
                folder_contents = drive_handler.list_files_in_folder(folder_id=gdrive_id_or_folder_id);
                if ("error" not in folder_contents) {
                    for item_meta in folder_contents {
                        if (not item_meta.get("mimeType", "").startswith("application/vnd.google-apps.folder")) {
                             current_files_for_id.append({
                                "id": item_meta["id"], "name": item_meta.get("name"),
                                "mimeType": item_meta.get("mimeType"), "parents": item_meta.get("parents", [])
                            });
                        }
                    }
                } else { results["failed_deepdoc"].append({"id": gdrive_id_or_folder_id, "reason": f"Folder list error: {folder_contents['error']}"}); continue; }
            }

            for file_detail in current_files_for_id {
                content_data = drive_handler.download_file_content(file_id=file_detail["id"]);
                if (isinstance(content_data, dict) and "error" in content_data) {
                    results["failed_deepdoc"].append({"id": file_detail["id"], "reason": f"Download error: {content_data['error']}"});
                    continue;
                }
                files_for_deepdoc_payload.append({"name": file_detail["name"], "content": content_data, "type": file_detail["mimeType"]});

                # Store details including the original item type (folder or file) that led to this file
                # and the specific parent folder ID of this file.
                file_parent_folder_id = file_detail["parents"][0] if file_detail["parents"] else "root";

                # processed_details =
                files_processed_details.append({
                    "id": file_detail["id"], "name": file_detail["name"],
                    "parent_folder_id_of_file": file_parent_folder_id,
                    "source_gdrive_id_was_folder": (original_item_type_for_id == "folder"),
                    "source_gdrive_id": gdrive_id_or_folder_id,  # The ID that was passed in drive_ids list
                    **(user_metadata or {})  # Unpacks user_metadata if it exists, otherwise empty dict
                });
            }
        }

        if (files_for_deepdoc_payload) {
            # Prepare metadatas (one per file in files_for_deepdoc_payload)
            # This assumes files_for_deepdoc_payload and files_processed_details are in the same order
            # OR we need to match them by name/id if DeepDoc requires aligned metadata
            deepdoc_metadatas = [];
            for i in range(len(files_for_deepdoc_payload)) {
                processed_file_detail = files_processed_details[i]; # Assuming alignment
                metadata = {
                    "source_system": "google_drive",
                    "google_drive_file_id": processed_file_detail["id"],
                    "google_drive_filename": processed_file_detail["name"],
                    "google_drive_folder_id": processed_file_detail["parent_folder_id_of_file"]
                };
                if (user_metadata) { metadata.update(user_metadata); }
                deepdoc_metadatas.append(metadata);
            }

            # log metadata before
            self.logger.warning(f"MetaDataBefore: {deepdoc_metadatas}");

            job_id = deepdoc_action.queue_deepdoc_job(files=files_for_deepdoc_payload, metadatas=deepdoc_metadatas, callback_url="");
            if (job_id) {
                results["job_ids"].append(job_id);
                for detail in files_processed_details { # Iterate over successfully prepared files
                    results["succeeded_deepdoc"].append({"id": detail["id"], "name": detail["name"], "job_id": job_id});

                    # Log Metadata After
                    self.logger.warning(f"MetaDataBefore: {detail}");

                    # --- WATCHER LOGIC POST-INGESTION ---
                    if (self.auto_watch_on_ingest) {
                        watch_target_id = "";
                        watch_type = "";
                        if (detail["source_gdrive_id_was_folder"]) { # If the original item was a folder
                            watch_target_id = detail["source_gdrive_id"]; # Watch the folder
                            watch_type = "folder";
                        } else { # Original item was a file (standalone)
                            watch_target_id = detail["id"]; # Watch the file itself
                            watch_type = "file";
                        }

                        # Check if a watch for this target_id already exists to avoid duplicates
                        already_watching_target = False;
                        for (j_uuid, existing_watch) in self.active_watch_channels.items() {
                            if (existing_watch.get("gdrive_id_watched") == watch_target_id) {
                                already_watching_target = True;
                                results["watches_managed"].append({
                                    "gdrive_id": watch_target_id, "type": watch_type,
                                    "status": "already_active", "jiva_channel_uuid": j_uuid
                                });
                                break;
                            }
                        }

                        if (not already_watching_target) {
                            watch_result = self.start_watching_resource(
                                gdrive_resource_id=watch_target_id,
                                resource_type=watch_type, # Pass the determined type
                                webhook_base_url=None
                            );
                            results["watches_managed"].append({
                                "gdrive_id": watch_target_id, "type": watch_type,
                                "status": watch_result.get("status"),
                                "jiva_channel_uuid": watch_result.get("jiva_channel_uuid"),
                                "message": watch_result.get("message")
                            });
                        }
                    }
                }
            } else { # DeepDoc job queuing failed
                 for detail in files_processed_details {
                    results["failed_deepdoc"].append({"id": detail["id"], "name": detail["name"], "reason": "DeepDoc job queuing failed"});
                }
            }
        }
        return results;
    }

    def remove_drive_item_from_vector_store(google_drive_file_id: str) -> Dict {
        result = {"status": "failed", "message": "", "watch_management_status": "not_attempted"};
        deepdoc_action = self.get_deepdoc_action();
        if (not deepdoc_action) { result["message"] = "DeepDoc action not found."; return result;}

        all_doc_entries = deepdoc_action.get_doc_entries();
        found_entry_metadata = None;
        job_id_to_delete = None;
        filename_to_delete = None;

        for entry in all_doc_entries {
            entry_meta = entry.get("metadata", {});
            if (entry_meta.get("google_drive_file_id") == google_drive_file_id) {
                found_entry_metadata = entry_meta;
                job_id_to_delete = entry.get("job_id");
                filename_to_delete = entry.get("filename");
                break;
            }
        }

        if (found_entry_metadata and job_id_to_delete) {
            if (deepdoc_action.delete_doc_entry(job_id=job_id_to_delete, filename=filename_to_delete)) {
                result["status"] = "succeeded";
                result["message"] = f"Deleted GDrive ID {google_drive_file_id} from DeepDoc.";

                # --- WATCHER LOGIC POST-DELETION (SINGLE FILE) ---
                if (self.auto_watch_on_ingest) {
                    parent_folder_id = found_entry_metadata.get("google_drive_folder_id");

                    if (parent_folder_id and parent_folder_id != "root" and parent_folder_id != "none") {
                        # File was part of a watched folder
                        # Check if other files from this folder still exist in DeepDoc
                        other_files_in_folder_exist = False;
                        current_all_docs = deepdoc_action.get_doc_entries(); # Re-fetch
                        for doc_entry in current_all_docs {
                            if (doc_entry.get("metadata", {}).get("google_drive_folder_id") == parent_folder_id) {
                                other_files_in_folder_exist = True;
                                break;
                            }
                        }
                        if (not other_files_in_folder_exist) {
                            # Last file in folder deleted, stop watching the folder
                            jiva_uuid_folder_watch = None;
                            for (j_uuid, w_info) in self.active_watch_channels.items() {
                                if (w_info.get("gdrive_id_watched") == parent_folder_id and w_info.get("type") == "folder") {
                                    jiva_uuid_folder_watch = j_uuid; break;
                                }
                            }
                            if (jiva_uuid_folder_watch) {
                                stop_res = self.stop_watching_resource(jiva_uuid_folder_watch, False);
                                result["watch_management_status"] = f"Folder {parent_folder_id} watch stop: {stop_res.get('status')}";
                            } else { result["watch_management_status"] = "Folder watch not found for emptied folder."; }
                        } else { result["watch_management_status"] = "Folder still has items; folder watch retained."; }
                    } else {
                        # Standalone file deleted, stop watching the file itself
                        jiva_uuid_file_watch = None;
                        for (j_uuid, w_info) in self.active_watch_channels.items() {
                            if (w_info.get("gdrive_id_watched") == google_drive_file_id and w_info.get("type") == "file") {
                                jiva_uuid_file_watch = j_uuid; break;
                            }
                        }
                        if (jiva_uuid_file_watch) {
                            stop_res = self.stop_watching_resource(jiva_uuid_file_watch, False);
                            result["watch_management_status"] = f"File {google_drive_file_id} watch stop: {stop_res.get('status')}";
                        } else { result["watch_management_status"] = "File watch not found for deleted file."; }
                    }
                }
            } else { result["message"] = f"DeepDoc failed to delete {google_drive_file_id}."; }
        } else { result["message"] = f"GDrive ID {google_drive_file_id} not found in DeepDoc."; }
        return result;
    }

    def remove_drive_folder_from_vector_store(google_drive_folder_id: str) -> Dict {
        results = {"deleted_files": [], "failed_to_delete_from_deepdoc": [], "watches_stopped": [], "watches_failed_to_stop": [], "message": ""};
        deepdoc_action = self.get_deepdoc_action();
        if (not deepdoc_action) {
            results["message"] = "DeepDoc action not found.";
            return results;
        }

        all_doc_entries = deepdoc_action.get_doc_entries();
        files_in_folder_to_process = []; # Renamed to avoid confusion with files_to_process in ingest

        for entry in all_doc_entries {
            if (entry.get("metadata", {}).get("google_drive_folder_id") == google_drive_folder_id) {
                files_in_folder_to_process.append({
                    "job_id": entry["job_id"],
                    "filename": entry["filename"], # DeepDoc internal filename
                    "gdrive_file_id": entry.get("metadata", {}).get("google_drive_file_id", "unknown")
                });
            }
        }

        if (not files_in_folder_to_process) {
            results["message"] = f"No DeepDoc entries found for Google Drive folder ID: {google_drive_folder_id}.";
            self.logger.info(results["message"]);
            return results;
        }

        self.logger.info(f"Found {len(files_in_folder_to_process)} files from GDrive folder {google_drive_folder_id} to remove from vector store.");

        gdrive_ids_successfully_deleted_from_deepdoc = [];

        for item_to_delete in files_in_folder_to_process {
            if (deepdoc_action.delete_doc_entry(job_id=item_to_delete["job_id"], filename=item_to_delete["filename"])) {
                results["deleted_files"].append(item_to_delete["gdrive_file_id"]); # List of GDrive IDs successfully deleted from DeepDoc
                gdrive_ids_successfully_deleted_from_deepdoc.append(item_to_delete["gdrive_file_id"]);
            } else {
                results["failed_to_delete_from_deepdoc"].append(item_to_delete["gdrive_file_id"]);
            }
        }

        # If the entire folder's content representation in DeepDoc is removed, stop watching the folder.
        if (self.auto_watch_on_ingest) {
            jiva_uuid_folder_watch = None;
            for (j_uuid, watch_info) in self.active_watch_channels.items() {
                if (watch_info.get("gdrive_id_watched") == google_drive_folder_id and watch_info.get("type") == "folder") {
                    jiva_uuid_folder_watch = j_uuid;
                    break;
                }
            }
            if (jiva_uuid_folder_watch) {
                stop_res = self.stop_watching_resource(jiva_channel_uuid=jiva_uuid_folder_watch, initiated_by_user=False);
                results["watch_management_status"] = f"Folder {google_drive_folder_id} watch stop: {stop_res.get('status')}";
            } else {
                results["watch_management_status"] = f"No active watch found for folder {google_drive_folder_id}.";
            }
        }

        if (results["failed_to_delete_from_deepdoc"]) {
            results["message"] = f"Attempted to remove folder {google_drive_folder_id} from DeepDoc. Succeeded for {len(results['deleted_files'])} files, failed for {len(results['failed_to_delete_from_deepdoc'])} files.";
        } else {
            results["message"] = f"Successfully requested removal of all {len(results['deleted_files'])} files from folder {google_drive_folder_id} via DeepDoc.";
        }
        if (results["watches_failed_to_stop"]) {
            results["message"] += f" Auto-unwatch: succeeded for {len(results['watches_stopped'])} files, failed for {len(results['watches_failed_to_stop'])} files.";
        } elif (results["watches_stopped"]) {
             results["message"] += f" Auto-unwatch: successfully stopped watches for {len(results['watches_stopped'])} files.";
        }


        self.logger.info(results["message"]);
        return results;
    }

    def _get_gdrive_id_from_resource_uri(resource_uri: str) -> Optional[str] {
        # Helper to extract the GDrive ID from X-Goog-Resource-URI
        # Example URI: https://www.googleapis.com/drive/v3/files/FILE_ID?alt=json
        # Example URI for changes API: https://www.googleapis.com/drive/v3/changes/CHANGE_ID?alt=json (less useful here)
        try {
            parsed_url = urlparse(resource_uri);
            path_parts = parsed_url.path.strip('/').split('/');
            # Look for 'files' or 'folders' segment, ID is usually after it.
            # This is a bit heuristic. Google's docs should be checked for canonical parsing.
            if ("files" in path_parts) {
                id_index = path_parts.index("files") + 1;
                if (id_index < len(path_parts)) {
                    return path_parts[id_index];
                }
            }
             # Add similar logic for 'folders' if needed, though watch is on fileId
        } except Exception as e {
            self.logger.error(f"Error parsing GDrive resource URI '{resource_uri}': {e}");
        }
        return None;
    }

    def process_drive_notification(headers: Dict, body_str: str) {
        drive_handler = self.get_drive_handler();
        if (not drive_handler) {
            return {"status": "failed", "message": "Google Drive Handler not available."};
        }

        google_channel_id = headers.get('X-Goog-Channel-ID');
        resource_state = headers.get('X-Goog-Resource-State');
        google_resource_id_header = headers.get('x-goog-resource-id');
        # Changed header gives hints like 'content,children' or 'properties'
        google_changed_header = headers.get('X-Goog-Changed', '');
        # Resource URI of the item that *actually changed* (could be a file within a watched folder)
        changed_resource_uri = headers.get('X-Goog-Resource-URI');

        self.logger.info(f"GDrive Notification: GoogleChannelID={google_channel_id}, State={resource_state}, ChangedURI={changed_resource_uri}, GoogleChangedHeader={google_changed_header}");

        jiva_uuid_found = None;
        watch_info = None;
        for (j_uuid, w_info) in self.active_watch_channels.items() {
            if (w_info.get("google_channel_id") == google_channel_id) {
                jiva_uuid_found = j_uuid;
                watch_info = w_info;
                break;
            }
        }

        if (not watch_info) {
            self.logger.warning(f"Received notification for unknown or stopped Google Channel ID: {google_channel_id}. It might have been stopped/expired.");
            # Google might send a final notification after a channel is stopped.
            # Attempt to tell Google to stop it again if it's truly unknown, to be safe, though it might 404.
            if (google_channel_id and google_resource_id_header) {
                    drive_handler.stop_channel(channel_id=google_channel_id, resource_id=google_resource_id_header);
            }
            return;
        }

        # This is the GDrive ID we set up the watch on (could be a file or a folder)
        watched_gdrive_id = watch_info.get("gdrive_id_watched");
        watched_type = watch_info.get("type"); # 'file' or 'folder'

        # --- Handle different resource states ---
        if (resource_state == "sync") {
            self.logger.info(f"Sync notification for watch {jiva_uuid_found} on {watched_gdrive_id}.");
            return;
        }

        # log type and other stuff needed for debugging
        self.logger.info(f"Watch Type: {watched_type}");

        # grab the change now and log
        (new_changes, page_token) = drive_handler.get_latest_changes(page_token=self.page_token);

        # log responses for debugging
        self.logger.info(f"Last Page Token: {page_token}, Last Drive Change {new_changes}");

        # set changes
        changes = new_changes if new_changes else [];

        # set page token
        self.page_token = page_token;

        # process changes
        for changed_gdrive_resource in changes {
            # log initial resource state
            self.logger.info(f"Resource State: {resource_state} {changed_gdrive_resource.get('file', {})} {changed_gdrive_resource.get('file', {}).get('trashed')}");

            # Determine the ID of the specific file/item that changed, from the changes
            changed_gdrive_file_id = changed_gdrive_resource.get('fileId');
            resource_state = "trash" if changed_gdrive_resource.get('file', {}).get('trashed') else "change";

            self.logger.info(f"Resource State: {resource_state}");

            if (not changed_gdrive_file_id) {
                self.logger.error(f"Could not extract changed GDrive File ID from changes: {changed_gdrive_resource}. Aborting processing for this notification.");
                continue;
            }

            if (resource_state in ["trash", "remove", "trashed"]) {
                self.logger.info(f"'{resource_state}' notification for item {changed_gdrive_file_id} (watched: {watched_gdrive_id} as {watched_type})");

                # Remove the specific changed item from DeepDoc
                self.remove_drive_item_from_vector_store(google_drive_file_id=changed_gdrive_file_id); # This will handle its own watch logic

                # If the watched item was a FOLDER and this deleted file was the LAST one in it (in DeepDoc)
                if (watched_type == "folder" and changed_gdrive_file_id != watched_gdrive_id) { # Check if not the folder itself
                    # Re-check if the folder is now empty in DeepDoc
                    if (not self._is_folder_still_represented_in_deepdoc(watched_gdrive_id)) {
                        self.logger.info(f"Watched folder {watched_gdrive_id} is now empty in DeepDoc. Stopping watch on folder.");
                        self.stop_watching_resource(jiva_channel_uuid=jiva_uuid_found, initiated_by_user=False);
                    }
                } elif (watched_type == "file" and changed_gdrive_file_id == watched_gdrive_id) {
                    # The watched standalone file itself was deleted. remove_drive_item_from_vector_store should have stopped its watch.
                    # If not, ensure it's stopped here (though it might be redundant).
                    if (jiva_uuid_found in self.active_watch_channels) { # Check if stop_watching_resource inside remove didn't already get it
                        self.logger.info(f"Ensuring watch for deleted standalone file {watched_gdrive_id} is stopped.");
                        self.stop_watching_resource(jiva_channel_uuid=jiva_uuid_found, initiated_by_user=False);
                    }
                }
                continue;
            }

            if (resource_state == "change" or headers.get('X-Goog-Changed')) {
                self.logger.info(f"'change' notification for item {changed_gdrive_file_id} (watched: {watched_gdrive_id} as {watched_type})");

                if (watched_type == "folder") {
                    # If a folder is watched, a "change" could be:
                    # 1. Metadata change on the folder itself (changed_gdrive_file_id == watched_gdrive_id)
                    # 2. A file within the folder changed (changed_gdrive_file_id != watched_gdrive_id)
                    # 3. A new file was added to the folder (Google might report change on folder, or directly on new file if that's how watches work)

                    # For simplicity, if a folder watch gets a 'change', we assume a file within it changed or was added.
                    # The most robust way is to re-ingest the specific 'changed_gdrive_file_id'.
                    # If 'changed_gdrive_file_id' is the folder ID itself, one might re-scan the folder for new/modified files.
                    # For now, let's assume 'change' on a folder watch implies we should re-ingest the 'changed_gdrive_file_id' if it's a folder item.

                    if (drive_handler) {
                        meta = drive_handler.get_file_metadata(file_id=changed_gdrive_file_id);
                        if ("error" not in meta and not meta.get("mimeType", "").startswith("application/vnd.google-apps.folder")) {
                            self.logger.info(f"File {changed_gdrive_file_id} in watched folder {watched_gdrive_id} changed. Re-ingesting file.");
                            self.remove_drive_item_from_vector_store(google_drive_file_id=changed_gdrive_file_id);

                            # log details
                            self.logger.warning(f"Logging Important stuff to debug why ingesting is creating new watcher {watched_gdrive_id}");
                            self.ingest_drive_items(drive_ids=[changed_gdrive_file_id], item_type="file", user_metadata={"trigger": "webhook_folder_watch_change", "source_gdrive_id": watched_gdrive_id, "google_drive_folder_id": watched_gdrive_id, "source_gdrive_id_was_folder": True});
                        } elif ("error" in meta) {
                            self.logger.error(f"Could not get metadata for changed item {changed_gdrive_file_id} in watched folder.");
                        } else { # It's the folder itself or another sub-folder that changed.
                            self.logger.info(f"Change detected on folder {changed_gdrive_file_id} (possibly watched folder {watched_gdrive_id} or a subfolder). Consider re-scanning for new/modified files if deeper sync is needed.");
                            # Potentially trigger a full re-scan and ingest of the watched_gdrive_id if changed_gdrive_file_id == watched_gdrive_id
                            # For now, if it's the folder itself, we might just log or do nothing further beyond specific file changes.
                            # If X-Goog-Changed indicates 'children', a re-list and diff would be ideal.
                            # Current simplified: If it's a file, ingest. If it's the folder, log.
                        }
                    }
                } elif (watched_type == "file") { # Standalone file watch
                    if (changed_gdrive_file_id == watched_gdrive_id) {
                        self.logger.info(f"Watched file {watched_gdrive_id} changed. Re-ingesting.");
                        self.remove_drive_item_from_vector_store(google_drive_file_id=watched_gdrive_id);
                        self.ingest_drive_items(drive_ids=[watched_gdrive_id], item_type="file", user_metadata={"trigger": "webhook_file_watch_change"});
                    } else {
                        self.logger.warning(f"Change notification for {changed_gdrive_file_id} but was watching {watched_gdrive_id}. Mismatch?");
                    }
                }
                continue;
            }
            self.logger.warning(f"Unhandled GDrive notification state '{resource_state}' for watch {jiva_uuid_found}.");
        }

    }

    def _is_folder_still_represented_in_deepdoc(folder_gdrive_id: str) -> bool {
        # Helper to check if any files from a given folder_gdrive_id are still in DeepDoc
        deepdoc_action = self.get_deepdoc_action();
        if (not deepdoc_action) { return False; } # Assume not, if DeepDoc is unavailable

        all_docs = deepdoc_action.get_doc_entries();
        for doc in all_docs {
            if (doc.get("metadata", {}).get("google_drive_folder_id") == folder_gdrive_id) {
                return True; # Found at least one file from this folder
            }
        }
        return False; # No files from this folder found
    }

    def healthcheck() -> Union[bool, Dict] {
        drive_handler = self.get_drive_handler();
        if (not drive_handler) {
            return { "status": False, "message": "GDrive Handler failed to initialize.", "severity": "error"};
        }
        deepdoc_action = self.get_deepdoc_action();
        if (not deepdoc_action) {
            return { "status": False, "message": f"DeepDocClientAction ('{self.deepdoc_action_label}') not found.", "severity": "error"};
        }
        # Add check for webhook base URL if auto-watch is intended via DAF
        if (self.watched_gdrive_resources and not self.default_webhook_base_url and not os.environ.get('JIVAS_BASE_URL')) {
             self.logger.warning("watched_gdrive_resources are configured, but no webhook base URL (DAF/ENV). Auto-recovery might fail.");
        }
        try {
            folder_to_test = self.default_folder_id if self.default_folder_id else "root";
            test_list = drive_handler.list_files_in_folder(folder_id=folder_to_test, page_size=1);
            if ("error" in test_list) {
                return { "status": False, "message": f"GDrive API error: {test_list['error']}", "severity": "error"};
            }
            return True;
        } except Exception as e {
            return { "status": False, "message": f"GDrive healthcheck exception: {e}", "severity": "error"};
        }
    }

    def list_gdrive_folder_contents(folder_id: str) -> List {
        drive_handler = self.get_drive_handler();
        if (not drive_handler) { return [{"error": "Drive Handler not ready"}]; }
        return drive_handler.list_files_in_folder(folder_id=folder_id if folder_id else self.default_folder_id);
    }

    def get_ingested_documents_from_drive() -> List {
        deepdoc_action = self.get_deepdoc_action();
        if (not deepdoc_action) { return [{"error": "DeepDoc action not found."}]; }
        all_docs = deepdoc_action.get_doc_entries();
        gdrive_docs = [doc for doc in all_docs if doc.get("metadata", {}).get("source_system") == "google_drive"];
        return gdrive_docs;
    }
}
