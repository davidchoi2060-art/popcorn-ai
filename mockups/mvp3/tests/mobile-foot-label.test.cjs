// 모바일 상세 하단 합계 줄: 라벨(「조립·기타」)이 긴 금액 문장에 밀려 한 글자씩 끊기지 않는다(2026-10-12 실서버 390px 캡처).
const assert=require('assert');const fs=require('fs');const path=require('path');
const css=fs.readFileSync(path.join(__dirname,'..','styles.css'),'utf8');
const mobile=css.slice(css.indexOf('.final-table tfoot{display:block'));
assert.match(mobile,/\.final-table tfoot th\{flex:none;white-space:nowrap\}/,'모바일 하단 라벨은 줄지 않고 줄바꿈하지 않는다');
assert.match(mobile,/\.final-table tfoot td\.final-part-price\{min-width:0;white-space:normal;word-break:keep-all\}/,'긴 금액 문장은 단어 단위로 줄바꿈한다');
console.log('mobile-foot-label ok');
