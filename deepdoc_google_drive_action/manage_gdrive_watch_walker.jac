import from typing { List, Dict, Optional, Literal }
import from jivas.agent.action.agent_graph_walker { agent_graph_walker }
import from jivas.agent.modules.action.path { action_walker_path }
import from jivas.agent.core.agent { Agent }
import from jivas.agent.action.action { Action }
import from jivas.agent.action.actions { Actions }

walker manage_gdrive_watch_walker(agent_graph_walker) {
    has operation: Literal["start", "stop", "list", "renew", "recover"] = "list";
    has gdrive_resource_id: Optional[str] = None;
    has jiva_channel_uuid: Optional[str] = None; # Jiva's internal UUID for the watch
    has webhook_base_url: Optional[str] = None; # Needed for start, e.g., "https://your-jiva-instance.com"
    has resource_type: Optional[str] = None; # resource type to be monitored

    has response: Dict = {};
    has reporting:bool = True;

    class __specs__ {
        static has private: bool = False;
        static has path: str = action_walker_path(__module__);
    }

    can on_agent with Agent entry {
        visit [-->](`?Actions);
    }

    can on_actions with Actions entry {
        visit [-->](`?Action)(?enabled==True)(?label=='DeepDocGoogleDriveAction');
    }

    can on_google_drive_action with Action entry {
        if (self.operation == "start") {
            if (self.gdrive_resource_id and self.webhook_base_url) {
                self.response = here.start_watching_resource(
                    gdrive_resource_id=self.gdrive_resource_id,
                    webhook_base_url=self.webhook_base_url,
                    resource_type=self.resource_type
                );
            } else {
                self.response = {"status": "failed", "message": "gdrive_resource_id and webhook_base_url are required for start operation."};
            }
        } elif (self.operation == "stop") {
            if (self.jiva_channel_uuid) {
                self.response = here.stop_watching_resource(jiva_channel_uuid=self.jiva_channel_uuid, initiated_by_user=True);
            } else {
                self.response = {"status": "failed", "message": "jiva_channel_uuid is required for stop operation."};
            }
        } elif (self.operation == "list") {
            self.response = {"active_watches": here.list_active_watches()};
        } elif (self.operation == "renew") { # For manual testing/triggering
            if (self.jiva_channel_uuid) {
                self.response = here.renew_watch_channel(jiva_channel_uuid=self.jiva_channel_uuid);
            } else {
                self.response = {"status": "failed", "message": "jiva_channel_uuid is required for renew operation."};
            }
        } elif (self.operation == "recover") {
             self.response = here.recover_watches(webhook_base_url=self.webhook_base_url); # webhook_base_url might be needed if stored globally
        } else {
            self.response = {"status": "failed", "message": f"Unknown operation: {self.operation}"};
        }

        if self.reporting {
            report self.response;
        }
    }
}