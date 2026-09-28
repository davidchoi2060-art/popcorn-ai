"""Catalog-based usage rules for conversation, separate from generation grids."""
import json
from pathlib import Path
from alembic import op
import sqlalchemy as sa
revision='0118'
down_revision='0117'
branch_labels=None
depends_on=None
def upgrade():
    op.execute('''CREATE TABLE pc_usage_rule_sets(rule_version TEXT PRIMARY KEY,content JSONB NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
    op.execute('''CREATE TABLE pc_usage_scenarios(scenario_id TEXT PRIMARY KEY,rule_version TEXT NOT NULL REFERENCES pc_usage_rule_sets(rule_version),content JSONB NOT NULL)''')
    data=json.loads((Path(__file__).resolve().parents[1]/'data/pc_usage_rules_20260928.json').read_text(encoding='utf-8'))
    c=op.get_bind()
    c.execute(sa.text('INSERT INTO pc_usage_rule_sets(rule_version,content) VALUES(:v,CAST(:c AS jsonb))'),{'v':data['rule_version'],'c':json.dumps({k:data[k] for k in ['requirements','sources']},ensure_ascii=False)})
    for s in data['scenarios']:
        c.execute(sa.text('INSERT INTO pc_usage_scenarios(scenario_id,rule_version,content) VALUES(:id,:v,CAST(:c AS jsonb))'),{'id':s['id'],'v':data['rule_version'],'c':json.dumps(s,ensure_ascii=False)})
def downgrade():
    op.execute('DROP TABLE pc_usage_scenarios');op.execute('DROP TABLE pc_usage_rule_sets')
