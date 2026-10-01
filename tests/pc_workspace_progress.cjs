// Verify proposal generation is not presented as product persistence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const calls = [];
const document = {
  getElementById: id => nodes.get(id),
  createElement: () => ({style: {}, setAttribute() {}}),
  head: {appendChild() {}},
  body: {appendChild(node) {nodes.set(node.id, node);}},
};
const window = {fetch: async (url, init) => {
  calls.push([url, init]);
  return {ok:true, status:200, clone() {return {json:async()=>({})};}};
}};
const context = {window, document, URL, location:{origin:'https://admin.popcornai.co.kr'}, setTimeout:()=>0, clearTimeout() {}};
vm.runInNewContext(fs.readFileSync('mockups/shared/ui-progress.js','utf8'),context);
(async () => {
  for (const mode of ['copy','review','sources']) {
    await window.fetch('/api/admin/pc-configurations/N07/ai-proposals',{method:'POST',body:JSON.stringify({mode})});
    assert.equal(nodes.has('__pc_progress'),false, 'AI draft must not display a saving banner');
  }
  await window.fetch('/api/admin/pc-configurations/N07/description',{method:'PUT',body:'{}'});
  assert.match(nodes.get('__pc_progress').innerHTML,/완료되었습니다/, 'real save retains completion feedback');
  assert.equal(calls.length,4);
  console.log('AI proposal modes and actual description-save progress checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
