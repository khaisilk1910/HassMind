'use strict';

// Run with `node --test tests/test_knowledge_ui.js`; no browser packages needed.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'static','index.html'),'utf8');
const css=fs.readFileSync(path.join(root,'static','app.css'),'utf8');
const script=fs.readFileSync(path.join(root,'static','app.js'),'utf8').replace(/start\(\)\.catch\([^\n]+\);?\s*$/,'');

function harness(){
  const nodes=new Map(),calls=[];
  const element=()=>({innerHTML:'',textContent:'',value:'',checked:false,disabled:false,dataset:{},style:{},classList:{add(){},remove(){},toggle(){}},appendChild(){},remove(){},addEventListener(){},querySelector(){return null},querySelectorAll(){return []},reset(){}});
  for(const match of html.matchAll(/id="([^"]+)"/g))nodes.set(match[1],element());
  // This node is inserted into proposal details by the renderer.
  nodes.set('knowledgeDryRunResult',element());
  const sandbox={URLSearchParams,Date,Set,Map,JSON,Math,Number,String,Array,Error,Promise,encodeURIComponent,
    localStorage:{getItem(){return null},setItem(){}},crypto:{randomUUID(){return 'test-session'}},
    document:{getElementById(id){if(!nodes.has(id))throw new Error('Missing UI node: '+id);return nodes.get(id)},querySelectorAll(){return []},addEventListener(){},createElement:element},
    window:{addEventListener(){}},location:{href:'http://localhost/',replace(){}},navigator:{},setTimeout(){},setInterval(){},
    fetch:async(url,opt)=>{calls.push({url,opt});throw new Error('Unexpected request '+url)}};
  vm.createContext(sandbox);vm.runInContext(script,sandbox,{filename:'app.js'});
  return {sandbox,nodes,calls,run(code){return vm.runInContext(code,sandbox)},respond(handler){sandbox.fetch=async(url,opt)=>{calls.push({url,opt});const response=await handler(url,opt);return {ok:response.status===undefined||response.status<400,status:response.status||200,headers:{get(){return 'request-test'}},text:async()=>JSON.stringify(response.body)}}}};
}

