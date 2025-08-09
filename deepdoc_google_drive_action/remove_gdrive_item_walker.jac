# --- Walkers for DeepDocGoogleDriveAction UI interaction ---

import from typing { List, Dict, Optional }
import from jivas.agent.modules.action.path { action_walker_path }
import from jivas.agent.action.agent_graph_walker { agent_graph_walker }
import from jivas.agent.core.agent { Agent }
import from jivas.agent.action.action { Action }
import from jivas.agent.action.actions { Actions }


# Walker to remove a single Drive item from the vector store
walker remove_gdrive_item_walker(agent_graph_walker) {
    has google_drive_file_id: str = "";
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
        self.response = here.remove_drive_item_from_vector_store(
            google_drive_file_id=self.google_drive_file_id
        );
        if self.reporting {
            report self.response;
        }
    }
}