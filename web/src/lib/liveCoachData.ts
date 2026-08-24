/* Adapts GET /teams/{team_id}/roster and GET /teams/{team_id}/athletes/{id}
 * (backend/app/routes/teams.py) into the same TeamAthleteProjection shape
 * TeamOverviewScreen/AthleteDetailScreen already render from demoData.ts.
 * This is a mapping layer only -- it never recomputes acute_load/
 * chronic_load/load_ratio/data_quality/grantedScopes, all of which come
 * straight from the server's Coach Roster Row projection (mirrors
 * liveTrainingLoad.ts's relationship to the training-load trend endpoint).
 *
 * Injury summary and detail are mapped independently because each field has
 * its own consent scope on the server.
 */

import type {
  CoachRosterRowWireResponse,
  TeamRosterWireResponse,
} from "../data/apiClient.ts";
import type { ConsentScope, DataQuality, MembershipStatus, TeamAthleteProjection } from "./types.ts";

const QUALITY_MAP: Record<NonNullable<CoachRosterRowWireResponse["data_quality"]>, DataQuality> = {
  SUFFICIENT: "OK",
  LOW: "LOW",
  INSUFFICIENT: "INSUFFICIENT",
};

export function adaptCoachRosterRow(wire: CoachRosterRowWireResponse): TeamAthleteProjection {
  return {
    athleteId: wire.athlete_id,
    name: wire.name,
    joinedAtUtc: wire.joined_at ?? "",
    status: wire.status as MembershipStatus,
    grantedScopes: wire.granted_scopes as ConsentScope[],
    acuteLoadAu: wire.acute_load_au,
    chronicLoadAu: wire.chronic_load_au,
    loadRatio: wire.load_ratio,
    dataQuality: wire.data_quality ? QUALITY_MAP[wire.data_quality] : "INSUFFICIENT",
    lastActivityLocalDate: wire.last_activity_local_date,
    last14DaysLoad: wire.last_14_days_load,
    injuryHasIssue: wire.injury_has_issue,
    injurySeverityBand: wire.injury_severity_band as TeamAthleteProjection["injurySeverityBand"],
    injuryFreeText: wire.injury_free_text,
  };
}

export function adaptTeamRoster(wire: TeamRosterWireResponse): TeamAthleteProjection[] {
  return wire.items.map(adaptCoachRosterRow);
}
