"""Allow voice_profile memory kind.

Migration 002 created memory_items with a CHECK limited to four kinds.
Slice 3 added voice_profile at the API and receipt layers but the
database CHECK still rejects it, so actual Postgres inserts fail with
a generic IntegrityError surfaced as HTTP 409. This revision widens
the CHECK to exactly the four preexisting kinds plus voice_profile,
with no other schema effects.

Downgrade refuses when any voice_profile row exists, so no committed
voice data is silently orphaned by restoring the narrower CHECK. With
no voice rows, downgrade restores the exact 002 CHECK.
"""
from alembic import op

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None

_OLD_KINDS = "kind IN ('brand_fact','profile','approval_example','blocked_rule')"
_NEW_KINDS = ("kind IN ('brand_fact','profile','approval_example','blocked_rule',"
              "'voice_profile')")


def upgrade():
    op.execute('ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_item_kind')
    op.execute('ALTER TABLE memory_items ADD CONSTRAINT memory_item_kind CHECK (%s)' % _NEW_KINDS)


def downgrade():
    op.execute(
        'DO $$ BEGIN '
        'IF EXISTS (SELECT 1 FROM memory_items WHERE kind = \'voice_profile\') THEN '
        'RAISE EXCEPTION \'Cannot downgrade: voice_profile rows exist; delete or migrate them before restoring the narrower memory_item_kind CHECK.\' USING ERRCODE = \'P0001\'; '
        'END IF; END $$;'
    )
    op.execute('ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_item_kind')
    op.execute('ALTER TABLE memory_items ADD CONSTRAINT memory_item_kind CHECK (%s)' % _OLD_KINDS)
