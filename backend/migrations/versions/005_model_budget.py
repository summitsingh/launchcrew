"""Global model budget plus durable call ledger.

Zero-default planning reservation in integer USD micros: one bounded
Standard call reserves a fixed 4 USD (4000000 micros). This is a local
planning reservation only, never an external provider hard cap. No grant
is issued here and no refill path exists; a private operator grant is
future separate work via the migration owner identity only.

The ledger has no FK to runs: sync runs and Campaign execute model work
before their run row commits, while async runs commit before a worker.
Never locking run rows avoids a lock order cycle.

Least privilege: migration-owned SECURITY DEFINER reserve and finalize
functions do all budget and ledger DML atomically with fixed amount and
model, static SQL, validated IDs and digest, and a pinned search_path
with pg_temp last. PUBLIC EXECUTE is revoked in the same transaction as
creation. No function accepts a caller-supplied debit amount and no
refill function exists. A row trigger blocks direct DML from any
non-owner non-superuser with SQLSTATE 42501, so broad table defaults
cannot restore runtime writes before a post-migration rebind. The exact
runtime role is discovered from existing table grants when present and
narrow table revokes plus explicit function grants are applied; with no
runtime role present the migration leaves tables without runtime grants
and functions owner-only, which is safe by default.
"""
import re

from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

_IDENT = re.compile(r'^[a-z_][a-z0-9_]{0,62}$')
_RESERVE_SIG = '(TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER)'
_FINALIZE_SIG = '(TEXT, TEXT, TEXT, INTEGER, INTEGER, INTEGER)'


def _quote_ident(name):
    if not _IDENT.match(name or ''):
        raise ValueError('invalid identifier')
    return '"' + name.replace('"', '""') + '"'


