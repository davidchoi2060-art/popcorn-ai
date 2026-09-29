"""Preserve fixed configurations; stage customer changes before atomic application."""
from alembic import op

revision = '0119'
down_revision = '0118'
branch_labels = None
depends_on = None

TABLES = ('pc_catalog_submissions', 'pc_quote_confirmations',
          'pc_quote_events', 'pc_performance_evidence', 'pc_change_validations',
          'pc_change_items', 'pc_change_revisions', 'pc_change_sets',
          'pc_quote_versions', 'pc_customer_quotes')


def upgrade():
    op.execute('''CREATE TABLE pc_customer_quotes (
      quote_id UUID PRIMARY KEY,
      session_id BIGINT NOT NULL REFERENCES consult_sessions(session_id),
      configuration_id TEXT NOT NULL REFERENCES pc_configurations(configuration_id),
      configuration_revision INTEGER NOT NULL CHECK(configuration_revision>0),
      origin_snapshot JSONB NOT NULL CHECK(jsonb_typeof(origin_snapshot)='object'),
      current_version INTEGER CHECK(current_version>0),
      status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    op.execute('CREATE INDEX pc_customer_quotes_session_idx ON pc_customer_quotes(session_id)')
    op.execute('''CREATE TABLE pc_quote_versions (
      quote_id UUID NOT NULL REFERENCES pc_customer_quotes(quote_id),
      version INTEGER NOT NULL CHECK(version>0),
      bom JSONB NOT NULL CHECK(jsonb_typeof(bom)='array' AND jsonb_array_length(bom)>0),
      bom_fingerprint VARCHAR(64) NOT NULL CHECK(length(bom_fingerprint)=64),
      conditions JSONB NOT NULL CHECK(jsonb_typeof(conditions)='object'),
      total_amount BIGINT NOT NULL CHECK(total_amount>=0),
      assembly_fee_included BOOLEAN NOT NULL,
      price_basis JSONB NOT NULL CHECK(jsonb_typeof(price_basis)='object' AND price_basis<>'{}'::jsonb),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(quote_id,version))''')
    op.execute('''ALTER TABLE pc_customer_quotes ADD CONSTRAINT pc_customer_quotes_version_fk
      FOREIGN KEY(quote_id,current_version) REFERENCES pc_quote_versions(quote_id,version)''')
    op.execute('''CREATE TABLE pc_change_sets (
      change_set_id UUID PRIMARY KEY,
      quote_id UUID NOT NULL REFERENCES pc_customer_quotes(quote_id),
      base_version INTEGER NOT NULL,
      current_revision INTEGER CHECK(current_revision>0),
      status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','applied','cancelled')),
      applied_version INTEGER, validation_id UUID,
      idempotency_key UUID NOT NULL UNIQUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(change_set_id,quote_id),
      FOREIGN KEY(quote_id,base_version) REFERENCES pc_quote_versions(quote_id,version),
      FOREIGN KEY(quote_id,applied_version) REFERENCES pc_quote_versions(quote_id,version),
      CHECK((status='applied' AND applied_version IS NOT NULL AND applied_version=base_version+1 AND validation_id IS NOT NULL)
         OR (status<>'applied' AND applied_version IS NULL AND validation_id IS NULL)))''')
    op.execute("CREATE UNIQUE INDEX pc_change_sets_active_idx ON pc_change_sets(quote_id) WHERE status='draft'")
    op.execute("CREATE UNIQUE INDEX pc_change_sets_applied_idx ON pc_change_sets(quote_id,base_version) WHERE status='applied'")
    op.execute('''CREATE TABLE pc_change_revisions (
      change_set_id UUID NOT NULL REFERENCES pc_change_sets(change_set_id),
      revision INTEGER NOT NULL CHECK(revision>0),
      request_summary TEXT NOT NULL,
      bom JSONB NOT NULL CHECK(jsonb_typeof(bom)='array' AND jsonb_array_length(bom)>0),
      bom_fingerprint VARCHAR(64) NOT NULL CHECK(length(bom_fingerprint)=64),
      budget_won BIGINT CHECK(budget_won>=0),
      price_status TEXT NOT NULL CHECK(price_status IN ('pending','estimated','confirmed')),
      base_total BIGINT NOT NULL CHECK(base_total>=0),
      delta_amount BIGINT, total_amount BIGINT CHECK(total_amount>=0),
      price_basis JSONB NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(price_basis)='object'),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(change_set_id,revision),
      CHECK((delta_amount IS NULL AND total_amount IS NULL) OR
            (delta_amount IS NOT NULL AND total_amount IS NOT NULL AND total_amount=base_total+delta_amount)),
      CHECK(price_status<>'confirmed' OR (total_amount IS NOT NULL AND price_basis<>'{}'::jsonb)))''')
    op.execute('''ALTER TABLE pc_change_sets ADD CONSTRAINT pc_change_sets_revision_fk
      FOREIGN KEY(change_set_id,current_revision) REFERENCES pc_change_revisions(change_set_id,revision)''')
    op.execute('''CREATE TABLE pc_change_items (
      change_set_id UUID NOT NULL, revision INTEGER NOT NULL, line_key TEXT NOT NULL,
      slot TEXT NOT NULL, operation TEXT NOT NULL CHECK(operation IN ('replace','add','remove')),
      before_parts JSONB NOT NULL CHECK(jsonb_typeof(before_parts)='array'),
      after_parts JSONB NOT NULL CHECK(jsonb_typeof(after_parts)='array'),
      reason TEXT NOT NULL,
      PRIMARY KEY(change_set_id,revision,line_key),
      FOREIGN KEY(change_set_id,revision) REFERENCES pc_change_revisions(change_set_id,revision),
      CHECK((operation='replace' AND jsonb_array_length(before_parts)>0 AND jsonb_array_length(after_parts)>0)
         OR (operation='add' AND jsonb_array_length(before_parts)=0 AND jsonb_array_length(after_parts)>0)
         OR (operation='remove' AND jsonb_array_length(before_parts)>0 AND jsonb_array_length(after_parts)=0)))''')
    op.execute('''CREATE TABLE pc_change_validations (
      validation_id UUID PRIMARY KEY, change_set_id UUID NOT NULL, revision INTEGER NOT NULL,
      bom_fingerprint VARCHAR(64) NOT NULL CHECK(length(bom_fingerprint)=64),
      compatibility TEXT NOT NULL CHECK(compatibility IN ('pass','fail','unknown')),
      sale_status TEXT NOT NULL CHECK(sale_status IN ('pass','fail','unknown')),
      pricing TEXT NOT NULL CHECK(pricing IN ('pass','fail','unknown')),
      intent_match TEXT NOT NULL CHECK(intent_match IN ('pass','fail','unknown')),
      rule_version TEXT NOT NULL, inputs_hash VARCHAR(64) NOT NULL CHECK(length(inputs_hash)=64),
      findings JSONB NOT NULL CHECK(jsonb_typeof(findings)='object'),
      checked_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
      CHECK(expires_at>checked_at), UNIQUE(validation_id,change_set_id,revision),
      FOREIGN KEY(change_set_id,revision) REFERENCES pc_change_revisions(change_set_id,revision))''')
    op.execute('''ALTER TABLE pc_change_sets ADD CONSTRAINT pc_change_sets_validation_fk
      FOREIGN KEY(validation_id,change_set_id,current_revision)
      REFERENCES pc_change_validations(validation_id,change_set_id,revision)''')
    op.execute('''CREATE TABLE pc_performance_evidence (
      evidence_id UUID PRIMARY KEY,
      evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('measured','published','estimate')),
      workload TEXT NOT NULL, workload_version TEXT NOT NULL,
      environment JSONB NOT NULL CHECK(jsonb_typeof(environment)='object' AND environment<>'{}'::jsonb),
      method TEXT NOT NULL, metrics JSONB NOT NULL CHECK(jsonb_typeof(metrics)='array' AND jsonb_array_length(metrics)>0),
      source_ref TEXT NOT NULL CHECK(length(source_ref)>0), measured_at TIMESTAMPTZ,
      collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      reviewed_by TEXT, reviewed_at TIMESTAMPTZ,
      supersedes UUID REFERENCES pc_performance_evidence(evidence_id),
      CHECK((reviewed_by IS NULL)=(reviewed_at IS NULL)),
      CHECK(evidence_kind<>'measured' OR measured_at IS NOT NULL))''')
    op.execute('''CREATE TABLE pc_quote_events (
      event_id UUID PRIMARY KEY, quote_id UUID NOT NULL REFERENCES pc_customer_quotes(quote_id),
      change_set_id UUID,
      actor_kind TEXT NOT NULL CHECK(actor_kind IN ('customer','admin','system')),
      actor_ref TEXT NOT NULL, action TEXT NOT NULL,
      payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      FOREIGN KEY(change_set_id,quote_id) REFERENCES pc_change_sets(change_set_id,quote_id))''')
    op.execute('CREATE INDEX pc_quote_events_quote_idx ON pc_quote_events(quote_id,created_at)')
    op.execute('''CREATE TABLE pc_quote_confirmations (
      confirmation_id UUID PRIMARY KEY, quote_id UUID NOT NULL, version INTEGER NOT NULL,
      confirmed_by TEXT NOT NULL, confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(quote_id,version),
      FOREIGN KEY(quote_id,version) REFERENCES pc_quote_versions(quote_id,version))''')
    op.execute('''CREATE TABLE pc_catalog_submissions (
      confirmation_id UUID PRIMARY KEY REFERENCES pc_quote_confirmations(confirmation_id),
      bom_fingerprint VARCHAR(64) NOT NULL CHECK(length(bom_fingerprint)=64),
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','linked','review_required')),
      configuration_id TEXT REFERENCES pc_configurations(configuration_id),
      note TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK((status='linked' AND configuration_id IS NOT NULL) OR status<>'linked'))''')
    op.execute('CREATE INDEX pc_catalog_submissions_pending_idx ON pc_catalog_submissions(status,created_at)')
    op.execute('''CREATE FUNCTION pc_quote_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Quote history is append-only: %', TG_TABLE_NAME; END $$''')
    for table in ('pc_quote_versions','pc_change_revisions','pc_change_items',
                  'pc_change_validations','pc_performance_evidence','pc_quote_events','pc_quote_confirmations'):
        op.execute(f'''CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
          FOR EACH ROW EXECUTE FUNCTION pc_quote_immutable()''')
    op.execute('''CREATE FUNCTION pc_change_apply_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE q pc_customer_quotes%ROWTYPE; r pc_change_revisions%ROWTYPE;
              v pc_change_validations%ROWTYPE; applied pc_quote_versions%ROWTYPE;
              base pc_quote_versions%ROWTYPE;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Cancel change sets instead of deleting'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.status<>'draft' THEN RAISE EXCEPTION 'New changes must start as draft'; END IF;
          RETURN NEW;
        END IF;
        IF OLD.status<>'draft' THEN RAISE EXCEPTION 'Terminal changes are immutable'; END IF;
        IF NEW.quote_id IS DISTINCT FROM OLD.quote_id OR NEW.base_version<>OLD.base_version
           OR NEW.change_set_id<>OLD.change_set_id OR NEW.idempotency_key<>OLD.idempotency_key THEN
          RAISE EXCEPTION 'Change origin is immutable';
        END IF;
        IF NEW.current_revision IS NULL OR (OLD.current_revision IS NOT NULL AND NEW.current_revision<OLD.current_revision) THEN
          RAISE EXCEPTION 'Change revision cannot move backwards';
        END IF;
        IF NEW.status='applied' THEN
          SELECT * INTO q FROM pc_customer_quotes WHERE quote_id=NEW.quote_id FOR UPDATE;
          SELECT * INTO r FROM pc_change_revisions WHERE change_set_id=NEW.change_set_id AND revision=NEW.current_revision;
          SELECT * INTO v FROM pc_change_validations WHERE validation_id=NEW.validation_id;
          SELECT * INTO base FROM pc_quote_versions WHERE quote_id=NEW.quote_id AND version=NEW.base_version;
          SELECT * INTO applied FROM pc_quote_versions WHERE quote_id=NEW.quote_id AND version=NEW.applied_version;
          IF q.status<>'active' OR q.current_version IS DISTINCT FROM NEW.base_version
             OR r.revision IS NULL OR v.validation_id IS NULL OR applied.version IS NULL
             OR v.change_set_id<>NEW.change_set_id OR v.revision<>NEW.current_revision
             OR v.bom_fingerprint<>r.bom_fingerprint OR v.expires_at<=clock_timestamp()
             OR v.compatibility<>'pass' OR v.sale_status<>'pass' OR v.pricing<>'pass' OR v.intent_match<>'pass'
             OR r.price_status<>'confirmed' OR r.base_total<>base.total_amount
             OR applied.total_amount IS DISTINCT FROM r.total_amount
             OR applied.bom IS DISTINCT FROM r.bom OR applied.bom_fingerprint<>r.bom_fingerprint
             OR applied.conditions IS DISTINCT FROM base.conditions
             OR applied.assembly_fee_included IS DISTINCT FROM base.assembly_fee_included
             OR applied.price_basis IS DISTINCT FROM r.price_basis THEN
            RAISE EXCEPTION 'Change is stale, unverified, or differs from approved preview';
          END IF;
          UPDATE pc_customer_quotes SET current_version=NEW.applied_version,updated_at=now() WHERE quote_id=NEW.quote_id;
        END IF;
        NEW.updated_at=now(); RETURN NEW;
      END $$''')
    op.execute('''CREATE TRIGGER pc_change_sets_guard BEFORE INSERT OR UPDATE OR DELETE ON pc_change_sets
      FOR EACH ROW EXECUTE FUNCTION pc_change_apply_guard()''')
    op.execute('''CREATE FUNCTION pc_change_content_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE s pc_change_sets%ROWTYPE;
      BEGIN
        SELECT * INTO s FROM pc_change_sets WHERE change_set_id=NEW.change_set_id FOR UPDATE;
        IF s.status<>'draft' OR NEW.revision<>coalesce(s.current_revision,0)+1 THEN
          RAISE EXCEPTION 'Write only the next draft revision before publishing its pointer';
        END IF;
        RETURN NEW;
      END $$''')
    for table in ('pc_change_revisions','pc_change_items'):
        op.execute(f'''CREATE TRIGGER {table}_insert_guard BEFORE INSERT ON {table}
          FOR EACH ROW EXECUTE FUNCTION pc_change_content_guard()''')
    op.execute('''CREATE FUNCTION pc_quote_confirm_catalog() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE q pc_customer_quotes%ROWTYPE; fingerprint TEXT;
      BEGIN
        SELECT * INTO q FROM pc_customer_quotes WHERE quote_id=NEW.quote_id FOR UPDATE;
        IF q.status<>'active' OR q.current_version IS DISTINCT FROM NEW.version THEN
          RAISE EXCEPTION 'Confirm only the current active quote version';
        END IF;
        SELECT bom_fingerprint INTO fingerprint FROM pc_quote_versions WHERE quote_id=NEW.quote_id AND version=NEW.version;
        INSERT INTO pc_catalog_submissions(confirmation_id,bom_fingerprint) VALUES(NEW.confirmation_id,fingerprint);
        RETURN NEW;
      END $$''')
    op.execute('''CREATE TRIGGER pc_quote_confirmations_catalog AFTER INSERT ON pc_quote_confirmations
      FOR EACH ROW EXECUTE FUNCTION pc_quote_confirm_catalog()''')
    op.execute('''CREATE FUNCTION pc_catalog_link_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE fingerprint TEXT;
      BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Keep catalog registration provenance'; END IF;
        IF NEW.confirmation_id<>OLD.confirmation_id OR NEW.bom_fingerprint<>OLD.bom_fingerprint THEN
          RAISE EXCEPTION 'Catalog submission origin is immutable';
        END IF;
        IF NEW.status='linked' THEN
          SELECT bom_fingerprint INTO fingerprint FROM pc_configurations WHERE configuration_id=NEW.configuration_id;
          IF fingerprint IS DISTINCT FROM NEW.bom_fingerprint THEN
            RAISE EXCEPTION 'Catalog configuration must match confirmed BOM';
          END IF;
        END IF;
        NEW.updated_at=now(); RETURN NEW;
      END $$''')
    op.execute('''CREATE TRIGGER pc_catalog_submissions_guard BEFORE UPDATE OR DELETE ON pc_catalog_submissions
      FOR EACH ROW EXECUTE FUNCTION pc_catalog_link_guard()''')


def downgrade():
    for table in TABLES:
        op.execute(f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM {table}) THEN RAISE EXCEPTION 'Archive populated quote data before downgrade'; END IF; END $$")
    op.execute('ALTER TABLE pc_customer_quotes DROP CONSTRAINT pc_customer_quotes_version_fk')
    op.execute('ALTER TABLE pc_change_sets DROP CONSTRAINT pc_change_sets_revision_fk')
    op.execute('ALTER TABLE pc_change_sets DROP CONSTRAINT pc_change_sets_validation_fk')
    for table in TABLES:
        op.execute(f'DROP TABLE {table}')
    op.execute('DROP FUNCTION pc_change_apply_guard()')
    op.execute('DROP FUNCTION pc_change_content_guard()')
    op.execute('DROP FUNCTION pc_quote_confirm_catalog()')
    op.execute('DROP FUNCTION pc_catalog_link_guard()')
    op.execute('DROP FUNCTION pc_quote_immutable()')
