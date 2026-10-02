import copy,json,unittest
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException
from pydantic import ValidationError
from api import admin_part_workspace as w
from api.part_explanations import fingerprint,present
class WorkspaceTests(unittest.TestCase):
 def row(self):
  return dict(source_product_code=1,product_code=1,product_name='CPU',spec_source_text='DDR5',source_fingerprint=fingerprint('CPU','DDR5'),source_snapshot={'name':'CPU','spec':'DDR5'},status='approved',sale_status='판매중',sale_price=1,updated_at='now',content={'facts':[{'label':'규격','value':'DDR5','source_id':'maker','verification':'확인'}],'role':'이전','highlights':[],'cautions':[],'questions':[],'review_issues':['추가 확인']})
 def body(self,row,role='새 설명'):
  value=w.editable(row['content']);value['role']=role
  return w.Save(basis=w.basis(row),content=value,evidence_note='제조사 자료 확인')
 def test_edits_preserve_sources_and_reopen_review(self):
  row=self.row();conn=unittest.mock.Mock()
  with patch.object(w,'read',return_value=row),patch.object(w,'usages',return_value=[]):
   self.assertTrue(w.save(conn,1,self.body(row),{'operator_id':1})['changed'])
  data=json.loads(conn.execute.call_args.args[1]['v'])
  self.assertEqual(data['facts'],row['content']['facts']);self.assertEqual(data['review_issues'],['추가 확인'])
  self.assertIn("status='draft'",str(conn.execute.call_args.args[0]));self.assertNotIn('source_fingerprint=',str(conn.execute.call_args.args[0]))
  self.assertEqual(data['_admin_part_history'][0]['before'],{'role':'이전'})
 def test_stale_and_noop_do_not_write(self):
  row=self.row();conn=unittest.mock.Mock();body=self.body(row);body.basis='0'*64
  with patch.object(w,'read',return_value=row),patch.object(w,'usages',return_value=[]):
   with self.assertRaises(HTTPException):w.save(conn,1,body,{'operator_id':1})
   self.assertFalse(w.save(conn,1,self.body(row,'이전'),{'operator_id':1})['changed'])
  conn.execute.assert_not_called()
 def test_changed_fact_loses_original_verification(self):
  row=self.row();body=self.body(row);body.content.facts[0].value='DDR4';conn=unittest.mock.Mock()
  with patch.object(w,'read',return_value=row),patch.object(w,'usages',return_value=[]):w.save(conn,1,body,{'operator_id':1})
  f=json.loads(conn.execute.call_args.args[1]['v'])['facts'][0]
  self.assertNotIn('source_id',f);self.assertIn('운영자 편집',f['verification'])
 def test_ai_cannot_change_specs_or_emit_wrong_type(self):
  row=self.row()
  for change in [{'field':'facts','value':[],'reason':'bad'},{'field':'role','value':[],'reason':'bad'}]:
   with self.assertRaises(ValidationError):w.parse(json.dumps({'changes':[change],'notes':[]}),row['content'])
  out=w.parse(json.dumps({'changes':[{'field':'role','value':'새 설명','reason':'쉽게'}],'notes':[]}),row['content'])
  self.assertEqual(out['changes'][0]['value'],'새 설명')
 def test_ai_proposal_is_readonly_and_checks_latest_basis(self):
  row=self.row();result=unittest.mock.Mock(text=json.dumps({'changes':[{'field':'role','value':'쉬운 설명','reason':'이해 개선'}],'notes':[]}),provider='test',model='stub')
  req=Request({'type':'http','headers':[]})
  with patch.object(w,'permission'),patch.object(w,'read',return_value=row),patch.object(w.llm,'call',return_value=result) as call:
   out=w.propose(1,w.Suggest(basis=w.basis(row)),req)
   self.assertEqual(out['changes'][0]['value'],'쉬운 설명');self.assertEqual(call.call_args.kwargs['fallback_order'],[])
  changed=copy.deepcopy(row);changed['sale_price']=2
  with patch.object(w,'permission'),patch.object(w,'read',side_effect=[row,changed]),patch.object(w.llm,'call',return_value=result):
   with self.assertRaises(HTTPException):w.propose(1,w.Suggest(basis=w.basis(row)),req)
 def test_approval_state_requires_audit_record(self):
  row=self.row();row['content']['review_issues']=[]
  self.assertEqual(w.state(row),'pending')
  row.update(approved_by=1,approved_at='now');self.assertEqual(w.state(row),'approved')
 def test_private_history_not_public_or_ai(self):
  row=self.row();row['content']['_admin_part_history']=[{'operator_id':99}]
  self.assertNotIn('_admin_part_history',present(row));self.assertNotIn('_admin_part_history',w.ai_context(row))
 def test_permission_and_cross_site(self):
  for actor,site in [(None,'same-origin'),({'role':'viewer'},'same-origin'),({'role':'owner'},'cross-site')]:
   with patch.object(w,'current_operator',return_value=actor):
    with self.assertRaises(HTTPException):w.permission(Request({'type':'http','headers':[(b'sec-fetch-site',site.encode())]}))
if __name__=='__main__':unittest.main()
