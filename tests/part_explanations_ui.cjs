const assert=require('node:assert/strict');
const {markup}=require('../mockups/shared/part-explanations.js');
const p={product_code:1,name:'<script>alert(1)</script>',role:'safe',slot:'CPU',price:30000,image_url:'javascript:alert(1)',facts:[{label:'<b>x</b>',value:'<img onerror=x>'}],review_issues:['draft'],sources:[{url:'javascript:alert(1)',title:'bad'}]};
const h=markup(p,{review:true});
assert(h.includes('&lt;script&gt;'));assert(!h.includes('<script>'));assert(!h.includes('src="javascript:'));assert(!h.includes('href="javascript:'));
assert(h.includes('30,000원'));assert(h.includes('<details'));assert(h.includes('검토 초안'));
assert(!markup(p).includes('검토 초안'));
console.log('part explanation UI escaping and disclosure checks passed');
