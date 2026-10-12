"""team chat: coach <-> athletes rooms, the @AI helper's cards, plan batches

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-09

chat_rooms: one team room per team (every active member) and one direct
room per (team, athlete) shared by that athlete and the team's coaches.

chat_messages: text messages from members, the AI helper (only ever in
reply to an @AI) and the system (e.g. "plan scheduled"). Retracting a
message keeps the row (retracted_at) so the room shows "訊息已收回".

chat_cards: what the @AI helper prepared for one person to confirm --
a coach's plan (dates x athletes x sessions) or an athlete's body-status
report. A card is only ever visible to its owner, and nothing is written
to assignments / injury reports until the owner confirms it.

chat_reads: per member, the last message seen in each room (unread badges).

assignment_batches + assigned_workouts.batch_id: every assignment created
from one confirmed plan card, so the plan can be revoked as a whole later.
assigned_workouts.tracked = false for strength / core sessions: scheduled
for the athlete to see, never marked done or missed. assigned_workouts.notes
holds such a session's content (the exercise list).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_ACTOR = "NULLIF(current_setting('app.actor_user_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "chat_rooms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("athlete_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("(kind = 'team' AND athlete_id IS NULL) OR (kind = 'direct' AND athlete_id IS NOT NULL)",
                           name="ck_chat_rooms_kind"),
    )
    op.create_index("uq_chat_rooms_team", "chat_rooms", ["team_id"], unique=True,
                    postgresql_where=sa.text("kind = 'team'"))
    op.create_index("uq_chat_rooms_direct", "chat_rooms", ["team_id", "athlete_id"], unique=True,
                    postgresql_where=sa.text("kind = 'direct'"))

    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("chat_rooms.id"), nullable=False),
        sa.Column("sender_kind", sa.Text(), nullable=False),
        sa.Column("sender_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mentions_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        # @AI processing state of a user message: pending | done | failed
        sa.Column("ai_state", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sender_kind IN ('user', 'ai', 'system')", name="ck_chat_messages_sender_kind"),
        sa.CheckConstraint("(sender_kind = 'user') = (sender_id IS NOT NULL)", name="ck_chat_messages_sender"),
        sa.CheckConstraint("char_length(body) <= 4000", name="ck_chat_messages_length"),
    )
    op.create_index("ix_chat_messages_room_created", "chat_messages", ["room_id", "created_at"])

    op.create_table(
        "chat_cards",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("chat_rooms.id"), nullable=False),
        sa.Column("source_message_id", UUID(as_uuid=True), sa.ForeignKey("chat_messages.id"), nullable=False),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('plan', 'body_report')", name="ck_chat_cards_kind"),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'dismissed', 'cancelled')", name="ck_chat_cards_status"),
    )
    op.create_index("ix_chat_cards_room_owner", "chat_cards", ["room_id", "owner_id"])

    op.create_table(
        "chat_reads",
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("chat_rooms.id"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "assignment_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("card_id", UUID(as_uuid=True), sa.ForeignKey("chat_cards.id"), nullable=True),
        sa.Column("summary", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("assigned_workouts", sa.Column("batch_id", UUID(as_uuid=True),
                                                 sa.ForeignKey("assignment_batches.id"), nullable=True))
    op.add_column("assigned_workouts", sa.Column("tracked", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("assigned_workouts", sa.Column("notes", sa.Text(), nullable=True))

    # runtime role grants + row-level security (the API also checks
    # membership explicitly; these are the defence in depth)
    op.execute("GRANT SELECT, INSERT ON chat_rooms TO runsense_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE ON chat_messages, chat_cards, chat_reads, assignment_batches "
               "TO runsense_runtime")
    op.execute("GRANT UPDATE ON assigned_workouts TO runsense_runtime")
    for table in ("chat_rooms", "chat_messages", "chat_cards", "chat_reads", "assignment_batches"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app_actor_in_chat_room(target_room_id uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
          SELECT EXISTS (
            SELECT 1 FROM chat_rooms r JOIN team_memberships tm ON tm.team_id = r.team_id
             WHERE r.id = target_room_id AND tm.status = 'ACTIVE'
               AND tm.user_id = NULLIF(current_setting('app.actor_user_id', true), '')::uuid
               AND (r.kind = 'team' OR r.athlete_id = tm.user_id
                    OR tm.role IN ('coach', 'head_coach', 'owner'))
          )
        $$
        """
    )
    op.execute("GRANT EXECUTE ON FUNCTION app_actor_in_chat_room(uuid) TO runsense_runtime")
    op.execute(f"""CREATE POLICY chat_rooms_member_rw ON chat_rooms TO runsense_runtime
                   USING (app_actor_in_chat_room(id)) WITH CHECK (app_actor_has_team_membership(team_id))""")
    op.execute(f"""CREATE POLICY chat_messages_member_rw ON chat_messages TO runsense_runtime
                   USING (app_actor_in_chat_room(room_id)) WITH CHECK (app_actor_in_chat_room(room_id))""")
    op.execute(f"""CREATE POLICY chat_cards_owner_rw ON chat_cards TO runsense_runtime
                   USING (owner_id = {_ACTOR}) WITH CHECK (app_actor_in_chat_room(room_id))""")
    op.execute(f"""CREATE POLICY chat_reads_self_rw ON chat_reads TO runsense_runtime
                   USING (user_id = {_ACTOR}) WITH CHECK (user_id = {_ACTOR})""")
    op.execute("""CREATE POLICY assignment_batches_coach_rw ON assignment_batches TO runsense_runtime
                  USING (app_actor_is_active_team_coach(team_id)) WITH CHECK (app_actor_is_active_team_coach(team_id))""")


def downgrade() -> None:
    for policy, table in (("assignment_batches_coach_rw", "assignment_batches"), ("chat_reads_self_rw", "chat_reads"),
                          ("chat_cards_owner_rw", "chat_cards"), ("chat_messages_member_rw", "chat_messages"),
                          ("chat_rooms_member_rw", "chat_rooms")):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS app_actor_in_chat_room(uuid)")
    op.drop_column("assigned_workouts", "notes")
    op.drop_column("assigned_workouts", "tracked")
    op.drop_column("assigned_workouts", "batch_id")
    op.drop_table("assignment_batches")
    op.drop_table("chat_reads")
    op.drop_table("chat_cards")
    op.drop_index("ix_chat_messages_room_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("uq_chat_rooms_direct", table_name="chat_rooms")
    op.drop_index("uq_chat_rooms_team", table_name="chat_rooms")
    op.drop_table("chat_rooms")
