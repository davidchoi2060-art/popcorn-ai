"""mvp4 social login: static contracts and actual JS execution in Node (offline)."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MVP = ROOT / 'mockups/mvp4'

HARNESS = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const base = process.argv[1];
const source = fs.readFileSync(base + '/assets/js/auth-ui.js', 'utf8');
const joinSource = fs.readFileSync(base + '/assets/js/join.js', 'utf8');
const tick = () => new Promise(r => setTimeout(r, 0));
async function settle() { for(let i=0;i<8;i++) await tick(); }
function node() {
  return { hidden:false, disabled:false, checked:false, attrs:{}, children:[], selectors:{}, listeners:{},
    setAttribute(k,v){this.attrs[k]=v;}, removeAttribute(k){delete this.attrs[k];},
    addEventListener(k,v){this.listeners[k]=v;}, focus(){this.focused=true;},
    querySelector(q){return this.selectors[q] || (this.selectors[q]=node());},
    querySelectorAll(q){if(q==='[data-provider]')return this.providers || (this.providers = ['kakao','naver','google'].filter(p=>this.innerHTML.includes('data-provider="'+p+'"')).map(p=>{const b=node();b.dataset={provider:p};return b;}));return [];},
    appendChild(b){this.children.push(b);}, insertBefore(b){this.children.push(b);},
    remove(){this.removed=true;}, showModal(){this.open=true;},close(){this.open=false;if(this.listeners.close)this.listeners.close();}
  };
}
function env(mode, storage) {
  const top=node(),menu=node(),root=node(),body=node(), calls=[], dialogs=[];
  top.querySelector=q=>top.children.find(b=>'data-auth-entry' in b.attrs)||null;
  menu.querySelector=q=>menu.children.find(b=>'data-auth-entry' in b.attrs)||null;
  body.appendChild=d=>dialogs.push(d);
  root.selectors.form=node();const form=root.selectors.form;form.elements={terms:node(),privacy:node(),age14:node()};
  const store=storage||new Map();
  const document={body,documentElement:{classList:{add(){},remove(){}}},contains:()=>true,
    querySelector:q=>({'.nh-tools':top,'#site-menu .nh-menu-content':menu,'[data-join-root]':root,'[data-auth-entry]':top.children[0]})[q]||null,
    getElementById:id=>id==='auth-dialog'?dialogs.filter(d=>!d.removed).slice(-1)[0]:null,
    createElement:()=>node()};
  let replaced='';
  const location={pathname:'/mvp4/index.html',search:'?screen=catalog&login_error=cancelled',hash:'#catalog',reload(){this.reloaded=true;}};
  const P={pages:{},h:s=>String(s).replace(/</g,'&lt;'),icon:()=>'<img>',bindShell(){}};
  const win={PAI:P,location,history:{state:{},replaceState(s,t,url){replaced=url;}},alert(){},
    localStorage:{getItem:()=>mode==='no-key'?null:'a'.repeat(32)},
    sessionStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
    fetch(url,options){calls.push({url,options});
      if(mode==='fail' || (mode==='me-fail'&&url.endsWith('/me')))return Promise.reject(new Error('offline'));
      let status=200,data={ok:true};
      if(url.endsWith('/providers'))data={enabled:mode!=='off',providers:mode==='empty'?[]:['google','kakao']};
      if(url.endsWith('/me'))data={authenticated:mode.startsWith('member'),member:{nickname:'고객'},auth_context:{session_context_id:'session1'}};
      if(url.endsWith('/pending')){data={provider:'kakao',nickname:'이름',required:['terms','privacy','age14'],optional:['marketing']};if(mode==='expired')status=410;if(mode==='closed')status=503;}
      if(url.endsWith('/join')){data={ok:true,return_path:'/mvp4/?screen=saved'};if(mode==='duplicate'){status=409;data={detail:{code:'already_joined'}};}if(mode==='join-fail')status=500;}
      if(url.endsWith('/withdraw')&&mode==='member-withdraw-fail')status=404;
      if(url.endsWith('/withdraw')&&mode==='member-withdraw-401')status=401;
      if(url.endsWith('/signout')&&mode==='member-signout-fail')status=500;
      return Promise.resolve({ok:status===200,status,json:()=>Promise.resolve(data)});
    }};
  const ctx={window:win,document,URLSearchParams,Promise,JSON,Error,Array};
  vm.runInNewContext(source,ctx);
  return {P,ctx,top,menu,root,form,calls,dialogs,win,store,get replaced(){return replaced;}};
}
(async()=>{
  let checks=0;
  for(const mode of ['off','empty','fail','me-fail']) {
    const e=env(mode);e.P.bindShell();await settle();e.P.bindShell();await settle();
    assert.equal(e.top.children.length,0);assert.equal(e.menu.children.length,0);assert.equal(e.dialogs.length,0);
    assert.equal(e.calls.length,mode==='me-fail'?2:1);checks++;
  }
  let e=env('guest');e.P.bindShell();await settle();assert.equal(e.top.children.length,1);assert.equal(e.menu.children.length,1);
  assert.equal(e.replaced,'/mvp4/index.html?screen=catalog#catalog');assert(e.dialogs[0].innerHTML.includes('로그인을 취소했습니다.'));
  e.top.children[0].onclick();let d=e.dialogs.slice(-1)[0];let providers=d.querySelectorAll('[data-provider]');
  assert.deepEqual(providers.map(b=>b.dataset.provider),['kakao','google']);providers[0].onclick();
  assert.equal(e.win.location.href,'/api/auth/kakao/start?return=%2Fmvp4%2Findex.html%3Fscreen%3Dcatalog');
  d.querySelector('[data-auth-close]').onclick();assert(e.top.children[0].focused);checks++;
  for(const [code,text] of Object.entries({cancelled:'로그인을 취소했습니다.',state_mismatch:'로그인 시간이 지났습니다.',attempt_expired:'로그인 시간이 지났습니다.',identity_revoked:'탈퇴한 로그인 정보입니다.',member_inactive:'이용이 제한된 회원입니다.',provider_failed:'로그인하지 못했습니다.',unknown:'로그인하지 못했습니다.'})) {
    const x=env('guest');x.win.location.search='?keep=1&login_error='+code;x.P.bindShell();await settle();x.P.bindShell();await settle();
    assert.equal(x.dialogs.length,1);assert(x.dialogs[0].innerHTML.includes(text));assert.equal(x.replaced,'/mvp4/index.html?keep=1#catalog');checks++;
  }
  const noKey=env('no-key');await noKey.P.authUI.request('/api/auth/attach-guest',{},true);assert(!('X-Access-Key' in noKey.calls[0].options.headers));checks++;
  e=env('member');e.win.location.search='';e.P.bindShell();await settle();e.P.bindShell();await settle();
  assert.equal(e.calls.filter(c=>c.url.endsWith('attach-guest')).length,1);
  let call=e.calls.find(c=>c.url.endsWith('attach-guest'));assert.equal(call.options.headers['X-Access-Key'],'a'.repeat(32));assert.equal(call.options.credentials,'same-origin');
  const again=env('member',e.store);again.win.location.search='';again.P.bindShell();await settle();assert(!again.calls.some(c=>c.url.endsWith('attach-guest')));checks++;
  for(const mode of ['member-withdraw-fail','member-withdraw-401','member-signout-fail']){
    e=env(mode);e.win.location.search='';e.P.bindShell();await settle();e.top.children[0].onclick();d=e.dialogs.slice(-1)[0];
    if(mode.includes('withdraw')){d.querySelector('[data-leave]').onclick();d=e.dialogs.slice(-1)[0];const box=d.querySelector('input'),b=d.querySelector('[data-withdraw]');box.checked=true;box.onchange();b.onclick();b.onclick();await settle();assert.equal(e.calls.filter(c=>c.url.endsWith('withdraw')).length,1);if(mode.endsWith('401'))assert(e.win.location.reloaded);else assert.equal(d.querySelector('.error').hidden,false);}
    else {d.querySelector('[data-signout]').onclick();await settle();assert.equal(d.querySelector('.error').hidden,false);assert(!e.win.location.reloaded);}checks++;
  }
  for(const mode of ['off','fail','expired','closed','join','duplicate','join-fail']){
    e=env(mode);e.win.location.search='';e.P.bindShell();await settle();vm.runInNewContext(joinSource,e.ctx);e.P.pages.join().mount();await settle();
    if(['off','fail','closed'].includes(mode)){assert(!e.root.innerHTML.includes('data-restart'));assert(!e.root.innerHTML.includes('data-join-form'));}
    else if(mode==='expired')assert(e.root.innerHTML.includes('로그인 다시 시작'));
    else {assert(!e.root.innerHTML.includes('marketing'));const all=e.form.querySelector('[data-all]');all.checked=true;all.onchange();assert(!e.form.querySelector('[type=submit]').disabled);e.form.onsubmit({preventDefault(){}});e.form.onsubmit({preventDefault(){}});await settle();const joins=e.calls.filter(c=>c.url.endsWith('/join'));assert.equal(joins.length,1);assert.deepEqual(JSON.parse(joins[0].options.body),{consents:{terms:true,privacy:true,age14:true}});assert.equal(joins[0].options.headers['X-Access-Key'],'a'.repeat(32));if(mode==='join')assert.equal(e.win.location.href,'/mvp4/?screen=saved');if(mode==='duplicate')assert.equal(e.win.location.href,'/mvp4/');if(mode==='join-fail'){assert.equal(e.form.querySelector('.error').hidden,false);assert(!e.form.querySelector('[type=submit]').disabled);}}
    checks++;
  }
  console.log(JSON.stringify({checks}));
})().catch(e=>{console.error(e);process.exit(1);});
"""


