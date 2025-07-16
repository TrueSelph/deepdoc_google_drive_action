# --- Walkers for DeepDocGoogleDriveAction UI interaction ---

import from typing { List, Dict, Optional }
import from jivas.agent.action.agent_graph_walker { agent_graph_walker }
import from jivas.agent.core.agent { Agent }
import from jivas.agent.action.action { Action }
import from jivas.agent.action.actions { Actions }


# Walker to list GDrive folder contents (directly from GDrive)
walker list_gdrive_folder_contents_walker(agent_graph_walker) {
    has folder_id: str = "";
    has response: List = [];

    can on_agent with Agent entry {
        visit [-->](`?Actions);
    }
    can on_actions with Actions entry {
        visit [-->](`?Action)(?enabled==True)(?label=='DeepDocGoogleDriveAction');
    }
    can on_google_drive_action with Action entry {
        self.response = here.list_gdrive_folder_contents(folder_id=self.folder_id);
    }
}