def upgrade():
    op.create_table(
        'model_budget',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('remaining_micros', sa.BigInteger, nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 'global'", name='model_budget_single_row'),
        sa.CheckConstraint('remaining_micros >= 0', name='model_budget_non_negative'),
    )
    op.execute("INSERT INTO model_budget(id, remaining_micros) VALUES ('global', 0)")
    op.create_table(
        'model_calls',
        sa.Column('id', sa.Text, primary_key=True),
        sa.Column('run_id', sa.Text, nullable=False),
        sa.Column('stage', sa.Text, nullable=False),
        sa.Column('attempt_id', sa.Text, nullable=False),
        sa.Column('request_digest', sa.Text, nullable=False),
        sa.Column('model', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('outcome', sa.Text, nullable=True),
        sa.Column('prompt_tokens', sa.Integer, nullable=True),
        sa.Column('completion_tokens', sa.Integer, nullable=True),
        sa.Column('total_tokens', sa.Integer, nullable=True),
        sa.Column('reservation_micros', sa.BigInteger, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('admitted','succeeded','failed_terminal','ambiguous_terminal')",
            name='model_call_status'),
        sa.CheckConstraint('reservation_micros = 4000000', name='model_call_fixed_reservation'),
        sa.CheckConstraint(
            'prompt_tokens IS NULL OR prompt_tokens >= 0',
            name='model_call_prompt_tokens_non_negative'),
        sa.CheckConstraint(
            'completion_tokens IS NULL OR completion_tokens >= 0',
            name='model_call_completion_tokens_non_negative'),
        sa.CheckConstraint(
            'total_tokens IS NULL OR total_tokens >= 0',
            name='model_call_total_tokens_non_negative'),
        sa.UniqueConstraint('run_id', 'stage', 'attempt_id', name='model_call_identity'),
    )
    op.create_index('model_calls_status', 'model_calls', ['status'])
    bind = op.get_bind()
    schema = bind.execute(sa.text('SELECT current_schema()')).scalar()
    if not _IDENT.match(schema or ''):
        raise ValueError('invalid migration schema')
    qi_schema = _quote_ident(schema)
    op.execute(sa.text(
        'CREATE OR REPLACE FUNCTION model_no_direct() RETURNS TRIGGER '
        'LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $func$ '
        'DECLARE v_owner TEXT; v_super BOOLEAN; BEGIN '
        'SELECT pg_get_userbyid(c.relowner) INTO v_owner FROM pg_class c '
        'JOIN pg_namespace n ON n.oid = c.relnamespace '
        'WHERE n.nspname = TG_TABLE_SCHEMA AND c.relname = TG_TABLE_NAME; '
        'IF NOT FOUND THEN '
        'RAISE EXCEPTION \'denied\' USING ERRCODE = \'42501\'; END IF; '
        'IF current_user = v_owner THEN '
        'IF TG_OP = \'DELETE\' THEN RETURN OLD; ELSE RETURN NEW; END IF; END IF; '
        'SELECT rolsuper INTO v_super FROM pg_roles WHERE rolname = current_user; '
        'IF FOUND AND v_super THEN '
        'IF TG_OP = \'DELETE\' THEN RETURN OLD; ELSE RETURN NEW; END IF; END IF; '
        'RAISE EXCEPTION \'denied\' USING ERRCODE = \'42501\'; END; $func$'
    ))
    op.execute(sa.text(
        'CREATE OR REPLACE FUNCTION model_reserve_call('
        'p_run_id TEXT, p_stage TEXT, p_attempt_id TEXT, p_request_digest TEXT, '
        'p_max_tokens INTEGER, p_n INTEGER, p_bytes_len INTEGER) '
        'RETURNS TABLE(id TEXT, run_id TEXT, stage TEXT, attempt_id TEXT, '
        'request_digest TEXT, model TEXT, status TEXT, outcome TEXT, '
        'prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, '
        'reservation_micros BIGINT, is_owner BOOLEAN) '
        'LANGUAGE plpgsql SECURITY DEFINER '
        'SET search_path = ' + qi_schema + ', pg_temp AS $func$ '
        'DECLARE v_existing model_calls%ROWTYPE; v_budget BIGINT; '
        'v_call_id TEXT; v_digest TEXT; BEGIN '
        'IF p_run_id IS NULL OR length(p_run_id) < 1 OR length(p_run_id) > 128 '
        'OR btrim(p_run_id) = \'\' THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_stage IS NULL OR length(p_stage) < 1 OR length(p_stage) > 128 '
        'OR btrim(p_stage) = \'\' THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_attempt_id IS NULL OR length(p_attempt_id) < 1 '
        'OR length(p_attempt_id) > 128 OR btrim(p_attempt_id) = \'\' THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_request_digest IS NULL OR length(p_request_digest) != 64 '
        'OR p_request_digest !~ \'^[0-9a-fA-F]{64}$\' THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'v_digest := lower(p_request_digest); '
        'IF p_max_tokens IS NULL OR p_max_tokens != 2048 THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_n IS NULL OR p_n != 1 THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_bytes_len IS NULL OR p_bytes_len < 0 OR p_bytes_len > 32768 THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'SELECT * INTO v_existing FROM model_calls '
        'WHERE model_calls.run_id = p_run_id AND model_calls.stage = p_stage '
        'AND model_calls.attempt_id = p_attempt_id FOR UPDATE; '
        'IF FOUND THEN '
        'IF lower(v_existing.request_digest) != v_digest THEN '
        'RAISE EXCEPTION \'admission conflict\' USING ERRCODE = \'23505\'; END IF; '
        'id := v_existing.id; run_id := v_existing.run_id; stage := v_existing.stage; '
        'attempt_id := v_existing.attempt_id; request_digest := v_existing.request_digest; '
        'model := v_existing.model; status := v_existing.status; outcome := v_existing.outcome; '
        'prompt_tokens := v_existing.prompt_tokens; '
        'completion_tokens := v_existing.completion_tokens; '
        'total_tokens := v_existing.total_tokens; '
        'reservation_micros := v_existing.reservation_micros; is_owner := FALSE; '
        'RETURN NEXT; RETURN; END IF; '
        'SELECT model_budget.remaining_micros INTO v_budget FROM model_budget '
        'WHERE model_budget.id = \'global\' FOR UPDATE; '
        'IF NOT FOUND THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'SELECT * INTO v_existing FROM model_calls '
        'WHERE model_calls.run_id = p_run_id AND model_calls.stage = p_stage '
        'AND model_calls.attempt_id = p_attempt_id; '
        'IF FOUND THEN '
        'IF lower(v_existing.request_digest) != v_digest THEN '
        'RAISE EXCEPTION \'admission conflict\' USING ERRCODE = \'23505\'; END IF; '
        'id := v_existing.id; run_id := v_existing.run_id; stage := v_existing.stage; '
        'attempt_id := v_existing.attempt_id; request_digest := v_existing.request_digest; '
        'model := v_existing.model; status := v_existing.status; outcome := v_existing.outcome; '
        'prompt_tokens := v_existing.prompt_tokens; '
        'completion_tokens := v_existing.completion_tokens; '
        'total_tokens := v_existing.total_tokens; '
        'reservation_micros := v_existing.reservation_micros; is_owner := FALSE; '
        'RETURN NEXT; RETURN; END IF; '
        'IF v_budget < 4000000 THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'UPDATE model_budget SET remaining_micros = model_budget.remaining_micros - 4000000, '
        'updated_at = now() WHERE model_budget.id = \'global\' '
        'AND model_budget.remaining_micros >= 4000000; '
        'IF NOT FOUND THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'v_call_id := \'mc_\' || replace(gen_random_uuid()::text, \'-\', \'\'); '
        'INSERT INTO model_calls(id, run_id, stage, attempt_id, request_digest, model, '
        'status, reservation_micros) VALUES (v_call_id, p_run_id, p_stage, p_attempt_id, '
        'v_digest, \'muse-spark-1.3\', \'admitted\', 4000000); '
        'id := v_call_id; run_id := p_run_id; stage := p_stage; '
        'attempt_id := p_attempt_id; request_digest := v_digest; '
        'model := \'muse-spark-1.3\'; status := \'admitted\'; outcome := NULL; '
        'prompt_tokens := NULL; completion_tokens := NULL; total_tokens := NULL; '
        'reservation_micros := 4000000; is_owner := TRUE; '
        'RETURN NEXT; RETURN; END; $func$'
    ))
    op.execute(sa.text(
        'CREATE OR REPLACE FUNCTION model_finalize_call('
        'p_call_id TEXT, p_status TEXT, p_outcome TEXT, '
        'p_prompt_tokens INTEGER, p_completion_tokens INTEGER, p_total_tokens INTEGER) '
        'RETURNS TABLE(id TEXT, run_id TEXT, stage TEXT, attempt_id TEXT, '
        'request_digest TEXT, model TEXT, status TEXT, outcome TEXT, '
        'prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, '
        'reservation_micros BIGINT, is_owner BOOLEAN) '
        'LANGUAGE plpgsql SECURITY DEFINER '
        'SET search_path = ' + qi_schema + ', pg_temp AS $func$ '
        'DECLARE v_row model_calls%ROWTYPE; v_outcome TEXT; BEGIN '
        'IF p_call_id IS NULL OR length(p_call_id) < 1 OR length(p_call_id) > 128 '
        'OR btrim(p_call_id) = \'\' THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_status IS NULL OR p_status NOT IN '
        '(\'succeeded\', \'failed_terminal\', \'ambiguous_terminal\') THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_outcome IS NULL OR p_outcome = \'\' THEN v_outcome := NULL; '
        'ELSIF p_outcome !~ \'^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$\' THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; '
        'ELSE v_outcome := p_outcome; END IF; '
        'IF p_prompt_tokens IS NOT NULL '
        'AND (p_prompt_tokens < 0 OR p_prompt_tokens > 10000000) THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_completion_tokens IS NOT NULL '
        'AND (p_completion_tokens < 0 OR p_completion_tokens > 10000000) THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF p_total_tokens IS NOT NULL '
        'AND (p_total_tokens < 0 OR p_total_tokens > 10000000) THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'SELECT * INTO v_row FROM model_calls '
        'WHERE model_calls.id = p_call_id FOR UPDATE; '
        'IF NOT FOUND THEN '
        'RAISE EXCEPTION \'admission denied\' USING ERRCODE = \'P0001\'; END IF; '
        'IF v_row.status != \'admitted\' THEN '
        'id := v_row.id; run_id := v_row.run_id; stage := v_row.stage; '
        'attempt_id := v_row.attempt_id; request_digest := v_row.request_digest; '
        'model := v_row.model; status := v_row.status; outcome := v_row.outcome; '
        'prompt_tokens := v_row.prompt_tokens; '
        'completion_tokens := v_row.completion_tokens; '
        'total_tokens := v_row.total_tokens; '
        'reservation_micros := v_row.reservation_micros; is_owner := FALSE; '
        'RETURN NEXT; RETURN; END IF; '
        'UPDATE model_calls SET status = p_status, outcome = v_outcome, '
        'prompt_tokens = p_prompt_tokens, completion_tokens = p_completion_tokens, '
        'total_tokens = p_total_tokens, updated_at = now() '
        'WHERE model_calls.id = p_call_id AND model_calls.status = \'admitted\'; '
        'SELECT * INTO v_row FROM model_calls WHERE model_calls.id = p_call_id; '
        'id := v_row.id; run_id := v_row.run_id; stage := v_row.stage; '
        'attempt_id := v_row.attempt_id; request_digest := v_row.request_digest; '
        'model := v_row.model; status := v_row.status; outcome := v_row.outcome; '
        'prompt_tokens := v_row.prompt_tokens; '
        'completion_tokens := v_row.completion_tokens; '
        'total_tokens := v_row.total_tokens; '
        'reservation_micros := v_row.reservation_micros; is_owner := FALSE; '
        'RETURN NEXT; RETURN; END; $func$'
    ))
    op.execute('CREATE TRIGGER model_budget_no_direct BEFORE INSERT OR UPDATE OR DELETE '
               'ON model_budget FOR EACH ROW EXECUTE FUNCTION model_no_direct()')
    op.execute('CREATE TRIGGER model_calls_no_direct BEFORE INSERT OR UPDATE OR DELETE '
               'ON model_calls FOR EACH ROW EXECUTE FUNCTION model_no_direct()')
    op.execute('REVOKE EXECUTE ON FUNCTION model_no_direct() FROM PUBLIC')
    op.execute('REVOKE EXECUTE ON FUNCTION model_reserve_call' + _RESERVE_SIG + ' FROM PUBLIC')
    op.execute('REVOKE EXECUTE ON FUNCTION model_finalize_call' + _FINALIZE_SIG + ' FROM PUBLIC')
    op.execute('REVOKE ALL ON TABLE model_budget, model_calls FROM PUBLIC')
    grantees = bind.execute(
        sa.text("SELECT DISTINCT grantee FROM information_schema.role_table_grants "
                "WHERE table_schema = :schema AND privilege_type = 'INSERT' "
                "AND grantee NOT IN (current_user, 'PUBLIC')"),
        {'schema': schema}).scalars().all()
    runtime_user = None
    if len(grantees) == 1:
        candidate = grantees[0]
        if not _IDENT.match(candidate or ''):
            raise ValueError('invalid runtime role')
        runtime_user = candidate
    elif len(grantees) > 1:
        raise ValueError('ambiguous runtime role')
    if runtime_user is not None:
        qi_runtime = _quote_ident(runtime_user)
        op.execute('REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE '
                   + qi_schema + '."model_budget", ' + qi_schema + '."model_calls" '
                   'FROM ' + qi_runtime)
        op.execute('GRANT EXECUTE ON FUNCTION ' + qi_schema + '."model_reserve_call"'
                   + _RESERVE_SIG + ' TO ' + qi_runtime)
        op.execute('GRANT EXECUTE ON FUNCTION ' + qi_schema + '."model_finalize_call"'
                   + _FINALIZE_SIG + ' TO ' + qi_runtime)
        op.execute('REVOKE EXECUTE ON FUNCTION ' + qi_schema + '."model_no_direct"() '
                   'FROM ' + qi_runtime)
        owner = bind.execute(
            sa.text("SELECT pg_get_userbyid(p.proowner) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = :schema AND p.proname = 'model_reserve_call'"),
            {'schema': schema}).scalar()
        if owner is None:
            raise ValueError('reserve function missing')


def downgrade():
    op.execute('DROP TRIGGER IF EXISTS model_calls_no_direct ON model_calls')
    op.execute('DROP TRIGGER IF EXISTS model_budget_no_direct ON model_budget')
    op.execute('DROP FUNCTION IF EXISTS model_finalize_call' + _FINALIZE_SIG)
    op.execute('DROP FUNCTION IF EXISTS model_reserve_call' + _RESERVE_SIG)
    op.execute('DROP FUNCTION IF EXISTS model_no_direct()')
    op.drop_index('model_calls_status', table_name='model_calls')
    op.drop_table('model_calls')
    op.drop_table('model_budget')
