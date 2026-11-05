// Synthetic full upload -> inspect -> sequential extraction -> apply. No network.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
  constructor(){ this.children=[]; this.listeners={}; this.dataset={}; this._value=''; this.checked=false; this.disabled=false; this.selectedIndex=0; }
  get value(){ return this.children[this.selectedIndex]?.isOption ? this.children[this.selectedIndex].value : this._value; }
  set value(v){ this._value=v; const i=this.children.findIndex(c=>c.isOption && c.value===v); if(i>=0)this.selectedIndex=i; }
  addEventListener(name, fn){ this.listeners[name]=fn; }
  appendChild(e){ this.children.push(e); return e; }
  replaceChildren(){ this.children=[]; }
  setAttribute(){}
  dispatchEvent(){}
  get options(){ return this.children; }
  querySelectorAll(){ return this.children.flatMap(c => c.children); }
}
const nodes = {}, el = id => nodes[id] || (nodes[id]=new Element());
const calls=[];
let pageResponse = null;
const context = {
  document:{ getElementById:el, createElement:tag=>{ const e=new Element(); e.isOption=tag==='option'; return e; } },
  window:{confirm:()=>true}, Event:class {}, Map, console,
  reviewState:{ocrData:{},sources:{}},
  FileReader:class { readAsDataURL(){this.result='data:application/pdf;base64,UERG'; this.onload();} },
  fetch:async (url,opts)=>{
    if(url.includes('status')) return {json:async()=>({ai:{base_url_host:'mock',model:'mock'}})};
    const body=JSON.parse(opts.body); calls.push({url,body});
    const result=url.endsWith('inspect') ? {page_count:2} : pageResponse ? pageResponse(body.page) : {page:body.page,records:[{fields:
      body.category==='identity' ? {nama:body.page===1?'PERSON A':'PERSON B',nik:'0012345678901234'} :
      body.category==='akad' ? {akad_nomor:'001/PK',akad_tanggal:'2026-10-12',nilai_pembiayaan:body.page===1?'1000000':'2000000'} :
      {ht_nomor:'01227',lok_desa:'Desa Contoh'}}]};
    return {ok:true,json:async()=>Object.assign({ok:true},result)};
  }
};
vm.createContext(context); vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
async function upload(category, expected=2){
  el('pdf-category').value=category; el('pdf-file').files=[{size:20}];
  await el('pdf-file').listeners.change();
  assert.equal(context.pdf.count,2); assert(!el('pdf-consent').checked);
  el('pdf-consent').checked=true; await el('pdf-run').listeners.click();
  assert(!el('pdf-consent').checked); assert.equal(context.pdf.records.length,expected);
}
function realSelectValues(){
  el('pdf-values').querySelectorAll().forEach(s=>{s.value=s.options[s.selectedIndex].value;});
}
(async()=>{
  await upload('akad'); realSelectValues();
  el('pdf-apply').listeners.click();
  assert.equal(el('f_akad_nomor').value,'001/PK');
  assert.equal(el('f_akad_tanggal').value,'2026-10-12');
  assert.equal(el('f_nilai_pembiayaan').value,''); // conflict never auto-selected
  const conflict=el('pdf-values').querySelectorAll().find(s=>s.dataset.key==='nilai_pembiayaan');
  conflict.selectedIndex=2; conflict.value=conflict.options[2].value;
  el('pdf-apply').listeners.click(); assert.equal(el('f_nilai_pembiayaan').value,'2000000');
  await upload('shm'); realSelectValues(); el('pdf-apply').listeners.click();
  assert.equal(el('f_ht_nomor').value,'01227'); assert.equal(el('f_lok_desa').value,'Desa Contoh');
  await upload('identity');
  assert(el('pdf-apply').disabled);
  el('pdf-person').value='1'; el('pdf-person').listeners.change(); realSelectValues();
  el('pdf-apply').listeners.click(); assert.equal(el('f_owner_nama').value,'');
  el('pdf-role').value='owner'; el('pdf-role').listeners.change(); assert(!el('pdf-apply').disabled); el('pdf-apply').listeners.click();
  assert.equal(el('f_owner_nama').value,'PERSON B'); assert.equal(el('f_owner_nik').value,'0012345678901234');
  assert.equal(context.reviewState.sources.owner_nama,'PDF hal. 2');
  const retainedRecords=context.pdf.records, requestsAfterScan=calls.length;
  el('pdf-person').value='0'; el('pdf-person').listeners.change(); realSelectValues();
  el('pdf-role').value='spouse'; el('pdf-role').listeners.change();
  el('f_spouse_nama').disabled=true; el('f_spouse_nik').disabled=true;
  el('pdf-apply').listeners.click();
  assert.equal(el('f_spouse_nama').value,''); assert(el('f_spouse_nama').disabled);
  // Simulate the user manually enabling the corresponding form options.
  el('f_spouse_nama').disabled=false; el('f_spouse_nik').disabled=false;
  el('pdf-apply').listeners.click();
  assert.equal(el('f_spouse_nama').value,'PERSON A');
  assert.equal(el('f_owner_nama').value,'PERSON B');
  assert.equal(context.reviewState.sources.spouse_nama,'PDF hal. 1');
  el('pdf-role').value='debtor'; el('pdf-role').listeners.change();
  el('f_debtor_nama').disabled=true; el('pdf-apply').listeners.click();
  assert.equal(el('f_debtor_nama').value,''); assert(el('f_debtor_nama').disabled);
  el('f_debtor_nama').disabled=false; el('pdf-apply').listeners.click();
  assert.equal(el('f_debtor_nama').value,'PERSON A');
  assert.strictEqual(context.pdf.records,retainedRecords); assert.equal(context.pdf.records.length,2);
  assert.equal(calls.length,requestsAfterScan); // no inspect, page rendering, or AI on reuse
  assert.strictEqual(el('pdf-results').hidden,false); assert.strictEqual(el('pdf-person-controls').hidden,false);
  assert(!el('pdf-apply').disabled); assert(!el('pdf-clear').disabled);
  assert(el('pdf-applied').textContent.includes('kolom diisi'));
  assert(el('pdf-applied').textContent.includes('tanpa scan ulang'));
  el('pdf-person').value='1'; el('pdf-person').listeners.change(); realSelectValues();
  el('pdf-role').value='owner'; el('pdf-role').listeners.change();
  el('f_owner_nama').value='EXISTING'; el('pdf-apply').listeners.click(); assert.equal(el('f_owner_nama').value,'EXISTING');
  el('pdf-overwrite').checked=true; context.window.confirm=()=>false;
  el('pdf-apply').listeners.click(); assert.equal(el('f_owner_nama').value,'EXISTING');
  context.window.confirm=()=>true;
  el('pdf-apply').listeners.click(); assert.equal(el('f_owner_nama').value,'PERSON B');
  assert.equal(calls.filter(c=>c.url.endsWith('page')).length,6);
  assert(calls.filter(c=>c.url.endsWith('page')).every(c=>c.body.consent===true));
  pageResponse = page=>({page,records:[],diagnostics:{provider_record_count:0,normalized_record_count:0,recognized_field_count:0,reason:'empty_model'}});
  await upload('identity',0);
  assert(el('pdf-apply').disabled); assert(el('pdf-person').disabled);
  assert(el('pdf-summary').textContent.includes('Tidak ada identitas'));
  assert(el('pdf-summary').textContent.includes('2 halaman kosong'));
  assert(el('pdf-pages').children[0].textContent.includes('empty_model'));
  pageResponse = page=>({page,records:[],diagnostics:{provider_record_count:1,normalized_record_count:0,recognized_field_count:0,reason:'no_usable_fields'}});
  await upload('identity',0);
  assert(el('pdf-pages').children[0].textContent.includes('no_usable_fields'));
  for(const malformed of [{}, {records:null}, {records:{}}, {records:[{fields:[]}]}]){
    const before=calls.length; pageResponse=()=>malformed;
    await upload('identity',0);
    assert.equal(calls.length-before,2); // inspect + first page only
    assert.equal(context.pdf.errors.length,1); assert(el('pdf-apply').disabled);
    assert(el('pdf-summary').textContent.includes('1 halaman gagal'));
  }
  pageResponse=page=>page===1 ? {page,records:[{fields:{nama:'PARTIAL'}}]} : {};
  await upload('identity',1);
  assert.equal(context.pdf.errors.length,1); assert.equal(context.pdf.pages.length,1);
  el('pdf-person').value='0'; el('pdf-person').listeners.change();
  el('pdf-role').value='owner'; el('pdf-role').listeners.change(); assert(!el('pdf-apply').disabled);
  el('pdf-values').querySelectorAll().forEach(s=>s.value=''); el('pdf-values').listeners.change(); assert(el('pdf-apply').disabled);
  el('pdf-clear').listeners.click(); assert.equal(context.pdf.data,null);
  assert.equal(context.pdf.records.length,0); assert.equal(context.pdf.pages.length,0);
  assert.equal(el('pdf-person').children.length,0); assert.equal(el('pdf-values').children.length,0);
  assert(el('pdf-results').hidden); assert(el('pdf-apply').disabled);
  assert.equal(el('pdf-applied').textContent,''); assert.equal(el('f_spouse_nama').value,'PERSON A');
  console.log('PASS PDF UI synthetic upload, sequential pages, 3 categories, conflict, person selection, zeros, overwrite, cleanup');
})().catch(e=>{console.error(e);process.exitCode=1;});
