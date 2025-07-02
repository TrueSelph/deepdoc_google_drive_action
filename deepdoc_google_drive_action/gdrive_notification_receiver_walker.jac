import logging;
import json; # If body is JSON
import from logging { Logger }
import from jivas.agent.action.interact_graph_walker { interact_graph_walker }
import from jivas.agent.core.agent { Agent }
import from jivas.agent.action.action { Action }
import from jivas.agent.action.actions { Actions }
import from jac_cloud.plugin.jaseci { JacPlugin as Jac }


walker gdrive_notification_receiver_walker(interact_graph_walker) {
    static has logger:Logger = logging.getLogger(__name__);

    has headers:dict = {};
    has params:dict = {}; # For query params if any
    has body:dict = {};   # Raw request body
    has response:dict = {"status": "received"}; # Default response to Google

    can on_agent with Agent entry {
        self.logger.warning(f"Headers: {self.headers}, Params: {self.params}, Body: {self.body}");
        # Basic validation
        if (not self.headers.get('X-Goog-Channel-ID') or not self.headers.get('X-Goog-Resource-ID')) {
            self.logger.warning("Received GDrive notification without required headers. Ignoring.");

            Jac.get_context().status = 400; # Bad Request
            disengage;
        }

        # Find the DeepDocGoogleDriveAction
        if (dd_gdrive_action := here.get_actions().get(action_label='DeepDocGoogleDriveAction')) {
            # Delegate processing to the action
            dd_gdrive_action.process_drive_notification(
                headers=self.headers,
                body_str=self.body # Pass raw body string
            );
            Jac.get_context().status = 200; # Acknowledge receipt
        } else {
            self.logger.error("DeepDocGoogleDriveAction not found or not enabled. Cannot process GDrive notification.");
            Jac.get_context().status = 500; # Internal Server Error
        }
        disengage; # Walker's job is done after delegation
    }
}