import json
import time
import uuid
from hi_agent.server.team_event_store import TeamEvent, TeamEventStore


class TeamSpace:
    def __init__(self, tenant_id: str, team_space_id: str, event_store: TeamEventStore) -> None:
        self._tenant_id = tenant_id
        self._team_space_id = team_space_id
        self._store = event_store

    def publish(
        self,
        event_type: str,
        payload: dict,
        source_run_id: str,
        source_user_id: str,
        source_session_id: str,
        publish_reason: str = "explicit",
        schema_version: int = 1,
    ) -> None:
        event = TeamEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self._tenant_id,
            team_space_id=self._team_space_id,
            event_type=event_type,
            payload_json=json.dumps(payload),
            source_run_id=source_run_id,
            source_user_id=source_user_id,
            source_session_id=source_session_id,
            publish_reason=publish_reason,
            schema_version=schema_version,
            created_at=time.time(),
        )
        self._store.insert(event)
