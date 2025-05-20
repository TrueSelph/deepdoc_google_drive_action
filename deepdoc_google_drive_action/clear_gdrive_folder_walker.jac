# --- Walkers for DeepDocGoogleDriveAction UI interaction ---

import:py from typing { List, Dict, Optional }
import:jac from jivas.agent.action.interact_graph_walker { interact_graph_walker }
import:jac from jivas.agent.core.agent { Agent }
import:jac from jivas.agent.action.action { Action }
import:jac from jivas.agent.action.actions { Actions }


# Walker to remove all items from a Drive folder from the vector store
walker clear_gdrive_folder_walker :interact_graph_walker: {
    has google_drive_folder_id: str = "";
    has response: Dict = {};

    can on_agent with Agent entry {
        visit [-->](`?Actions);
    }
    can on_actions with Actions entry {
        visit [-->](`?Action)(?enabled==True)(?label=='DeepDocGoogleDriveAction');
    }
    can on_google_drive_action with Action entry {
        self.response = here.remove_drive_folder_from_vector_store(
            google_drive_folder_id=self.google_drive_folder_id
        );
    }
}