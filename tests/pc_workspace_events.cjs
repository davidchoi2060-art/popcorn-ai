// Nested detail tabs must be handled by their own editor, without remounting it.
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const handlers={}, elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',addEventListener(){},querySelector(){return null;},showModal(){throw Error('Nested tab reopened dialog');}});return elements.get(id);}
const document={getElementById:element,addEventListener(type,fn){handlers[type]=fn;},querySelectorAll(){return [];}};
const window={addEventListener(){},PcCatalogDetail:{mount(){throw Error('Nested detail tab remounted');}}};
const context={document,window,URLSearchParams,location:{search:''},fetch:async()=>({ok:true,json:async()=>({items:[]})})};
vm.runInNewContext(fs.readFileSync('mockups/shared/pc-workspace.js','utf8'),context);
for(const tab of ['parts','copy','review']){
  const button={dataset:{tab},closest(){return null;},hasAttribute(){return false;}};
  assert.doesNotThrow(()=>handlers.click({target:{closest(){return button;}}}));
}
console.log('Nested detail tab event isolation checks passed');
