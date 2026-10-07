"""SOURCE only. Support records; no application/backfill/business execution."""
import re

from alembic import op
from sqlalchemy import text

revision = '0128'
down_revision = '0127'
branch_labels = None
depends_on = None

UPGRADE_SQL = r'''
CREATE TABLE __S__.commerce_support_cases (
  case_id UUID PRIMARY KEY,
  order_id BIGINT NOT NULL REFERENCES __S__.commerce_order_details(order_id),
  owner_scope VARCHAR(64) NOT NULL CHECK(owner_scope ~ '^[0-9a-f]{64}$'),
  origin TEXT NOT NULL CHECK(origin IN ('customer','external_record')),
  state TEXT NOT NULL CHECK(state IN ('open','closed')),
  admin_revision BIGINT NOT NULL CHECK(admin_revision>0),
  public_revision BIGINT,
  created_at BIGINT NOT NULL CHECK(created_at>=0),
  updated_at BIGINT NOT NULL CHECK(updated_at>=created_at),
  public_updated_at BIGINT,
  write_txid BIGINT NOT NULL CHECK(write_txid>0),
  UNIQUE(order_id,case_id),
  CHECK((origin='customer' AND public_revision IS NOT NULL AND public_revision>0
    AND public_revision<=admin_revision AND public_updated_at IS NOT NULL
    AND public_updated_at>=created_at AND public_updated_at<=updated_at)
    OR (origin='external_record' AND public_revision IS NULL AND public_updated_at IS NULL))
);
CREATE INDEX commerce_support_customer_cases ON __S__.commerce_support_cases(order_id,case_id)
  WHERE origin='customer';
CREATE TABLE __S__.commerce_support_events (
  operation_id UUID PRIMARY KEY,
  event_id UUID NOT NULL UNIQUE,
  order_id BIGINT NOT NULL,
  case_id UUID NOT NULL,
  owner_scope VARCHAR(64) NOT NULL CHECK(owner_scope ~ '^[0-9a-f]{64}$'),
  actor JSONB NOT NULL CHECK(jsonb_typeof(actor)='object'),
  customer_user_id BIGINT REFERENCES __S__.users(user_id),
  operator_id BIGINT REFERENCES __S__.admin_operators(operator_id),
  action TEXT NOT NULL CHECK(action IN ('create_inquiry','append_customer_message',
    'reopen','record_external_contact','record_reply','publish_customer_reply','internal_note','close')),
  visible BOOLEAN NOT NULL,
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 4000 AND length(btrim(body))>0
    AND octet_length(body)<=12000 AND position('<' IN body)=0 AND position('>' IN body)=0),
  reply_event_id UUID,
  request JSONB NOT NULL CHECK(jsonb_typeof(request)='object'),
  request_hash VARCHAR(64) NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
  result JSONB NOT NULL CHECK(jsonb_typeof(result)='object'),
  result_hash VARCHAR(64) NOT NULL CHECK(result_hash ~ '^[0-9a-f]{64}$'),
  admin_revision BIGINT NOT NULL CHECK(admin_revision>0),
  public_revision BIGINT CHECK(public_revision>0 AND public_revision<=admin_revision),
  recorded_at BIGINT NOT NULL CHECK(recorded_at>=0),
  write_txid BIGINT NOT NULL CHECK(write_txid>0),
  commit_id UUID NOT NULL UNIQUE,
  UNIQUE(order_id,case_id,event_id),
  UNIQUE(case_id,admin_revision),
  FOREIGN KEY(order_id,case_id) REFERENCES __S__.commerce_support_cases(order_id,case_id),
  FOREIGN KEY(order_id,case_id,reply_event_id)
    REFERENCES __S__.commerce_support_events(order_id,case_id,event_id),
  CHECK((actor->>'kind'='customer' AND customer_user_id IS NOT NULL AND customer_user_id>0
    AND operator_id IS NULL AND actor IS NOT DISTINCT FROM
      jsonb_build_object('kind','customer','user_id',customer_user_id,'owner_scope',owner_scope)
    AND action IN ('create_inquiry','append_customer_message','reopen') AND visible)
    OR (actor->>'kind'='operator' AND operator_id IS NOT NULL AND operator_id>0
    AND customer_user_id IS NULL AND actor IS NOT DISTINCT FROM
      jsonb_build_object('kind','operator','operator_id',operator_id)
    AND action IN ('record_external_contact','record_reply','publish_customer_reply','internal_note','close','reopen'))),
  CHECK((action='publish_customer_reply')=(reply_event_id IS NOT NULL)),
  CHECK(NOT visible OR public_revision IS NOT NULL),
  CHECK(action NOT IN ('record_external_contact','record_reply','internal_note') OR NOT visible),
  CHECK(request ?& ARRAY['version','order_id','order_no','owner_scope','actor','command']),
  CHECK(request->>'version' IS NOT DISTINCT FROM 'commerce_support_v1'
    AND request->'actor' IS NOT DISTINCT FROM actor
    AND request->>'owner_scope' IS NOT DISTINCT FROM owner_scope
    AND request->'order_id' IS NOT DISTINCT FROM to_jsonb(order_id)
    AND request->'command'->>'operation_id' IS NOT DISTINCT FROM operation_id::text
    AND request->'command'->>'action' IS NOT DISTINCT FROM action),
  CHECK(result ?& ARRAY['case_id','origin','state','revision','recorded_at','updated_at',
    'event_id','action','event_body','visible','delivery']),
  CHECK(result->>'case_id' IS NOT DISTINCT FROM case_id::text
    AND result->>'event_id' IS NOT DISTINCT FROM event_id::text
    AND result->>'action' IS NOT DISTINCT FROM action
    AND result->>'event_body' IS NOT DISTINCT FROM body
    AND result->'visible' IS NOT DISTINCT FROM to_jsonb(visible)
    AND result->>'delivery' IS NOT DISTINCT FROM 'not_attempted'
    AND result->'updated_at' IS NOT DISTINCT FROM to_jsonb(recorded_at))
);
CREATE UNIQUE INDEX commerce_support_public_sequence ON __S__.commerce_support_events(case_id,public_revision)
  WHERE visible;

CREATE FUNCTION __S__.commerce_support_case_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $case$
DECLARE d record;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Support cases are preserved'; END IF;
  SELECT * INTO d FROM __S__.commerce_order_details WHERE order_id=NEW.order_id FOR UPDATE;
  IF NOT FOUND OR NEW.owner_scope IS DISTINCT FROM d.owner_scope OR NEW.write_txid<>txid_current() THEN
    RAISE EXCEPTION 'Support original order mismatch';
  END IF;
  IF TG_OP='INSERT' THEN
    IF NEW.admin_revision<>1 OR NEW.state<>'open' OR NEW.updated_at<>NEW.created_at
      OR (NEW.origin='customer' AND (NEW.public_revision<>1 OR NEW.public_updated_at<>NEW.created_at)) THEN
      RAISE EXCEPTION 'Support initial state mismatch';
    END IF;
  ELSE
    IF NEW.case_id IS DISTINCT FROM OLD.case_id OR NEW.order_id IS DISTINCT FROM OLD.order_id
      OR NEW.owner_scope IS DISTINCT FROM OLD.owner_scope OR NEW.origin IS DISTINCT FROM OLD.origin
      OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.admin_revision<>OLD.admin_revision+1
      OR NEW.updated_at<OLD.updated_at
      OR (NEW.origin='customer' AND (NEW.public_revision NOT IN (OLD.public_revision,OLD.public_revision+1)
        OR (NEW.public_revision=OLD.public_revision AND
          (NEW.public_updated_at IS DISTINCT FROM OLD.public_updated_at OR NEW.state IS DISTINCT FROM OLD.state)))) THEN
      RAISE EXCEPTION 'Support case revision or immutable scope mismatch';
    END IF;
  END IF;
  RETURN NEW;
END; $case$;
CREATE TRIGGER commerce_support_case_guard BEFORE INSERT OR UPDATE OR DELETE ON __S__.commerce_support_cases
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_support_case_guard();

CREATE FUNCTION __S__.commerce_support_event_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $event$
DECLARE x record; d record; draft record; previous record; cmd jsonb; expected bigint;
BEGIN
  IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Support events are immutable'; END IF;
  SELECT * INTO x FROM __S__.commerce_support_cases WHERE order_id=NEW.order_id AND case_id=NEW.case_id FOR UPDATE;
  SELECT o.order_no,c.owner_identity INTO d FROM __S__.commerce_order_details c
    JOIN __S__.orders o USING(order_id) WHERE c.order_id=NEW.order_id;
  IF x.case_id IS NULL OR NEW.owner_scope IS DISTINCT FROM x.owner_scope OR NEW.write_txid<>txid_current()
    OR x.write_txid<>NEW.write_txid OR NEW.admin_revision<>x.admin_revision
    OR NEW.public_revision IS DISTINCT FROM x.public_revision OR NEW.recorded_at<>x.updated_at
    OR NEW.visible IS DISTINCT FROM (x.origin='customer' AND NEW.action NOT IN
      ('record_external_contact','record_reply','internal_note'))
    OR NEW.request->>'order_no' IS DISTINCT FROM d.order_no
    OR NEW.result->>'origin' IS DISTINCT FROM x.origin OR NEW.result->>'state' IS DISTINCT FROM x.state
    OR NEW.result->'recorded_at' IS DISTINCT FROM to_jsonb(x.created_at) THEN
    RAISE EXCEPTION 'Support event scope mismatch';
  END IF;
  IF NEW.customer_user_id IS NOT NULL AND (x.origin<>'customer' OR d.owner_identity->>'kind'<>'guest'
    OR NEW.customer_user_id IS DISTINCT FROM (d.owner_identity->>'user_id')::bigint) THEN
    RAISE EXCEPTION 'Support customer author mismatch';
  END IF;
  IF NEW.admin_revision=1 THEN
    IF NEW.action NOT IN ('create_inquiry','record_external_contact') THEN
      RAISE EXCEPTION 'Support initial event required';
    END IF;
  ELSE
    SELECT * INTO previous FROM __S__.commerce_support_events
      WHERE case_id=NEW.case_id AND admin_revision=NEW.admin_revision-1;
    IF previous.event_id IS NULL OR NEW.action IN ('create_inquiry','record_external_contact')
      OR (x.origin='customer' AND NEW.public_revision IS DISTINCT FROM
          previous.public_revision+CASE WHEN NEW.visible THEN 1 ELSE 0 END)
      OR (NEW.visible AND x.public_updated_at<>NEW.recorded_at)
      OR (NEW.action='close' AND (previous.result->>'state'<>'open' OR x.state<>'closed'))
      OR (NEW.action='reopen' AND (previous.result->>'state'<>'closed' OR x.state<>'open'))
      OR (NEW.action NOT IN ('close','reopen') AND
        (x.state IS DISTINCT FROM previous.result->>'state'
          OR (NEW.action<>'internal_note' AND x.state<>'open'))) THEN
      RAISE EXCEPTION 'Support event transition mismatch';
    END IF;
  END IF;
  IF NEW.operator_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM __S__.admin_operators
    WHERE operator_id=NEW.operator_id AND role IN ('operator','owner') AND status='활성') THEN
    RAISE EXCEPTION 'Support operator inactive';
  END IF;
  cmd:=NEW.request->'command';
  expected:=CASE WHEN NEW.customer_user_id IS NULL THEN NEW.admin_revision-1 ELSE NEW.public_revision-1 END;
  IF jsonb_typeof(cmd)<>'object' OR NOT (cmd ?& ARRAY['operation_id','action','case_id','expected_revision'])
    OR cmd->'expected_revision' IS DISTINCT FROM to_jsonb(expected)
    OR NEW.result->'revision' IS DISTINCT FROM to_jsonb(expected+1)
    OR (NEW.action IN ('create_inquiry','record_external_contact') AND
      (cmd->'case_id' IS DISTINCT FROM 'null'::jsonb OR expected<>0
       OR (NEW.action='create_inquiry') IS DISTINCT FROM (x.origin='customer')))
    OR (NEW.action NOT IN ('create_inquiry','record_external_contact') AND
      cmd->>'case_id' IS DISTINCT FROM NEW.case_id::text) THEN
    RAISE EXCEPTION 'Support request revision mismatch';
  END IF;
  IF NEW.action='publish_customer_reply' THEN
    SELECT * INTO draft FROM __S__.commerce_support_events WHERE order_id=NEW.order_id
      AND case_id=NEW.case_id AND event_id=NEW.reply_event_id;
    IF x.origin<>'customer' OR draft.event_id IS NULL OR draft.action<>'record_reply' OR draft.visible
      OR draft.body IS DISTINCT FROM NEW.body OR draft.write_txid=txid_current()
      OR cmd->>'reply_event_id' IS DISTINCT FROM NEW.reply_event_id::text THEN
      RAISE EXCEPTION 'Support exact private draft required';
    END IF;
  ELSIF cmd->>'body' IS DISTINCT FROM NEW.body THEN
    RAISE EXCEPTION 'Support body mismatch';
  END IF;
  RETURN NEW;
END; $event$;
CREATE TRIGGER commerce_support_event_guard BEFORE INSERT OR UPDATE OR DELETE ON __S__.commerce_support_events
  FOR EACH ROW EXECUTE FUNCTION __S__.commerce_support_event_guard();

CREATE FUNCTION __S__.commerce_support_case_event_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $complete$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM __S__.commerce_support_events WHERE order_id=NEW.order_id
    AND case_id=NEW.case_id AND admin_revision=NEW.admin_revision AND write_txid=NEW.write_txid) THEN
    RAISE EXCEPTION 'Support revision requires immutable event';
  END IF;
  RETURN NULL;
END; $complete$;
CREATE CONSTRAINT TRIGGER commerce_support_case_event_complete AFTER INSERT OR UPDATE ON __S__.commerce_support_cases
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION __S__.commerce_support_case_event_guard();
'''


def _schema(bind):
    value = bind.execute(text('SELECT current_schema()')).scalar_one()
    if type(value) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise RuntimeError('Support schema unavailable')
    return '"' + value + '"'


def upgrade():
    bind = op.get_bind()
    op.execute(UPGRADE_SQL.replace('__S__', _schema(bind)))


def downgrade():
    schema = _schema(op.get_bind())
    op.execute(('''DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM __S__.commerce_support_cases LIMIT 1)
        OR EXISTS(SELECT 1 FROM __S__.commerce_support_events LIMIT 1) THEN
        RAISE EXCEPTION 'Support history must be preserved';
      END IF;
    END $$;
    DROP TABLE __S__.commerce_support_events;
    DROP TABLE __S__.commerce_support_cases;
    DROP FUNCTION __S__.commerce_support_case_event_guard();
    DROP FUNCTION __S__.commerce_support_event_guard();
    DROP FUNCTION __S__.commerce_support_case_guard();''').replace('__S__', schema))
