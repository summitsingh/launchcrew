"""Workspace isolation for demo and signed-in owners.

Additive deterministic design. A reserved 'demo' workspace owns all legacy
rows and seeded profiles. Authenticated workspaces are relational rows keyed
by the verified server actor, never by caller input. Agents become
(workspace_id, name) so the same profile name is usable across workspaces.
Runs, memory_items, campaigns, campaign_days, and audit gain workspace_id
with composite indexes. No workspace_id column keeps a persistent DEFAULT:
explicit backfill assigns legacy rows, then defaults are removed, so a
future omitted-owner write fails closed instead of silently landing in
shared demo. Child links that carry their own workspace (memory_items,
audit) or join two parents (campaign_days) use composite foreign keys to
runs and campaigns, so cross-workspace parent-child links fail at the DB
layer. Nullable run links use MATCH SIMPLE semantics: NULL passes, a set
link must match the same workspace. Single-parent ledgers without their
own workspace (sam_calls, run_steps, approvals, memory) keep existing
foreign keys and stay reachable only through scoped parents in
application SQL. Global SAM and model budgets stay global, zero-default,
and ungrantable from public routes.
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'workspaces',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('owner', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.execute("INSERT INTO workspaces(id, owner) VALUES ('demo', 'demo') ON CONFLICT DO NOTHING")
    op.execute('ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_agent_name_fkey')
    op.execute("ALTER TABLE agents ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'demo'")
    op.execute("UPDATE agents SET workspace_id='demo' WHERE workspace_id IS NULL OR workspace_id=''")
    op.execute('ALTER TABLE agents ALTER COLUMN workspace_id DROP DEFAULT')
    op.execute('ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_pkey')
    op.execute('ALTER TABLE agents ADD CONSTRAINT agents_pkey PRIMARY KEY (workspace_id, name)')
    op.execute('ALTER TABLE agents ADD CONSTRAINT agents_workspace_fkey '
               'FOREIGN KEY (workspace_id) REFERENCES workspaces(id)')
    op.execute("ALTER TABLE runs ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'demo'")
    op.execute("UPDATE runs SET workspace_id='demo' WHERE workspace_id IS NULL OR workspace_id=''")
    op.execute('ALTER TABLE runs ALTER COLUMN workspace_id DROP DEFAULT')
    op.execute('ALTER TABLE runs ADD CONSTRAINT runs_workspace_fkey '
               'FOREIGN KEY (workspace_id) REFERENCES workspaces(id)')
    op.execute('ALTER TABLE runs ADD CONSTRAINT runs_id_workspace_unique UNIQUE (id, workspace_id)')
    op.execute('ALTER TABLE runs ADD CONSTRAINT runs_agent_workspace_fkey '
               'FOREIGN KEY (workspace_id, agent_name) REFERENCES agents(workspace_id, name)')
    op.execute('CREATE INDEX IF NOT EXISTS runs_workspace_queue '
               'ON runs(workspace_id, state, created_at, id)')
    op.execute('CREATE INDEX IF NOT EXISTS runs_workspace_id ON runs(workspace_id, id)')
    op.execute("ALTER TABLE memory_items ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'demo'")
    op.execute('UPDATE memory_items SET workspace_id = COALESCE('
               '(SELECT workspace_id FROM runs WHERE runs.id = memory_items.source_run_id), '
               "'demo')")
    op.execute('ALTER TABLE memory_items ALTER COLUMN workspace_id DROP DEFAULT')
    op.execute('ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_source_run_id_fkey')
    op.execute('ALTER TABLE memory_items ADD CONSTRAINT memory_items_workspace_fkey '
               'FOREIGN KEY (workspace_id) REFERENCES workspaces(id)')
    op.execute('ALTER TABLE memory_items ADD CONSTRAINT memory_items_source_workspace_fkey '
               'FOREIGN KEY (source_run_id, workspace_id) REFERENCES runs(id, workspace_id)')
    op.execute('CREATE INDEX IF NOT EXISTS memory_items_workspace '
               'ON memory_items(workspace_id, created_at, id)')
    op.execute("ALTER TABLE campaigns ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'demo'")
    op.execute("UPDATE campaigns SET workspace_id='demo' WHERE workspace_id IS NULL OR workspace_id=''")
    op.execute('ALTER TABLE campaigns ALTER COLUMN workspace_id DROP DEFAULT')
    op.execute('ALTER TABLE campaigns ADD CONSTRAINT campaigns_id_workspace_unique UNIQUE (id, workspace_id)')
    op.execute('ALTER TABLE campaigns ADD CONSTRAINT campaigns_workspace_fkey '
               'FOREIGN KEY (workspace_id) REFERENCES workspaces(id)')
    op.execute('CREATE INDEX IF NOT EXISTS campaigns_workspace '
               'ON campaigns(workspace_id, created_at, id)')
    op.execute('ALTER TABLE campaign_days ADD COLUMN workspace_id TEXT')
    op.execute('UPDATE campaign_days SET workspace_id = campaigns.workspace_id '
               'FROM campaigns WHERE campaigns.id = campaign_days.campaign_id')
    op.execute('ALTER TABLE campaign_days ALTER COLUMN workspace_id SET NOT NULL')
    op.execute('ALTER TABLE campaign_days DROP CONSTRAINT IF EXISTS campaign_days_campaign_id_fkey')
    op.execute('ALTER TABLE campaign_days DROP CONSTRAINT IF EXISTS campaign_days_run_id_fkey')
    op.execute('ALTER TABLE campaign_days ADD CONSTRAINT campaign_days_workspace_fkey '
               'FOREIGN KEY (workspace_id) REFERENCES workspaces(id)')
    op.execute('ALTER TABLE campaign_days ADD CONSTRAINT campaign_days_campaign_workspace_fkey '
               'FOREIGN KEY (campaign_id, workspace_id) REFERENCES campaigns(id, workspace_id)')
    op.execute('ALTER TABLE campaign_days ADD CONSTRAINT campaign_days_run_workspace_fkey '
               'FOREIGN KEY (run_id, workspace_id) REFERENCES runs(id, workspace_id)')
    op.execute('CREATE INDEX IF NOT EXISTS campaign_days_workspace '
               'ON campaign_days(workspace_id, campaign_id, day)')
    op.execute("ALTER TABLE audit ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'demo'")
    op.execute('UPDATE audit SET workspace_id = COALESCE('
               '(SELECT workspace_id FROM runs WHERE runs.id = audit.run_id), '
               "'demo')")
    op.execute('ALTER TABLE audit ALTER COLUMN workspace_id DROP DEFAULT')
    op.execute('ALTER TABLE audit DROP CONSTRAINT IF EXISTS audit_run_id_fkey')
    op.execute('ALTER TABLE audit ADD CONSTRAINT audit_workspace_fkey '
               'FOREIGN KEY (workspace_id) REFERENCES workspaces(id)')
    op.execute('ALTER TABLE audit ADD CONSTRAINT audit_run_workspace_fkey '
               'FOREIGN KEY (run_id, workspace_id) REFERENCES runs(id, workspace_id)')
    op.execute('CREATE INDEX IF NOT EXISTS audit_workspace_run_time '
               'ON audit(workspace_id, run_id, created_at, id)')


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM agents GROUP BY name HAVING COUNT(DISTINCT workspace_id) > 1) THEN '
        "RAISE EXCEPTION 'Cannot downgrade: duplicate agent names across workspaces prevent restoration of global PRIMARY KEY (name). Rename or remove duplicates before downgrade.' USING ERRCODE = '23505'; "
        'END IF; END $$;'
    )
    op.execute('DROP INDEX IF EXISTS audit_workspace_run_time')
    op.execute('ALTER TABLE audit DROP CONSTRAINT IF EXISTS audit_run_workspace_fkey')
    op.execute('ALTER TABLE audit DROP CONSTRAINT IF EXISTS audit_workspace_fkey')
    op.execute('ALTER TABLE audit DROP COLUMN IF EXISTS workspace_id')
    op.execute('ALTER TABLE audit ADD CONSTRAINT audit_run_id_fkey FOREIGN KEY (run_id) REFERENCES runs(id)')
    op.execute('DROP INDEX IF EXISTS campaign_days_workspace')
    op.execute('ALTER TABLE campaign_days DROP CONSTRAINT IF EXISTS campaign_days_run_workspace_fkey')
    op.execute('ALTER TABLE campaign_days DROP CONSTRAINT IF EXISTS campaign_days_campaign_workspace_fkey')
    op.execute('ALTER TABLE campaign_days DROP CONSTRAINT IF EXISTS campaign_days_workspace_fkey')
    op.execute('ALTER TABLE campaign_days DROP COLUMN IF EXISTS workspace_id')
    op.execute('ALTER TABLE campaign_days ADD CONSTRAINT campaign_days_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(id)')
    op.execute('ALTER TABLE campaign_days ADD CONSTRAINT campaign_days_run_id_fkey FOREIGN KEY (run_id) REFERENCES runs(id)')
    op.execute('DROP INDEX IF EXISTS campaigns_workspace')
    op.execute('ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_workspace_fkey')
    op.execute('ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_id_workspace_unique')
    op.execute('ALTER TABLE campaigns DROP COLUMN IF EXISTS workspace_id')
    op.execute('DROP INDEX IF EXISTS memory_items_workspace')
    op.execute('ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_source_workspace_fkey')
    op.execute('ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_workspace_fkey')
    op.execute('ALTER TABLE memory_items DROP COLUMN IF EXISTS workspace_id')
    op.execute('ALTER TABLE memory_items ADD CONSTRAINT memory_items_source_run_id_fkey FOREIGN KEY (source_run_id) REFERENCES runs(id)')
    op.execute('DROP INDEX IF EXISTS runs_workspace_id')
    op.execute('DROP INDEX IF EXISTS runs_workspace_queue')
    op.execute('ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_agent_workspace_fkey')
    op.execute('ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_id_workspace_unique')
    op.execute('ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_workspace_fkey')
    op.execute('ALTER TABLE runs DROP COLUMN IF EXISTS workspace_id')
    op.execute('ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_workspace_fkey')
    op.execute('ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_pkey')
    op.execute('ALTER TABLE agents ADD CONSTRAINT agents_pkey PRIMARY KEY (name)')
    op.execute('ALTER TABLE agents DROP COLUMN IF EXISTS workspace_id')
    op.execute('ALTER TABLE runs ADD CONSTRAINT runs_agent_name_fkey '
               'FOREIGN KEY (agent_name) REFERENCES agents(name)')
    op.drop_table('workspaces')
