# --- Walkers for DeepDocGoogleDriveAction UI interaction ---

import:py from typing { List, Dict, Optional }
import:jac from jivas.agent.action.interact_graph_walker { interact_graph_walker }
import:jac from jivas.agent.core.agent { Agent }
import:jac from jivas.agent.action.action { Action }
import:jac from jivas.agent.action.actions { Actions }


# Walker to trigger ingestion of Drive items
walker ingest_gdrive_items_walker :interact_graph_walker: {
    has drive_ids: List[str] = [];
    has item_type: str = "file"; # "file" or "folder"
    has user_metadata: Optional[Dict] = {};
    has response: Dict = {};

    can on_agent with Agent entry {
        visit [-->](`?Actions);
    }
    can on_actions with Actions entry {
        # Find the specific DeepDocGoogleDriveAction instance
        visit [-->](`?Action)(?enabled==True)(?label=='DeepDocGoogleDriveAction'); # Assuming default label. If action was renamed please change here
    }
    can on_google_drive_action with Action entry {
        # Call the ingest_drive_items ability
        self.response = here.ingest_drive_items(
            drive_ids=self.drive_ids,
            item_type=self.item_type,
            user_metadata=self.user_metadata
        );
    }
}