class SocialLogin(unittest.TestCase):
    def test_files_and_no_remote_resources(self):
        files = ['join.html', 'assets/js/auth-ui.js', 'assets/js/join.js', 'assets/css/auth-ui.css']
        files += ['assets/icons/auth-' + p + '.svg' for p in ('kakao', 'naver', 'google')]
        for name in files:
            path = MVP / name
            self.assertTrue(path.is_file(), name)
            text = path.read_text(encoding='utf-8').replace('http://www.w3.org/2000/svg', '')
            self.assertNotRegex(text, r'https?://|(?:src|href)=[\"\x27]//')

    def test_contracts(self):
        auth = (MVP / 'assets/js/auth-ui.js').read_text(encoding='utf-8')
        join = (MVP / 'assets/js/join.js').read_text(encoding='utf-8')
        for code in ('cancelled', 'state_mismatch', 'attempt_expired', 'identity_revoked', 'member_inactive', 'provider_failed'):
            self.assertIn(code + ':', auth)
        for sentence in ('로그인을 취소했습니다.', '로그인 시간이 지났습니다. 다시 시도해 주세요.',
                         '탈퇴한 로그인 정보입니다. 고객지원으로 문의해 주세요.',
                         '이용이 제한된 회원입니다. 고객지원으로 문의해 주세요.',
                         '로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.'):
            self.assertIn(sentence, auth)
        self.assertIn('data.enabled !== true', auth)
        self.assertIn("'/api/auth/' + provider + '/start?return='", auth)
        self.assertIn('/api/auth/attach-guest', auth)
        self.assertIn('X-Access-Key', auth)
        self.assertIn("['terms', 'privacy', 'age14']", join)
        self.assertNotIn('marketing', join)
        self.assertNotRegex(auth + join, r'localStorage\.(?:setItem|removeItem)')
        self.assertIn('noindex', (MVP / 'join.html').read_text(encoding='utf-8'))

    def test_shell_pages_load_auth_after_header_before_boot(self):
        for path in MVP.glob('*.html'):
            text = path.read_text(encoding='utf-8')
            if 'assets/js/core.js' not in text:
                continue  # Redirects and standalone previews do not have PAI.shell.
            self.assertIn('assets/js/auth-ui.js', text, path.name)
            self.assertLess(text.index('assets/js/header-ui.js'), text.index('assets/js/auth-ui.js'), path.name)
            for boot in ('assets/js/boot.js', 'assets/js/design-boot.js'):
                if boot in text:
                    self.assertLess(text.index('assets/js/auth-ui.js'), text.index(boot), path.name)

    def test_offline_behaviour(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node 없음')
        out = subprocess.run([node, '-e', HARNESS, str(MVP)], capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertGreaterEqual(json.loads(out.stdout)['checks'], 24)


if __name__ == '__main__':
    unittest.main()
