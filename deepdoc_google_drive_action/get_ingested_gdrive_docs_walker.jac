# --- Walkers for DeepDocGoogleDriveAction UI interaction ---

import:py from typing { List, Dict, Optional }
import:jac from jivas.agent.action.interact_graph_walker { interact_graph_walker }
import:jac from jivas.agent.core.agent { Agent }
import:jac from jivas.agent.action.action { Action }
import:jac from jivas.agent.action.actions { Actions }


# Walker to get documents ingested from Google Drive (from DeepDoc manifest)
walker get_ingested_gdrive_docs_walker :interact_graph_walker: {
    has response: List = []; # Will be a list of dicts or list containing an error dict

    can on_agent with Agent entry {
        visit [-->](`?Actions);
    }
    can on_actions with Actions entry {
        visit [-->](`?Action)(?enabled==True)(?label=='DeepDocGoogleDriveAction');
    }
    can on_google_drive_action with Action entry {
        self.response = here.get_ingested_documents_from_drive();
    }
}