test('Knowledge HTML includes accessible search/config forms and all review surfaces',()=>{
  for(const id of ['knowledgeSearchForm','knowledgeConfigForm','knowledgeStatus','knowledgeManifest','knowledgeScanBox','knowledgeProposals','knowledgeProposalDetail','knowledgeAudit'])assert.match(html,new RegExp('id="'+id+'"'));
  assert.match(html,/\.yml/);
  assert.match(html,/knowledge-scan/);
  assert.match(script,/knowledge:loadKnowledge/);
  assert.match(script,/knowledgeSearchForm'\)\.addEventListener\('submit'/);
});

test('Search result metadata and preview escape all untrusted fields',()=>{
  const h=harness();h.sandbox.row={type:'<svg onload=x>',name:'<img src=x onerror=x>',entity_id:'light.<script>',area:'"onclick="x',domain:'<b>',source:'</pre><script>evil()</script>',aliases:['<iframe>'],preview:'<script>evil()</script>',score:0.91,confidence:0.95,match_type:'exact'};
  const rendered=h.run('knowledgeResultHtml(row)');
  assert.doesNotMatch(rendered,/<script>|<img |<iframe>|<svg /);
  assert.match(rendered,/&lt;script&gt;/);
  for(const label of ['entity_id','Khu vực','Domain','Score / match','Nguồn','Alias','Preview','Confidence 95%'])assert.ok(rendered.includes(label),label);
});

test('Fuzzy or low confidence results warn; missing and non-finite scores show a dash',()=>{
  const h=harness();assert.match(h.run("knowledgeResultHtml({name:'AC',match_type:'fuzzy',confidence:0.98})"),/Cần xác nhận entity/);
  assert.match(h.run("knowledgeResultHtml({name:'AC',match_type:'name',confidence:0.7})"),/Cần xác nhận entity/);
  assert.doesNotMatch(h.run("knowledgeResultHtml({name:'AC',match_type:'exact',confidence:0.99})"),/knowledge-warning/);
  for(const value of ['null','undefined','NaN','Infinity',"''"])assert.equal(h.run('knowledgeNumber('+value+')'),'—');
});

test('Search sends encoded query, type, area and domain; displays result cards',async()=>{
  const h=harness();h.nodes.get('knowledgeQuery').value='máy lạnh & cửa';h.nodes.get('knowledgeArea').value='phòng ngủ';h.nodes.get('knowledgeDomain').value='climate';h.nodes.get('knowledgeType').value='entity';
  h.respond(async()=>({body:[{entity_id:'climate.bedroom',type:'entity',score:0.9,confidence:0.94,match_type:'alias'}]}));
  await h.run('searchKnowledge()');const url=new URL(h.calls[0].url,'http://localhost');
  assert.equal(url.searchParams.get('q'),'máy lạnh & cửa');assert.equal(url.searchParams.get('area'),'phòng ngủ');assert.equal(url.searchParams.get('domain'),'climate');assert.equal(url.searchParams.get('type'),'entity');assert.equal(url.searchParams.get('limit'),'20');
  assert.match(h.nodes.get('knowledgeBox').innerHTML,/climate.bedroom/);assert.equal(h.nodes.get('knowledgeSearchBtn').disabled,false);
});

test('Status renders index manifest/errors and monitor configuration without raw HTML',()=>{
  const h=harness();h.sandbox.status={index:{files:2,records:3,chunks:5,indexed_at:'2026-10-04T00:00:00Z',manifest:[{path:'<script>',hash:'0123456789abcdef',records:3}],errors:[{severity:'error',path:'<img>',message:'<svg>'}]},monitor:{enabled:false,notify_enabled:true,scan_interval_seconds:90},pending_count:2};
  h.run('renderKnowledgeStatus(status)');assert.equal(h.nodes.get('knowledgeMonitorEnabled').checked,false);assert.equal(h.nodes.get('knowledgeNotifyEnabled').checked,true);assert.equal(h.nodes.get('knowledgeScanInterval').value,90);assert.match(h.nodes.get('knowledgeManifest').innerHTML,/&lt;script&gt;/);assert.doesNotMatch(h.nodes.get('knowledgeManifest').innerHTML,/<script>|<img>|<svg>/);assert.match(h.nodes.get('knowledgeStatus').innerHTML,/Semantic records/);
});

test('Approve is disabled until successful dry-run and sends CSRF only after explicit action',async()=>{
  const h=harness();h.run("uiState.csrf='csrf-test';knowledgeUI.selected={id:'p 1',kind:'content',status:'pending',changes:[{path:'entities.yaml',diff:'- old\\n+ new'}]};renderKnowledgeProposal(knowledgeUI.selected)");
  assert.match(h.nodes.get('knowledgeProposalDetail').innerHTML,/data-action="knowledge-approve"[^>]*disabled/);
  await h.run("knowledgeProposalAction('approve','p 1')");assert.equal(h.calls.length,0);
  h.respond(async(url)=>url.endsWith('/dry-run')?{body:{valid:true,issues:[]}}:url.endsWith('/approve')?{body:{status:'applied'}}:url==='/api/knowledge/status'?{body:{index:{},monitor:{}}}:url==='/api/knowledge/proposals'?{body:[]}:url==='/api/knowledge/audit'?{body:[]}:{body:{id:'p 1',kind:'content',status:'applied',changes:[]}});
  await h.run("knowledgeProposalAction('dry-run','p 1')");assert.doesNotMatch(h.nodes.get('knowledgeProposalDetail').innerHTML,/data-action="knowledge-approve"[^>]*disabled/);
  await h.run("knowledgeProposalAction('approve','p 1')");const call=h.calls.find(item=>item.url.endsWith('/approve'));assert.ok(call);assert.equal(call.url,'/api/knowledge/proposals/p%201/approve');assert.equal(call.opt.method,'POST');assert.equal(call.opt.headers['X-CSRF-Token'],'csrf-test');assert.equal(call.opt.credentials,'same-origin');
});

test('Stale approval error invalidates dry-run and safely displays the server error',async()=>{
  const h=harness();h.run("knowledgeUI.selected={id:'stale',kind:'content',status:'pending',changes:[]};knowledgeUI.dryRun={valid:true}");h.respond(async()=>({status:409,body:{detail:'File changed <script> scan again'}}));
  await h.run("knowledgeProposalAction('approve','stale')");assert.equal(h.run('knowledgeUI.dryRun'),null);assert.match(h.nodes.get('knowledgeDryRunResult').innerHTML,/File changed &lt;script&gt;/);assert.match(h.nodes.get('knowledgeProposalDetail').innerHTML,/data-action="knowledge-approve"[^>]*disabled/);
});

test('Review-only findings never offer approval and escape proposal diff/issues',async()=>{
  const h=harness();h.run("knowledgeUI.selected={id:'bad',kind:'review',status:'pending',reason:'<img>',changes:[{path:'<script>',diff:'</pre><script>evil()</script>'}],issues:[{message:'<svg>'}]};renderKnowledgeProposal(knowledgeUI.selected)" );let output=h.nodes.get('knowledgeProposalDetail').innerHTML;assert.doesNotMatch(output,/data-action="knowledge-approve"/);assert.match(output,/không phải thay đổi có thể Approve/);
  h.respond(async()=>({body:{valid:false,issues:[{code:'schema',severity:'error',message:'<iframe>'}]}}));await h.run("knowledgeProposalAction('dry-run','bad')");output=h.nodes.get('knowledgeProposalDetail').innerHTML;assert.doesNotMatch(output,/data-action="knowledge-approve"/);assert.doesNotMatch(output,/<script>|<img>|<svg>|<iframe>/);assert.match(output,/&lt;iframe&gt;/);
});

test('Conflict diagnostics show exact records and re-index warnings do not disable approval',async()=>{
  const h=harness();h.run("knowledgeUI.selected={id:'r1',kind:'reindex',status:'pending',changes:[],issues:[{code:'entity_conflict',severity:'warning',path:'20-entities.yaml',entity_id:'light.room',conflict_fields:['name','area'],definitions:[{path:'20-entities.yaml',location:'entities[2]',entity_id:'light.room',name:'Đèn A',area_id:'bedroom',domain:'light'},{path:'20-entities.yaml',location:'entities[7]',entity_id:'light.room',name:'Đèn B',area_id:'living',domain:'light'}]}]};renderKnowledgeProposal(knowledgeUI.selected)");
  let output=h.nodes.get('knowledgeProposalDetail').innerHTML;assert.match(output,/entities\[2\]/);assert.match(output,/entities\[7\]/);assert.match(output,/khác nhau ở: name, area/);assert.match(output,/Approve &amp; Re-index/);assert.match(output,/data-action="knowledge-approve"[^>]*disabled/);
  h.respond(async(url)=>url.endsWith('/dry-run')?{body:{valid:true,warning_count:1,issues:[{code:'entity_conflict',severity:'warning',blocking:false,path:'20-entities.yaml',entity_id:'light.room',conflict_fields:['name'],definitions:[{path:'20-entities.yaml',location:'entities[2]',entity_id:'light.room',name:'Đèn A',area_id:'bedroom',domain:'light'},{path:'20-entities.yaml',location:'entities[7]',entity_id:'light.room',name:'Đèn B',area_id:'bedroom',domain:'light'}]}]}}:{body:{}});
  await h.run("knowledgeProposalAction('dry-run','r1')");output=h.nodes.get('knowledgeProposalDetail').innerHTML;assert.doesNotMatch(output,/data-action="knowledge-approve"[^>]*disabled/);assert.match(output,/1 cảnh báo không chặn áp dụng/);
});

test('Rollback is available only for applied content proposals',()=>{
  const h=harness();h.run("renderKnowledgeProposal({id:'a',kind:'content',status:'applied',changes:[]})");assert.match(h.nodes.get('knowledgeProposalDetail').innerHTML,/knowledge-rollback/);
  for(const kind of ['reindex','review']){h.run("renderKnowledgeProposal({id:'a',kind:'"+kind+"',status:'applied',changes:[]})");assert.doesNotMatch(h.nodes.get('knowledgeProposalDetail').innerHTML,/knowledge-rollback/)}
});

test('Monitor rejects invalid intervals and persists valid options with CSRF',async()=>{
  const h=harness();h.nodes.get('knowledgeScanInterval').value='29';await h.run('saveKnowledgeConfig()');assert.equal(h.calls.length,0);
  h.nodes.get('knowledgeScanInterval').value='300';h.nodes.get('knowledgeMonitorEnabled').checked=true;h.nodes.get('knowledgeNotifyEnabled').checked=false;h.run("uiState.csrf='csrf-config'");h.respond(async(url)=>({body:url.endsWith('/status')?{index:{},monitor:{}}:{ok:true}}));
  await h.run('saveKnowledgeConfig()');assert.equal(h.calls[0].opt.method,'PATCH');assert.deepEqual(JSON.parse(h.calls[0].opt.body),{enabled:true,scan_interval_seconds:300,notify_enabled:false,notify_channel:'mobile',zalo_thread_id:''});assert.equal(h.calls[0].opt.headers['X-CSRF-Token'],'csrf-config');
});

test('Scan and re-index send explicit CSRF mutations and refresh status',async()=>{
  const h=harness();h.run("uiState.csrf='csrf-scan'");h.respond(async(url)=>({body:url.endsWith('/scan')?{id:'scan-1',changes:{added:['new.yaml'],modified:[],deleted:[]},issues:[],ha_checked:true}:url.endsWith('/status')?{index:{files:1,records:2,chunks:2},latest_scan:{id:'scan-1',changes:{added:['new.yaml']},issues:[],ha_checked:true}}:url.endsWith('/proposals')||url.endsWith('/audit')?[]:{ok:true}}));
  await h.run('scanKnowledge()');await h.run('reindexKnowledge()');
  for(const endpoint of ['/api/knowledge/scan','/api/knowledge/reindex']){const call=h.calls.find(item=>item.url===endpoint);assert.equal(call.opt.method,'POST');assert.equal(call.opt.headers['X-CSRF-Token'],'csrf-scan')}
  assert.match(h.nodes.get('knowledgeScanBox').innerHTML,/1 file mới/);assert.equal(h.nodes.get('knowledgeScanBtn').disabled,false);assert.equal(h.nodes.get('knowledgeReindexBtn').disabled,false);
});

test('Current source loads into the editor and draft carries hash without applying content',async()=>{
  const h=harness();h.run("uiState.csrf='csrf-draft'");h.nodes.get('knowledgeDraftPath').value='20-entities.yaml';
  h.respond(async(url)=>({body:url.startsWith('/api/knowledge/file?')?{path:'20-entities.yaml',content:'entities: []\n',sha256:'base-hash'}:url==='/api/knowledge/proposals'?{id:'draft-1',kind:'content',status:'pending',changes:[]}:url==='/api/knowledge/status'?{index:{},monitor:{}}:url==='/api/knowledge/audit'?[]:{id:'draft-1',kind:'content',status:'pending',changes:[]}}));
  await h.run('loadKnowledgeFile()');assert.equal(h.nodes.get('knowledgeDraftContent').value,'entities: []\n');h.nodes.get('knowledgeDraftContent').value='entities:\n  - entity_id: light.room\n';h.nodes.get('knowledgeDraftReason').value='Correct alias';await h.run('createKnowledgeDraft()');
  const call=h.calls.find(item=>item.url==='/api/knowledge/proposals'&&item.opt.method==='POST');assert.ok(call);assert.equal(call.opt.headers['X-CSRF-Token'],'csrf-draft');assert.deepEqual(JSON.parse(call.opt.body),{reason:'Correct alias',changes:[{path:'20-entities.yaml',new_content:'entities:\n  - entity_id: light.room\n',expected_hash:'base-hash'}]});assert.equal(h.calls.some(item=>item.url.endsWith('/approve')),false);assert.match(h.nodes.get('knowledgeProposalDetail').innerHTML,/data-action="knowledge-approve"[^>]*disabled/);
});

test('Source-read and stale-draft errors remain reviewable and escaped',async()=>{
  const h=harness();h.nodes.get('knowledgeDraftPath').value='entities.yaml';h.nodes.get('knowledgeDraftReason').value='Fix names';h.respond(async()=>({status:409,body:{detail:'Draft source changed <script>'}}));await h.run('loadKnowledgeFile()');assert.equal(h.run('knowledgeUI.loadedSource'),null);assert.match(h.nodes.get('knowledgeDraftError').innerHTML,/&lt;script&gt;/);await h.run('createKnowledgeDraft()');assert.match(h.nodes.get('knowledgeDraftError').innerHTML,/Draft source changed/);assert.equal(h.nodes.get('knowledgeDraftBtn').disabled,false);
});

test('Retained index and recovery-needed proposals are visible',()=>{
  const h=harness();h.run("renderKnowledgeStatus({index:{status:'error',retained_previous:true,files:2,records:0,indexed_records:8,errors:[{message:'invalid yaml'}],warnings:[{message:'old state ignored'}],manifest:[{path:'x.yaml',sha256:'abcdef0123456789',status:'error'}]},recovery_required:1})");assert.match(h.nodes.get('knowledgeStatus').innerHTML,/đang giữ chỉ mục thành công trước đó/);assert.match(h.nodes.get('knowledgeStatus').innerHTML,/1 đề xuất cần khôi phục/);assert.match(h.nodes.get('knowledgeManifest').innerHTML,/hash abcdef012345/);assert.match(h.nodes.get('knowledgeManifest').innerHTML,/old state ignored/);
  assert.equal(h.run("knowledgeStatusClass('recovery_required')"),'bad');
});

test('Failed source reload keeps original editor hash so a stale draft cannot silently rebase',async()=>{
  const h=harness();h.run("knowledgeUI.loadedSource={path:'x.yaml',sha256:'original-hash'}");h.nodes.get('knowledgeDraftPath').value='x.yaml';h.nodes.get('knowledgeDraftContent').value='original content';h.nodes.get('knowledgeDraftReason').value='Correct names';h.respond(async()=>({status:409,body:{detail:'File changed'}}));
  await h.run('loadKnowledgeFile()');await h.run('createKnowledgeDraft()');const draft=h.calls.find(item=>item.url==='/api/knowledge/proposals');assert.equal(JSON.parse(draft.opt.body).changes[0].expected_hash,'original-hash');assert.equal(h.nodes.get('knowledgeDraftContent').value,'original content');
});

test('Explicit Reject and Rollback use their own endpoints and refresh the reviewed proposal',async()=>{
  for(const [action,status,resultStatus] of [['reject','pending','rejected'],['rollback','applied','rolled_back']]){
    const h=harness();h.run("uiState.csrf='csrf-decision';knowledgeUI.selected={id:'decision',kind:'content',status:'"+status+"',changes:[]}");h.respond(async(url)=>({body:url==='/api/knowledge/status'?{index:{},monitor:{}}:url==='/api/knowledge/proposals'||url==='/api/knowledge/audit'?[]:{id:'decision',kind:'content',status:resultStatus,changes:[]}}));
    await h.run("knowledgeProposalAction('"+action+"','decision')");const decision=h.calls.find(item=>item.url==='/api/knowledge/proposals/decision/'+action);assert.ok(decision);assert.equal(decision.opt.method,'POST');assert.equal(decision.opt.headers['X-CSRF-Token'],'csrf-decision');assert.equal(h.run('knowledgeUI.selected.status'),resultStatus);assert.equal(h.calls.some(item=>item.url.endsWith('/approve')),false);
  }
});


test('Changed scan fingerprint makes stale index warning visible',()=>{const h=harness();h.sandbox.status={index:{status:'ready',stale:true,files:1,chunks:1,records:1},monitor:{enabled:true},pending_count:1};h.run('renderKnowledgeStatus(status)');assert.match(h.nodes.get('knowledgeStatus').innerHTML,/Scan mới nhất khác index/);});


test('Review queue is scroll-bounded and notification controls exist for every notifying feature',()=>{
  assert.match(css,/#knowledgeProposals\s*\{[^}]*max-height:[^;}]+;[^}]*overflow-y:auto/s);
  for(const id of ['approvalNotifyChannel','approvalZaloThread','jobNotifyChannel','jobNotifyMode','jobZaloThread','ruleNotifyChannel','ruleZaloThread','knowledgeNotifyChannel','knowledgeZaloThread'])assert.match(html,new RegExp('id="'+id+'"'));
});

test('Scheduler edit loads persisted values and PUT saves notification route',async()=>{
  const h=harness();h.run("jobsCache=[{id:7,name:'Night',prompt:'Report',schedule_type:'daily',schedule_value:'21:00',notify:1,notify_channel:'zalo',zalo_thread_id:'thread-7',notify_mode:'actionable',enabled:true}];editJob(7)");
  assert.equal(h.nodes.get('jobname').value,'Night');assert.equal(h.nodes.get('jobNotifyChannel').value,'zalo');assert.equal(h.nodes.get('jobNotifyMode').value,'actionable');assert.equal(h.nodes.get('jobZaloThread').value,'thread-7');assert.equal(h.nodes.get('jobSubmitBtn').textContent,'Lưu thay đổi');
  h.nodes.get('jobname').value='Night edited';h.respond(async(url)=>({body:url==='/api/jobs/7'?{id:7,enabled:true}:[]}));await h.run('saveJob()');
  const call=h.calls.find(x=>x.url==='/api/jobs/7');assert.ok(call);assert.equal(call.opt.method,'PUT');const body=JSON.parse(call.opt.body);assert.equal(body.name,'Night edited');assert.equal(body.notify_channel,'zalo');assert.equal(body.zalo_thread_id,'thread-7');assert.equal(body.notify_mode,'actionable');
});

test('Event rule edit loads persisted values and PUT saves notification route',async()=>{
  const h=harness();h.run("rulesCache=[{id:8,name:'Door',entity_id:'binary_sensor.door',to_state:'on',prompt:'Check',cooldown_seconds:120,notify:1,notify_channel:'zalo',zalo_thread_id:'thread-8',enabled:true}];editRule(8)");
  assert.equal(h.nodes.get('rulename').value,'Door');assert.equal(h.nodes.get('ruleNotifyChannel').value,'zalo');assert.equal(h.nodes.get('ruleZaloThread').value,'thread-8');assert.equal(h.nodes.get('ruleSubmitBtn').textContent,'Lưu thay đổi');
  h.nodes.get('rulename').value='Door edited';h.respond(async(url)=>({body:url==='/api/event-rules/8'?{id:8,enabled:true}:[]}));await h.run('saveRule()');
  const call=h.calls.find(x=>x.url==='/api/event-rules/8');assert.ok(call);assert.equal(call.opt.method,'PUT');const body=JSON.parse(call.opt.body);assert.equal(body.name,'Door edited');assert.equal(body.notify_channel,'zalo');assert.equal(body.zalo_thread_id,'thread-8');
});

test('Approval notification preference saves Zalo route and defaults empty select to mobile',async()=>{
  const h=harness();h.nodes.get('approvalNotifyEnabled').checked=true;h.nodes.get('approvalNotifyChannel').value='zalo';h.nodes.get('approvalZaloThread').value='abc';h.respond(async()=>({body:{ok:true}}));await h.run('saveApprovalNotification()');
  let body=JSON.parse(h.calls[0].opt.body);assert.deepEqual(body,{enabled:true,channel:'zalo',zalo_thread_id:'abc'});
  const h2=harness();h2.nodes.get('approvalNotifyEnabled').checked=true;h2.respond(async()=>({body:{ok:true}}));await h2.run('saveApprovalNotification()');body=JSON.parse(h2.calls[0].opt.body);assert.equal(body.channel,'mobile');
});

test('Time formatter preserves the server timezone offset instead of browser-local conversion',()=>{
  const h=harness();
  assert.equal(h.run("fmtTime('2026-10-04T18:27:57.027022+07:00')"),'04/10/2026 18:27:57 +07:00');
  assert.equal(h.run("fmtTime('2026-10-04T11:27:57Z')"),'04/10/2026 11:27:57 +00:00');
});
