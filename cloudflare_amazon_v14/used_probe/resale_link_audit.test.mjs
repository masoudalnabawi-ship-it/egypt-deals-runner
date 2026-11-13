import test from 'node:test';
import assert from 'node:assert/strict';
import {validAuditDestination,auditResaleLinks} from './resale_link_audit.js';
const snap=(markdown='',tree={role:'root',children:[]})=>({result:{markdown,accessibilityTree:tree}});
test('audit restricted to exact user-provided Amazon Resale node',()=>{
  assert.equal(validAuditDestination('https://www.amazon.eg/b?node=27972173031'),true);
  assert.equal(validAuditDestination('https://www.amazon.eg/l/27972173031'),true);
  assert.equal(validAuditDestination('https://www.amazon.eg/b?node=27972175031'),false);
  assert.equal(validAuditDestination('https://other.example/b?node=27972173031'),false);
  assert.equal(validAuditDestination('https://www.amazon.eg/ap/signin'),false);
});
test('metadata keywords alone never prove a resale listing',()=>{
  const x=auditResaleLinks(snap('---\nkeywords: "Amazon Resale"\n---\nVisit our store!'));
  assert.equal(x.resale_keyword_in_metadata,true);assert.equal(x.resale_keyword_in_body,false);
  assert.equal(x.diagnosis,'RESALE_KEYWORD_METADATA_ONLY_NO_LISTING_PROOF');
  assert.equal(x.product_candidate_count,0);
});
test('recognizes slugged Amazon product route from markdown, no price claims',()=>{
  const x=auditResaleLinks(snap('[product](https://www.amazon.eg/Redmi-Buds/dp/B0DBHRWRKC/ref=something)'));
  assert.equal(x.product_candidate_count,1);
  assert.equal(x.product_candidates[0].asin,'B0DBHRWRKC');
  assert.equal(x.product_candidates[0].used_verified,false);
});
test('reads common URL fields on accessibility link node',()=>{
  const x=auditResaleLinks(snap('',{role:'main',children:[{role:'link',target:'/gp/aw/d/B0DBHRWRKC'},{role:'link',link:'/l/12345678901'}]}));
  assert.equal(x.accessibility_link_roles_with_target,2);assert.equal(x.product_candidate_count,1);
  assert.equal(x.category_candidate_count,1);
});
test('external products are excluded and private query strings are not reported',()=>{
  const x=auditResaleLinks(snap('[bad](https://evil.example/dp/B0DBHRWRKC?secret=a) [root](https://www.amazon.eg/?token=xyz)'));
  assert.equal(x.product_candidate_count,0);assert.equal(x.link_kind_counts.external,1);
  assert.equal(JSON.stringify(x).includes('secret=a'),false);
  assert.equal(JSON.stringify(x).includes('token=xyz'),false);
});
test('accessibility roles without href are identified accurately',()=>{
  const x=auditResaleLinks(snap('',{role:'root',children:[{role:'link',name:'Resale'}, {role:'link',name:'Store'}]}));
  assert.equal(x.accessibility_link_roles,2);assert.equal(x.accessibility_link_property_shapes.NO_LINK_TARGET,2);
  assert.equal(x.diagnosis,'ACCESSIBILITY_LINKS_HAVE_NO_HREF');
});
test('single page never reports used-offer verification',()=>{
  const x=auditResaleLinks(snap('[p](/dp/B0DBHRWRKC)'));
  assert.equal(x.verified_used_offers,0);assert.equal(x.public_posting_enabled,false);
});

test('same-line product signals remain diagnostic, never verified offers',()=>{
  const x=auditResaleLinks(snap(
    '[Used like new product — EGP 450](https://www.amazon.eg/dp/B0DBHRWRKC?tag=private)\n'+
    '[Regular item](https://www.amazon.eg/dp/B09381LZWT)'
  ));
  assert.equal(x.product_candidate_count,2);
  const used=x.product_candidates.find(p=>p.asin==='B0DBHRWRKC');
  assert.equal(used.same_line_used_keyword,true);
  assert.equal(used.same_line_currency_marker,true);
  assert.equal(used.used_verified,false);
  assert.equal(used.context_is_diagnostic_only,true);
  assert.equal(x.product_links_with_both_signals,1);
  assert.equal(x.verified_used_offers,0);
  assert.equal(x.public_posting_enabled,false);
  assert.equal(JSON.stringify(x).includes('tag=private'),false);
});
