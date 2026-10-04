'use strict';
const APP_VERSION='1.2.4';
const $=id=>document.getElementById(id);
function makeSessionId(){if(globalThis.crypto&&typeof globalThis.crypto.randomUUID==='function')return globalThis.crypto.randomUUID();return 'web-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,12)}
const uiState={sessionId:localStorage.getItem('hassmind_session')||makeSessionId(),activeTab:'overview',csrf:'',user:null,passwordMinLength:14};
localStorage.setItem('hassmind_session',uiState.sessionId);
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function fmtTime(ts){try{return new Date(ts).toLocaleString('vi-VN',{hour12:false})}catch{return ts||''}}
function fmtDuration(seconds){seconds=Number(seconds||0);if(seconds<60)return seconds.toFixed(0)+'s';if(seconds<3600)return Math.floor(seconds/60)+'m '+Math.floor(seconds%60)+'s';return Math.floor(seconds/3600)+'h '+Math.floor((seconds%3600)/60)+'m'}
function toast(message,bad=false){const d=document.createElement('div');d.className='toast'+(bad?' bad':'');d.textContent=message;$('toastHost').appendChild(d);setTimeout(()=>d.remove(),4500)}
function hasLeadingEmoji(text){return /^[\u2600-\u27BF\u{1F300}-\u{1FAFF}]/u.test(String(text||'').trim())}
function semanticEmoji(text,heading=false){
  const raw=String(text||'').trim();if(!raw||hasLeadingEmoji(raw))return '';
  const t=raw.toLocaleLowerCase('vi-VN');
  const rules=[
    [/kết luận|tổng kết|tóm tắt|summary|trạng thái chung|an toàn/,'✅'],
    [/hiện diện|presence|occupancy|chuyển động|motion|giám sát/,'👁️'],
    [/camera|frigate/,'📷'],[/cửa|door|contact/,'🚪'],
    [/đèn|chiếu sáng|light/,'💡'],[/quạt|fan/,'🌀'],[/điều hòa|climate|air conditioner/,'❄️'],
    [/ổ cắm|socket|plug/,'🔌'],[/máy in|printer/,'🖨️'],
    [/nhiệt độ|temperature/,'🌡️'],[/độ ẩm|humidity/,'💧'],[/môi trường|environment/,'🌿'],
    [/điện năng|năng lượng|energy|power/,'⚡'],[/mạng|wifi|network/,'📡'],[/âm thanh|media|tts/,'🔊'],
    [/lỗi|error|unavailable|mất kết nối/,'⚠️']
  ];
  for(const [re,icon] of rules)if(re.test(t))return icon;
  return heading?'📌':'•';
}
function appendInlineMarkdown(parent,text){
  const src=String(text??'');let i=0,buffer='';
  const flush=()=>{if(buffer){parent.appendChild(document.createTextNode(buffer));buffer=''}};
  const addWrapped=(tag,content,cls='')=>{flush();const el=document.createElement(tag);if(cls)el.className=cls;appendInlineMarkdown(el,content);parent.appendChild(el)};
  while(i<src.length){
    if(src[i]==='\\'&&i+1<src.length&&'\\`*_~#[]'.includes(src[i+1])){buffer+=src[i+1];i+=2;continue}
    if(src[i]==='`'){
      const j=src.indexOf('`',i+1);if(j!==-1){flush();const code=document.createElement('code');code.className='chat-inline-code';code.textContent=src.slice(i+1,j);parent.appendChild(code);i=j+1;continue}
    }
    if(src.startsWith('**',i)||src.startsWith('__',i)){
      const marker=src.slice(i,i+2),j=src.indexOf(marker,i+2);if(j!==-1){addWrapped('strong',src.slice(i+2,j),'chat-strong');i=j+2;continue}
    }
    if(src.startsWith('~~',i)){
      const j=src.indexOf('~~',i+2);if(j!==-1){addWrapped('del',src.slice(i+2,j));i=j+2;continue}
    }
    if((src[i]==='*'||src[i]==='_')&&src[i+1]&&!/\s/.test(src[i+1])){
      const marker=src[i],j=src.indexOf(marker,i+1);if(j>i+1){addWrapped('em',src.slice(i+1,j));i=j+1;continue}
    }
    buffer+=src[i];i++;
  }
  flush();
}
function parseListLine(line){
  const m=String(line).replace(/\t/g,'    ').match(/^(\s*)([-+*]|\d+[.)])\s+(.+)$/);if(!m)return null;
  return {indent:m[1].length,ordered:/^\d/.test(m[2]),text:m[3]};
}
function isTableSeparator(line){return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(String(line||''))}
function tableCells(line){let v=String(line||'').trim();if(v.startsWith('|'))v=v.slice(1);if(v.endsWith('|'))v=v.slice(0,-1);return v.split('|').map(x=>x.trim())}
function renderMarkdown(target,text){
  target.replaceChildren();target.classList.add('chat-markdown');
  const lines=String(text??'').replace(/(?:&#x20;|&#32;|&nbsp;)/gi,' ').replace(/\r\n?/g,'\n').split('\n');let i=0;
  const appendParagraph=(chunk)=>{const p=document.createElement('p');chunk.forEach((line,idx)=>{appendInlineMarkdown(p,line.trim());if(idx<chunk.length-1)p.appendChild(document.createElement('br'))});target.appendChild(p)};
  while(i<lines.length){
    const line=lines[i];if(!line.trim()){i++;continue}
    const fence=line.match(/^\s*```([^`]*)$/);if(fence){const code=[];i++;while(i<lines.length&&!/^\s*```\s*$/.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;const pre=document.createElement('pre');pre.className='chat-code-block';const c=document.createElement('code');if(fence[1].trim())c.dataset.language=fence[1].trim();c.textContent=code.join('\n');pre.appendChild(c);target.appendChild(pre);continue}
    const heading=line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);if(heading){const h=document.createElement('h'+Math.min(6,heading[1].length));const icon=semanticEmoji(heading[2],true);if(icon){const span=document.createElement('span');span.className='chat-heading-icon';span.textContent=icon;h.appendChild(span)}appendInlineMarkdown(h,heading[2]);target.appendChild(h);i++;continue}
    if(/^\s{0,3}((---+)|(\*\*\*+)|(___+))\s*$/.test(line)){target.appendChild(document.createElement('hr'));i++;continue}
    if(i+1<lines.length&&line.includes('|')&&isTableSeparator(lines[i+1])){
      const table=document.createElement('table');table.className='chat-table';const thead=document.createElement('thead'),tr=document.createElement('tr');for(const cell of tableCells(line)){const th=document.createElement('th');appendInlineMarkdown(th,cell);tr.appendChild(th)}thead.appendChild(tr);table.appendChild(thead);i+=2;const tbody=document.createElement('tbody');while(i<lines.length&&lines[i].trim()&&lines[i].includes('|')){const row=document.createElement('tr');for(const cell of tableCells(lines[i])){const td=document.createElement('td');appendInlineMarkdown(td,cell);row.appendChild(td)}tbody.appendChild(row);i++}table.appendChild(tbody);target.appendChild(table);continue
    }
    const firstList=parseListLine(line);if(firstList){
      const root=document.createElement(firstList.ordered?'ol':'ul');root.className='chat-list';target.appendChild(root);const stack=[{indent:firstList.indent,ordered:firstList.ordered,list:root,lastLi:null}];
      while(i<lines.length){const item=parseListLine(lines[i]);if(!item)break;let current=stack[stack.length-1];while(stack.length>1&&item.indent<current.indent){stack.pop();current=stack[stack.length-1]}
        if(item.indent>current.indent&&current.lastLi){const nested=document.createElement(item.ordered?'ol':'ul');nested.className='chat-list nested';current.lastLi.appendChild(nested);current={indent:item.indent,ordered:item.ordered,list:nested,lastLi:null};stack.push(current)}
        else if(item.indent===current.indent&&item.ordered!==current.ordered){break}
        const li=document.createElement('li');if(!item.ordered){const icon=document.createElement('span');icon.className='chat-bullet-icon';icon.textContent=semanticEmoji(item.text,false);li.appendChild(icon)}appendInlineMarkdown(li,item.text);current.list.appendChild(li);current.lastLi=li;i++;
      }continue
    }
    if(/^\s*>\s?/.test(line)){const q=document.createElement('blockquote');const qlines=[];while(i<lines.length&&/^\s*>\s?/.test(lines[i]))qlines.push(lines[i++].replace(/^\s*>\s?/,''));qlines.forEach((x,idx)=>{appendInlineMarkdown(q,x);if(idx<qlines.length-1)q.appendChild(document.createElement('br'))});target.appendChild(q);continue}
    const para=[];while(i<lines.length&&lines[i].trim()){
      const next=lines[i];if(para.length&&( /^\s*```/.test(next)||/^\s*#{1,6}\s+/.test(next)||parseListLine(next)||/^\s*>\s?/.test(next)||/^\s{0,3}---+\s*$/.test(next)||(i+1<lines.length&&next.includes('|')&&isTableSeparator(lines[i+1]))))break;para.push(next);i++}
    appendParagraph(para);
  }
}
function renderChatText(target,text,enableMarkdown=false){target.classList.remove('chat-markdown');if(enableMarkdown){renderMarkdown(target,text);return}target.replaceChildren();target.textContent=String(text??'')}
async function copyTextSafe(value,sourceElement=null){
  const text=String(value??'');if(!text)throw new Error('Không có nội dung để sao chép.');
  if(globalThis.isSecureContext===true&&navigator.clipboard&&typeof navigator.clipboard.writeText==='function'){try{await navigator.clipboard.writeText(text);return 'clipboard'}catch{}}
  const previous=document.activeElement,ta=document.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.setAttribute('aria-hidden','true');ta.style.position='fixed';ta.style.top='0';ta.style.left='-9999px';ta.style.opacity='0';document.body.appendChild(ta);
  let ok=false;try{ta.focus();ta.select();ta.setSelectionRange(0,ta.value.length);ok=typeof document.execCommand==='function'&&document.execCommand('copy')}catch{}finally{ta.remove();try{previous&&typeof previous.focus==='function'&&previous.focus()}catch{}}
  if(!ok&&sourceElement){try{sourceElement.focus();sourceElement.select();sourceElement.setSelectionRange(0,String(sourceElement.value||'').length)}catch{}}
  if(!ok)throw new Error('Trình duyệt đã chặn clipboard. Nội dung đã được chọn để bạn nhấn Ctrl/Cmd+C.');return 'legacy'
}
class ApiError extends Error{constructor(message,status,requestId){super(message);this.status=status;this.requestId=requestId||''}}
async function api(path,opt={}){
  const method=(opt.method||'GET').toUpperCase();
  const headers=Object.assign({},opt.headers||{});
  if(opt.body!==undefined&&!headers['Content-Type'])headers['Content-Type']='application/json';
  if(!['GET','HEAD','OPTIONS'].includes(method)&&uiState.csrf)headers['X-CSRF-Token']=uiState.csrf;
  const r=await fetch(path,Object.assign({},opt,{method,headers,credentials:'same-origin'}));
  const rid=r.headers.get('x-request-id')||'';const text=await r.text();let data;try{data=JSON.parse(text)}catch{data=text}
  if(r.status===401&&path!=='/api/auth/me'){location.replace('/login');throw new ApiError('Phiên đăng nhập đã hết hạn.',401,rid)}
  if(!r.ok){const msg=typeof data==='string'?data:(data.detail||data.message||JSON.stringify(data));throw new ApiError(msg,r.status,(data&&data.request_id)||rid)}
  return data;
}
function errorHtml(e){return `<div class="error-text"><strong>${esc(e.message||e)}</strong>${e.requestId?`<div class="small-text mono mt-10">Request ID: ${esc(e.requestId)}</div>`:''}</div>`}
async function reportClientError(event,message,stack='',details={}){if(!uiState.csrf)return;try{await api('/api/client-log',{method:'POST',body:JSON.stringify({level:'ERROR',event,message:String(message||''),stack:String(stack||''),url:location.href,session_id:uiState.sessionId,details})})}catch{}}
window.addEventListener('error',e=>reportClientError('window_error',e.message,e.error?.stack||'',{filename:e.filename,lineno:e.lineno,colno:e.colno}));
window.addEventListener('unhandledrejection',e=>reportClientError('unhandled_rejection',String(e.reason?.message||e.reason),e.reason?.stack||''));

async function initAuth(){
  try{const me=await api('/api/auth/me');uiState.csrf=me.csrf_token||'';uiState.user=me.user;$('currentUser').textContent=me.user.username;$('userAvatar').textContent=(me.user.username||'A').slice(0,1).toUpperCase();$('session').textContent='session: '+uiState.sessionId;return true;}
  catch(e){if(e.status===401){location.replace('/login');return false}throw e}
}
async function logout(){try{await api('/api/auth/logout',{method:'POST',body:'{}'})}catch{}location.replace('/login')}
async function health(){const pill=$('healthPill');try{const r=await fetch('/health',{cache:'no-store'});const j=await r.json();pill.className='health-pill '+(j.ok?'ok':'bad');$('healthText').textContent=j.ok?`HassMind ${APP_VERSION} · online`:'Không khỏe'}catch{pill.className='health-pill bad';$('healthText').textContent='offline'}}
function metric(label,value,sub=''){return `<div class="card metric span-3"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div>${sub?`<div class="metric-sub">${esc(sub)}</div>`:''}</div>`}

async function loadOverview(){const box=$('overviewMetrics');try{const [s,d,skills]=await Promise.all([api('/api/status'),api('/api/diagnostics'),api('/api/skills')]);box.innerHTML=[metric('HassMind',s.version,`uptime ${fmtDuration(s.uptime_seconds)}`),metric('Home Assistant',s.ha_connected?'Connected':'Disconnected',s.ha_version||s.ha_error||''),metric('LLM model',s.model||'—'),metric('Logging',s.log_level||'—',d.logging?.path||''),metric('Database',d.database?.exists?'Ready':'Missing',`${d.database?.size_bytes||0} bytes`),metric('DB writable',d.database?.parent_writable?'Yes':'No',d.database?.path||''),metric('Background tasks',d.runtime?.background_tasks?.length||0),metric('Log buffer',d.logging?.ring_size||0,`include_content=${d.logging?.include_content}`)].join('');$('diagBox').textContent=JSON.stringify(d,null,2);$('skillsBox').innerHTML=(skills||[]).map(x=>`<div class="item"><div class="item-head"><strong>${esc(x.name)}</strong></div><div class="small-text muted mt-10">${esc(x.description||'')}</div></div>`).join('')||'<div class="empty">Không có skill.</div>'}catch(e){box.innerHTML=`<div class="card card-pad span-12">${errorHtml(e)}</div>`;$('diagBox').textContent=e.message}}
function clearChatEmpty(){const e=$('chatEmpty');if(e)e.remove()}
function addMsg(role,text,meta='',isError=false){clearChatEmpty();const row=document.createElement('div');row.className='msg-row '+role;const bubble=document.createElement('div');bubble.className='msg'+(isError?' error':'');const body=document.createElement('div');renderChatText(body,text,role==='assistant'&&!isError);bubble.appendChild(body);if(meta){const m=document.createElement('div');m.className='msg-meta mono';m.textContent=meta;bubble.appendChild(m)}row.appendChild(bubble);$('chatbox').appendChild(row);$('chatbox').scrollTop=$('chatbox').scrollHeight;return {row,bubble,body}}
async function sendChat(){const el=$('chatinput'),text=el.value.trim();if(!text)return;el.value='';addMsg('user',text);const pending=addMsg('assistant','Đang xử lý…');$('sendBtn').disabled=true;try{const j=await api('/api/chat',{method:'POST',body:JSON.stringify({session_id:uiState.sessionId,message:text})});renderChatText(pending.body,j.answer,true);if(j.request_id){const m=document.createElement('div');m.className='msg-meta mono';m.textContent='request: '+j.request_id;pending.bubble.appendChild(m)}}catch(e){pending.bubble.classList.add('error');renderChatText(pending.body,'ERROR: '+e.message,false);if(e.requestId){const m=document.createElement('div');m.className='msg-meta mono';m.textContent='Request ID: '+e.requestId;pending.bubble.appendChild(m)}reportClientError('chat_error',e.message,e.stack||'',{request_id:e.requestId||''})}finally{$('sendBtn').disabled=false;el.focus()}}
function newSession(){uiState.sessionId=makeSessionId();localStorage.setItem('hassmind_session',uiState.sessionId);$('session').textContent='session: '+uiState.sessionId;$('chatbox').innerHTML='<div class="chat-empty" id="chatEmpty"><div><strong>Phiên mới</strong><div class="small-text mt-10">Session đã được tạo lại.</div></div></div>';toast('Đã tạo phiên mới')}

function integrationCard(name,x){
  const status=x?.status||'unknown',ok=!!x?.ok,enabled=x?.enabled!==false,badge=!enabled?'warn':ok?'ok':'bad';
  const title=x?.name||name;
  return `<div class="card card-pad integration-status-card"><div class="card-title"><div><h3>${esc(title)}</h3>${x?.custom?`<div class="small-text muted mono">${esc(x.integration_id||name)}</div>`:''}</div><span class="badge ${badge}">${esc(status)}</span></div>${x?.error?`<div class="error-text small-text mt-10">${esc(x.error)}</div>`:''}<details class="mt-10"><summary>Chi tiết health</summary><pre>${esc(JSON.stringify(x,null,2))}</pre></details></div>`
}
function integrationField(integrationId,field){
  const id=`int-${integrationId}-${field.name}`,label=esc(field.label||field.name);
  if(field.type==='boolean')return `<label class="integration-toggle" for="${esc(id)}"><span>${label}</span><input id="${esc(id)}" data-field="${esc(field.name)}" type="checkbox" ${field.value?'checked':''}></label>`;
  if(field.type==='secret'){
    const status=field.configured?`<span class="badge ok">đã cấu hình · ${esc(field.source||'')}</span>`:'<span class="badge warn">chưa cấu hình</span>';
    return `<div class="field"><label for="${esc(id)}">${label} ${status}</label><input id="${esc(id)}" data-field="${esc(field.name)}" class="input mono" type="password" value="" autocomplete="new-password" placeholder="${field.configured?'Để trống để giữ secret hiện tại':'Nhập secret'}"><div class="field-hint">Secret lưu trong /data/secrets và không được trả ngược qua API.</div></div>`
  }
  const type=field.type==='integer'?'number':'text',extra=field.type==='integer'?` min="${esc(field.min??1)}" max="${esc(field.max??65535)}"`:'';
  return `<div class="field"><label for="${esc(id)}">${label}</label><input id="${esc(id)}" data-field="${esc(field.name)}" class="input${field.type==='url'?' mono':''}" type="${type}" value="${esc(field.value??'')}" placeholder="${esc(field.placeholder||'')}"${extra}></div>`
}
function integrationSummary(item,enabled,custom=false){
  return `<summary class="integration-summary"><div class="integration-summary-main"><span class="integration-icon">${esc(item.icon||'🔌')}</span><div class="integration-summary-copy"><div class="integration-summary-title">${esc(item.name)}</div><div class="integration-summary-description">${esc(item.description||'')}</div>${custom?`<div class="integration-summary-meta mono">${esc(item.id)} · Custom HTTP</div>`:''}</div></div><div class="integration-summary-side"><span class="badge ${enabled?'ok':'warn'}">${enabled?'enabled':'disabled'}</span><span class="integration-chevron" aria-hidden="true">⌄</span></div></summary>`
}
function integrationEditor(item){
  const enabled=item.fields.find(f=>f.name==='enabled')?.value!==false;
  return `<details class="card integration-editor">${integrationSummary(item,enabled,false)}<form class="integration-editor-body" data-integration-form="${esc(item.id)}"><div class="integration-fields">${item.fields.map(f=>integrationField(item.id,f)).join('')}</div><div class="integration-editor-footer"><span class="small-text muted">Nguồn: <span class="mono">${esc(item.source||'')}</span></span><div class="row"><button class="btn small" data-action="integration-reset" data-id="${esc(item.id)}" type="button">Khôi phục stack/default</button><button class="btn primary small" type="submit">Lưu & áp dụng</button></div></div></form></details>`
}
function customIntegrationEditor(item){
  const sid=`custom-${item.id}`;
  const configured=item.secret_configured?'<span class="badge ok">đã cấu hình</span>':'<span class="badge warn">chưa cấu hình</span>';
  return `<details class="card integration-editor integration-editor-custom">${integrationSummary(item,item.enabled!==false,true)}<form class="integration-editor-body" data-custom-integration-form="${esc(item.id)}"><div class="integration-fields">
    <label class="integration-toggle" for="${esc(sid)}-enabled"><span>Bật integration</span><input id="${esc(sid)}-enabled" data-custom-field="enabled" type="checkbox" ${item.enabled?'checked':''}></label>
    <div class="field"><label for="${esc(sid)}-name">Tên hiển thị</label><input id="${esc(sid)}-name" data-custom-field="name" class="input" value="${esc(item.name)}" maxlength="120"></div>
    <div class="field"><label for="${esc(sid)}-icon">Icon / emoji</label><input id="${esc(sid)}-icon" data-custom-field="icon" class="input" value="${esc(item.icon||'🔌')}" maxlength="16"></div>
    <div class="field"><label>Integration ID</label><input class="input mono" value="${esc(item.id)}" disabled><div class="field-hint">ID cố định sau khi tạo.</div></div>
    <div class="field"><label for="${esc(sid)}-url">Base URL</label><input id="${esc(sid)}-url" data-custom-field="base_url" class="input mono" value="${esc(item.base_url)}" placeholder="http://127.0.0.1:9000"></div>
    <div class="field"><label for="${esc(sid)}-health">Health path</label><input id="${esc(sid)}-health" data-custom-field="health_path" class="input mono" value="${esc(item.health_path||'/health')}" placeholder="/health"></div>
    <div class="field"><label for="${esc(sid)}-auth">Authentication</label><select id="${esc(sid)}-auth" data-custom-field="auth_type" class="select"><option value="none" ${item.auth_type==='none'?'selected':''}>Không dùng</option><option value="bearer" ${item.auth_type==='bearer'?'selected':''}>Bearer token</option><option value="header" ${item.auth_type==='header'?'selected':''}>API key qua HTTP header</option></select></div>
    <div class="field"><label for="${esc(sid)}-header">Tên API-key header</label><input id="${esc(sid)}-header" data-custom-field="auth_header" class="input mono" value="${esc(item.auth_header||'X-API-Key')}" placeholder="X-API-Key"><div class="field-hint">Chỉ dùng khi Authentication = API key header.</div></div>
    <div class="field"><label for="${esc(sid)}-secret">Credential ${configured}</label><input id="${esc(sid)}-secret" data-custom-field="secret" class="input mono" type="password" value="" autocomplete="new-password" placeholder="${item.secret_configured?'Để trống để giữ credential hiện tại':'Nhập token / API key'}"><div class="field-hint">Lưu riêng trong /data/secrets; API không trả secret về trình duyệt.</div></div>
    <label class="integration-toggle" for="${esc(sid)}-clear"><span>Xóa credential đang lưu</span><input id="${esc(sid)}-clear" data-custom-field="clear_secret" type="checkbox"></label>
    <div class="field integration-field-full"><label for="${esc(sid)}-description">Mô tả</label><textarea id="${esc(sid)}-description" data-custom-field="description" class="textarea" maxlength="600">${esc(item.description||'')}</textarea></div>
  </div><div class="integration-editor-footer"><span class="small-text muted">Nguồn: <span class="mono">web_admin</span></span><div class="row"><button class="btn bad small" data-action="integration-delete-custom" data-id="${esc(item.id)}" type="button">Xóa Integration</button><button class="btn primary small" type="submit">Lưu & áp dụng</button></div></div></form></details>`
}
function customIntegrationCreatePanel(){
  return `<details id="integrationAddPanel" class="card integration-add-panel"><summary class="integration-add-summary"><div><strong>➕ Thêm Integration mới</strong><div class="small-text muted mt-10">Tạo một Custom HTTP Integration để lưu cấu hình và theo dõi health trực tiếp từ Web Admin.</div></div><span class="integration-chevron" aria-hidden="true">⌄</span></summary><form class="integration-add-body" data-custom-integration-create><div class="integration-create-grid">
    <div class="field"><label>Tên Integration</label><input data-custom-field="name" class="input" required maxlength="120" placeholder="Ví dụ: Voice Server"></div>
    <div class="field"><label>ID <span class="muted">(có thể để trống)</span></label><input data-custom-field="id" class="input mono" maxlength="64" placeholder="voice-server"><div class="field-hint">Nếu để trống HassMind tự tạo ID từ tên.</div></div>
    <div class="field"><label>Icon / emoji</label><input data-custom-field="icon" class="input" value="🔌" maxlength="16"></div>
    <div class="field"><label>Base URL</label><input data-custom-field="base_url" class="input mono" required placeholder="http://127.0.0.1:9000"></div>
    <div class="field"><label>Health path</label><input data-custom-field="health_path" class="input mono" value="/health" placeholder="/health"></div>
    <div class="field"><label>Authentication</label><select data-custom-field="auth_type" class="select"><option value="none">Không dùng</option><option value="bearer">Bearer token</option><option value="header">API key qua HTTP header</option></select></div>
    <div class="field"><label>Tên API-key header</label><input data-custom-field="auth_header" class="input mono" value="X-API-Key" placeholder="X-API-Key"></div>
    <div class="field"><label>Credential / token</label><input data-custom-field="secret" class="input mono" type="password" autocomplete="new-password" placeholder="Có thể để trống nếu không cần auth"></div>
    <label class="integration-toggle"><span>Bật ngay sau khi tạo</span><input data-custom-field="enabled" type="checkbox" checked></label>
    <div class="field integration-field-full"><label>Mô tả</label><textarea data-custom-field="description" class="textarea" maxlength="600" placeholder="Integration này dùng để làm gì..."></textarea></div>
  </div><div class="integration-add-note">🔒 Custom Integration chỉ thực hiện health-check HTTP. HassMind không tự tạo quyền gọi API/Action cho AI; các action vẫn cần adapter typed riêng để giữ an toàn.</div><div class="row end mt-14"><button class="btn" data-action="integration-add-cancel" type="button">Đóng</button><button class="btn primary" type="submit">Tạo Integration</button></div></form></details>`
}
function customIntegrationPayload(form){
  const values={};
  form.querySelectorAll('[data-custom-field]').forEach(el=>{values[el.dataset.customField]=el.type==='checkbox'?el.checked:el.value});
  return values
}
async function saveIntegration(id,form){
  const values={};form.querySelectorAll('[data-field]').forEach(el=>{values[el.dataset.field]=el.type==='checkbox'?el.checked:el.value});
  const btn=form.querySelector('button[type="submit"]');if(btn)btn.disabled=true;
  try{await api('/api/integrations/config/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify({values})});toast('Đã lưu và áp dụng '+id);await loadIntegrations()}catch(e){toast(e.message,true)}finally{if(btn)btn.disabled=false}
}
async function resetIntegration(id){if(!confirm('Khôi phục '+id+' về cấu hình stack/default và xóa secret override trong Web Admin?'))return;try{await api('/api/integrations/config/'+encodeURIComponent(id),{method:'DELETE'});toast('Đã khôi phục '+id);await loadIntegrations()}catch(e){toast(e.message,true)}}
async function createCustomIntegration(form){
  const payload=customIntegrationPayload(form),btn=form.querySelector('button[type="submit"]');if(btn)btn.disabled=true;
  try{const j=await api('/api/integrations/custom',{method:'POST',body:JSON.stringify(payload)});toast('Đã thêm Integration '+(j.integration?.name||j.integration?.id||''));await loadIntegrations()}catch(e){toast(e.message,true)}finally{if(btn)btn.disabled=false}
}
async function saveCustomIntegration(id,form){
  const payload=customIntegrationPayload(form),btn=form.querySelector('button[type="submit"]');if(btn)btn.disabled=true;
  try{await api('/api/integrations/custom/'+encodeURIComponent(id),{method:'PUT',body:JSON.stringify(payload)});toast('Đã lưu và áp dụng '+id);await loadIntegrations()}catch(e){toast(e.message,true)}finally{if(btn)btn.disabled=false}
}
async function deleteCustomIntegration(id){if(!confirm('Xóa Integration '+id+'? Cấu hình và credential runtime của Integration này sẽ bị xóa.'))return;try{await api('/api/integrations/custom/'+encodeURIComponent(id),{method:'DELETE'});toast('Đã xóa Integration '+id);await loadIntegrations()}catch(e){toast(e.message,true)}}
async function openIntegrationAddPanel(){let panel=$('integrationAddPanel');if(!panel){await loadIntegrations();panel=$('integrationAddPanel')}if(!panel)return;panel.open=true;panel.scrollIntoView({behavior:'smooth',block:'start'});setTimeout(()=>panel.querySelector('[data-custom-field="name"]')?.focus(),250)}
async function loadIntegrations(){
  const box=$('integrationsBox');
  try{
    const [status,config]=await Promise.all([api('/api/integrations'),api('/api/integrations/config')]);
    const builtins=(config.integrations||[]).map(integrationEditor).join('');
    const customs=(config.custom_integrations||[]).map(customIntegrationEditor).join('');
    const customEmpty=(config.custom_integrations||[]).length?'':'<div class="integration-empty">Chưa có Custom Integration. Nhấn <strong>Thêm Integration</strong> để tạo mới.</div>';
    const cards=[];
    Object.entries(status.companion_containers||{}).forEach(([k,v])=>cards.push(integrationCard(k,v)));
    Object.entries(status.home_assistant_custom_components||{}).forEach(([k,v])=>{if(typeof v==='object')cards.push(integrationCard('HA · '+k,v))});
    box.innerHTML=`<div class="span-12 integrations-layout">
      <div class="integration-section-title"><div><h2>⚙️ Danh sách Integrations</h2><p>Cấu hình mặc định được thu gọn. Nhấn vào từng Integration để mở phần thiết lập.</p></div><span class="badge info">${(config.integrations||[]).length+(config.custom_integrations||[]).length} integrations</span></div>
      ${customIntegrationCreatePanel()}
      <div class="integration-subsection"><div class="integration-subhead"><h3>HassMind adapters</h3><span class="small-text muted">Adapter typed tích hợp sẵn</span></div><div class="integration-editor-grid">${builtins}</div></div>
      <div class="integration-subsection"><div class="integration-subhead"><h3>Custom Integrations</h3><span class="small-text muted">Bạn tự thêm từ Web Admin</span></div>${customEmpty}<div class="integration-editor-grid">${customs}</div></div>
      <div class="integration-section-title integration-status-heading"><div><h2>🩺 Trạng thái kết nối</h2><p>Health/status thực tế của adapter và Home Assistant custom component.</p></div></div>
      <div class="integration-status-grid">${cards.join('')}</div>
      <details class="card integration-policy"><summary>🛡️ Effective policy</summary><pre>${esc(JSON.stringify(status.policy,null,2))}</pre></details>
    </div>`
  }catch(e){box.innerHTML=`<div class="card card-pad span-12">${errorHtml(e)}</div>`}
}

function logRow(row,index){const rid=row.request_id||'',sid=row.session_id||'';return `<tr class="log-row" data-log-index="${index}"><td class="mono">${esc(fmtTime(row.ts))}</td><td><span class="lvl ${esc(row.level)}">${esc(row.level)}</span></td><td>${esc(row.component||row.logger||'')}</td><td class="mono">${esc(row.event||'')}</td><td class="log-msg" title="${esc(row.message||'')}">${esc(row.message||'')}</td><td class="mono">${esc(rid||sid||'—')}</td></tr><tr id="logDetail${index}" class="log-detail" hidden><td colspan="6"><pre>${esc(JSON.stringify(row,null,2))}</pre></td></tr>`}
function toggleLogDetail(index){const el=$('logDetail'+index);if(el)el.hidden=!el.hidden}
async function loadLogs(){const qs=new URLSearchParams({limit:$('logLimit').value});if($('logLevel').value)qs.set('level',$('logLevel').value);if($('logComponent').value.trim())qs.set('component',$('logComponent').value.trim());if($('logQuery').value.trim())qs.set('q',$('logQuery').value.trim());try{const rows=await api('/api/logs?'+qs.toString());$('logCount').textContent=rows.length+' dòng';$('logsBody').innerHTML=rows.map(logRow).join('')||'<tr><td colspan="6" class="empty">Không có log phù hợp.</td></tr>'}catch(e){$('logsBody').innerHTML=`<tr><td colspan="6">${errorHtml(e)}</td></tr>`}}
async function exportLogs(){const qs=new URLSearchParams({limit:'2000'});if($('logLevel').value)qs.set('level',$('logLevel').value);if($('logComponent').value.trim())qs.set('component',$('logComponent').value.trim());if($('logQuery').value.trim())qs.set('q',$('logQuery').value.trim());try{const r=await fetch('/api/logs/export?'+qs.toString(),{credentials:'same-origin'});if(r.status===401){location.replace('/login');return}if(!r.ok)throw new Error(await r.text());const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`hassmind-logs-${APP_VERSION}.ndjson`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}catch(e){toast('Không thể export log: '+e.message,true)}}
async function loadAudit(){const box=$('auditBox');try{const rows=await api('/api/audit?limit=200');box.innerHTML=rows.map(x=>`<details><summary><span class="mono">#${x.id}</span> · ${esc(x.tool_name)} ${x.error?'<span class="badge bad">error</span>':'<span class="badge ok">ok</span>'}</summary><pre>${esc(JSON.stringify(x,null,2))}</pre></details>`).join('')||'<div class="empty">Chưa có tool audit.</div>'}catch(e){box.innerHTML=errorHtml(e)}}
async function loadEvents(){try{$('eventsBox').textContent=JSON.stringify(await api('/api/events?limit=120'),null,2)}catch(e){$('eventsBox').textContent='ERROR: '+e.message+(e.requestId?'\nRequest ID: '+e.requestId:'')}}
async function loadApprovals(){const box=$('approvalsBox');try{const rows=await api('/api/approvals');box.innerHTML=rows.map(x=>`<div class="item"><div class="item-head"><strong>${esc(x.id)}</strong><span class="badge ${x.status==='applied'||x.status==='approved'?'ok':x.status==='pending'?'warn':'bad'}">${esc(x.status)}</span><span class="muted small-text">${esc(x.kind)} · ${esc(x.target_id)} · risk=${esc(x.risk)}</span></div><p>${esc(x.reason||'')}</p><pre>${esc(x.diff||'')}</pre>${x.status==='pending'?`<div class="row end mt-10"><button class="btn good small" data-action="approval-approve" data-id="${esc(x.id)}" type="button">Duyệt + apply</button><button class="btn bad small" data-action="approval-reject" data-id="${esc(x.id)}" type="button">Từ chối</button></div>`:''}${x.error?`<div class="error-text small-text mt-10">${esc(x.error)}</div>`:''}</div>`).join('')||'<div class="empty">Chưa có proposal.</div>'}catch(e){box.innerHTML=errorHtml(e)}}
async function decideApproval(id,approve){try{await api('/api/approvals/'+encodeURIComponent(id)+'/decision',{method:'POST',body:JSON.stringify({approve})});toast(approve?'Đã duyệt':'Đã từ chối');loadApprovals()}catch(e){toast(e.message,true)}}

async function loadJobs(){const box=$('jobsBox');try{const rows=await api('/api/jobs');box.innerHTML=rows.map(x=>`<div class="item"><div class="item-head"><strong>#${x.id} · ${esc(x.name)}</strong><span class="badge ${x.enabled?'ok':'warn'}">${x.enabled?'enabled':'disabled'}</span><span class="muted small-text">${esc(x.schedule_type)} ${esc(x.schedule_value)}</span><button class="btn small" data-action="job-toggle" data-id="${x.id}" data-enabled="${x.enabled?'0':'1'}" type="button">${x.enabled?'Tắt':'Bật'}</button><button class="btn bad small" data-action="job-delete" data-id="${x.id}" type="button">Xóa</button></div><p>${esc(x.prompt||'')}</p><div class="small-text muted mono">next=${esc(x.next_run||'—')} · last=${esc(x.last_run||'—')}</div>${x.last_result?`<details class="mt-10"><summary>Kết quả gần nhất</summary><pre>${esc(x.last_result)}</pre></details>`:''}</div>`).join('')||'<div class="empty">Chưa có job.</div>'}catch(e){box.innerHTML=errorHtml(e)}}
async function createJob(){const b={name:$('jobname').value.trim(),prompt:$('jobprompt').value.trim(),schedule_type:$('jobtype').value,schedule_value:$('jobvalue').value.trim(),notify:true};try{await api('/api/jobs',{method:'POST',body:JSON.stringify(b)});toast('Đã tạo job ở trạng thái disabled');$('jobForm').reset();loadJobs()}catch(e){toast(e.message,true)}}
async function toggleJob(id,enabled){try{await api('/api/jobs/'+id,{method:'PATCH',body:JSON.stringify({enabled})});loadJobs()}catch(e){toast(e.message,true)}}
async function deleteJob(id){if(!confirm('Xóa job này?'))return;try{await api('/api/jobs/'+id,{method:'DELETE'});loadJobs()}catch(e){toast(e.message,true)}}

async function loadRules(){const box=$('rulesBox');try{const rows=await api('/api/event-rules');box.innerHTML=rows.map(x=>`<div class="item"><div class="item-head"><strong>#${x.id} · ${esc(x.name)}</strong><span class="badge ${x.enabled?'ok':'warn'}">${x.enabled?'enabled':'disabled'}</span><span class="muted small-text mono">${esc(x.entity_id)} → ${esc(x.to_state||'*')}</span><button class="btn small" data-action="rule-toggle" data-id="${x.id}" data-enabled="${x.enabled?'0':'1'}" type="button">${x.enabled?'Tắt':'Bật'}</button><button class="btn bad small" data-action="rule-delete" data-id="${x.id}" type="button">Xóa</button></div><p>${esc(x.prompt||'')}</p><div class="small-text muted">cooldown=${x.cooldown_seconds}s · last=${esc(x.last_triggered||'—')}</div></div>`).join('')||'<div class="empty">Chưa có rule.</div>'}catch(e){box.innerHTML=errorHtml(e)}}
async function createRule(){const b={name:$('rulename').value.trim(),entity_id:$('ruleentity').value.trim(),to_state:$('rulestate').value.trim()||null,prompt:$('ruleprompt').value.trim(),cooldown_seconds:Number($('rulecooldown').value||300),notify:true};try{await api('/api/event-rules',{method:'POST',body:JSON.stringify(b)});toast('Đã tạo rule ở trạng thái disabled');$('ruleForm').reset();$('rulecooldown').value='300';loadRules()}catch(e){toast(e.message,true)}}
async function toggleRule(id,enabled){try{await api('/api/event-rules/'+id,{method:'PATCH',body:JSON.stringify({enabled})});loadRules()}catch(e){toast(e.message,true)}}
async function deleteRule(id){if(!confirm('Xóa event rule này?'))return;try{await api('/api/event-rules/'+id,{method:'DELETE'});loadRules()}catch(e){toast(e.message,true)}}
async function reindexKnowledge(){try{const j=await api('/api/knowledge/reindex',{method:'POST',body:'{}'});$('knowledgeBox').textContent=JSON.stringify(j,null,2);toast('Re-index hoàn tất')}catch(e){$('knowledgeBox').textContent='ERROR: '+e.message;toast(e.message,true)}}
async function searchKnowledge(){const q=$('knowledgeQuery').value.trim();if(!q)return;try{$('knowledgeBox').textContent=JSON.stringify(await api('/api/knowledge/search?q='+encodeURIComponent(q)),null,2)}catch(e){$('knowledgeBox').textContent='ERROR: '+e.message}}

function kvRows(entries){return entries.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}
async function loadSessions(){const box=$('sessionsBox');try{const rows=await api('/api/auth/sessions');box.innerHTML=rows.map(x=>`<div class="item"><div class="item-head"><strong>${x.current?'Phiên hiện tại':'Phiên khác'}</strong><span class="badge ${x.current?'ok':'info'}">${x.current?'current':'active'}</span></div><div class="small-text muted mt-10">IP: ${esc(x.ip||'—')}</div><div class="small-text muted">Last seen: ${esc(fmtTime(x.last_seen_at))}</div><div class="small-text muted">Expires: ${esc(fmtTime(x.expires_at))}</div><div class="small-text muted">${esc(x.user_agent||'')}</div></div>`).join('')||'<div class="empty">Không có phiên.</div>'}catch(e){box.innerHTML=errorHtml(e)}}
async function loadAuthAudit(){const box=$('authAuditBox');try{const rows=await api('/api/auth/audit?limit=50');box.innerHTML=rows.map(x=>`<div class="item"><div class="item-head"><strong>${esc(x.event)}</strong><span class="badge ${x.success?'ok':'bad'}">${x.success?'success':'failed'}</span></div><div class="small-text muted mt-10">${esc(fmtTime(x.created_at))} · user=${esc(x.username||'—')} · IP=${esc(x.ip||'—')}</div>${x.details?`<div class="small-text muted">${esc(x.details)}</div>`:''}</div>`).join('')||'<div class="empty">Chưa có sự kiện bảo mật.</div>'}catch(e){box.innerHTML=errorHtml(e)}}
function secretSourceLabel(source){return ({runtime_file:'Runtime file',docker_secret:'Docker secret (bootstrap)',environment:'Environment (bootstrap)',missing:'Missing'})[source]||source||'—'}
async function loadSettings(){try{const s=await api('/api/settings/security');$('apiTokenBadge').className='badge '+(s.api_token.configured?'ok':'bad');$('apiTokenBadge').textContent=s.api_token.configured?'Configured':'Missing';$('apiTokenInfo').innerHTML=kvRows([['Nguồn',secretSourceLabel(s.api_token.source)],['Fingerprint',s.api_token.fingerprint||'—'],['Trạng thái',s.api_token.configured?'Đã cấu hình':'Chưa cấu hình']]);$('adminInfo').innerHTML=kvRows([['Username',s.admin.username],['Recovery',s.admin.recovery_enabled?'Đã cấu hình':'Chưa cấu hình'],['Session TTL',s.admin.session_ttl_minutes+' phút'],['Idle timeout',s.admin.session_idle_minutes+' phút'],['Password min',s.admin.password_min_length+' ký tự'],['Password storage',s.admin.password_storage==='argon2id_hash_only'?'Argon2id hash only':s.admin.password_storage||'—']]);uiState.passwordMinLength=Number(s.admin.password_min_length||14);$('newAdminPassword').minLength=uiState.passwordMinLength;$('confirmAdminPassword').minLength=uiState.passwordMinLength;const policyHint=$('passwordPolicyHint');if(policyHint)policyHint.textContent=`Tối thiểu ${uiState.passwordMinLength} ký tự. Nếu dưới 20 ký tự phải có ít nhất 3 nhóm: chữ thường, chữ hoa, số, ký tự đặc biệt. Mật khẩu không được chứa username. Đổi mật khẩu sẽ thu hồi các phiên khác.`;$('recoveryBadge').className='badge '+(s.admin.recovery_enabled?'ok':'bad');$('recoveryBadge').textContent=s.admin.recovery_enabled?'Configured':'Missing';$('recoveryInfo').innerHTML=kvRows([['Trạng thái',s.admin.recovery_enabled?'Đã cấu hình':'Chưa cấu hình'],['Nguồn',secretSourceLabel(s.admin.recovery_source)],['Runtime file',s.admin.recovery_runtime_file||'/data/secrets/admin_recovery_key'],['Cách dùng','Trang Login → Quên mật khẩu?']]);$('newUsername').value=s.admin.username;$('securityInfo').innerHTML=kvRows([['Cookie Secure',String(s.admin.cookie_secure)],['Allowed networks',s.admin.allowed_networks.join(', ')||'Không giới hạn'],['Log secret redaction',String(s.logging.secret_redaction)],['Log content',String(s.logging.content_logging)],['Scrub old logs',String(s.logging.scrub_existing_logs_on_start)],['Scrub old audit',String(s.logging.scrub_existing_audit_on_start)],['Log file',s.logging.file]]);const w=$('cookieWarning');if(!s.admin.cookie_secure){w.classList.remove('hidden');w.textContent='Bạn đang dùng ADMIN_COOKIE_SECURE=false để hỗ trợ HTTP LAN. Khi chuyển sang HTTPS/reverse proxy, hãy bật true để cookie chỉ truyền qua TLS.'}else{w.classList.add('hidden')}await Promise.all([loadSessions(),loadAuthAudit()])}catch(e){toast('Không tải được Settings: '+e.message,true)}}
async function saveApiToken(generate=false){const current=$('tokenCurrentPassword').value;const token=$('newApiToken').value.trim();if(!current){toast('Nhập mật khẩu admin hiện tại.',true);return}if(!generate&&token.length<32){toast('API token phải có ít nhất 32 ký tự.',true);return}try{const j=await api('/api/settings/api-token',{method:'POST',body:JSON.stringify({current_password:current,token,generate})});$('tokenCurrentPassword').value='';$('newApiToken').value='';if(j.token){$('generatedTokenBox').classList.remove('hidden');$('generatedToken').value=j.token}else{$('generatedTokenBox').classList.add('hidden');$('generatedToken').value=''}toast('Đã cập nhật HassMind API token');loadSettings()}catch(e){toast(e.message,true)}}
async function rotateRecoveryKey(){const current=$('recoveryCurrentPassword').value;if(!current){toast('Nhập mật khẩu admin hiện tại.',true);return}if(!confirm('Tạo Recovery Key mới? Recovery Key hiện tại sẽ không còn dùng được.'))return;try{const j=await api('/api/settings/recovery-key',{method:'POST',body:JSON.stringify({current_password:current})});$('recoveryCurrentPassword').value='';$('generatedRecoveryKey').value=j.recovery_key||'';$('generatedRecoveryBox').classList.remove('hidden');toast('Đã tạo Recovery Key mới. Hãy lưu ngay ở nơi an toàn.');loadSettings()}catch(e){toast(e.message,true)}}
async function changeUsernameSubmit(){try{const j=await api('/api/auth/change-username',{method:'POST',body:JSON.stringify({current_password:$('usernamePassword').value,new_username:$('newUsername').value.trim()})});$('usernamePassword').value='';uiState.user.username=j.username;$('currentUser').textContent=j.username;$('userAvatar').textContent=j.username.slice(0,1).toUpperCase();toast('Đã đổi tên đăng nhập');loadSettings()}catch(e){toast(e.message,true)}}
async function changePasswordSubmit(){const current=$('currentPassword').value,n=$('newAdminPassword').value,c=$('confirmAdminPassword').value;if(!current){toast('Nhập mật khẩu hiện tại.',true);return}if(n.length<uiState.passwordMinLength){toast(`Mật khẩu mới phải có ít nhất ${uiState.passwordMinLength} ký tự.`,true);return}if(n!==c){toast('Hai mật khẩu mới không khớp.',true);return}try{await api('/api/auth/change-password',{method:'POST',body:JSON.stringify({current_password:current,new_password:n})});$('passwordForm').reset();toast('Đã đổi mật khẩu và thu hồi các phiên khác');loadSessions();loadAuthAudit()}catch(e){toast(e.message,true)}}
async function revokeOtherSessions(){if(!confirm('Đăng xuất tất cả phiên khác?'))return;try{const j=await api('/api/auth/sessions/revoke-others',{method:'POST',body:'{}'});toast(`Đã thu hồi ${j.revoked} phiên`);loadSessions()}catch(e){toast(e.message,true)}}

function clearOneTimeSecrets(){const token=$('generatedToken'),recovery=$('generatedRecoveryKey');if(token)token.value='';if(recovery)recovery.value='';$('generatedTokenBox')?.classList.add('hidden');$('generatedRecoveryBox')?.classList.add('hidden');$('tokenCurrentPassword').value='';$('newApiToken').value='';$('recoveryCurrentPassword').value=''}
function setTab(id){if(uiState.activeTab==='settings'&&id!=='settings')clearOneTimeSecrets();uiState.activeTab=id;document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('.nav-btn').forEach(x=>x.classList.toggle('active',x.dataset.tab===id));const loaders={overview:loadOverview,integrations:loadIntegrations,logs:loadLogs,audit:loadAudit,events:loadEvents,approvals:loadApprovals,jobs:loadJobs,rules:loadRules,settings:loadSettings};if(loaders[id])loaders[id]()}
function bindEvents(){
  document.querySelectorAll('.nav-btn').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
  $('logoutBtn').addEventListener('click',logout);$('sendBtn').addEventListener('click',sendChat);$('chatinput').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();sendChat()}});
  ['logLevel','logLimit'].forEach(id=>$(id).addEventListener('change',loadLogs));['logComponent','logQuery'].forEach(id=>$(id).addEventListener('keydown',e=>{if(e.key==='Enter')loadLogs()}));
  $('jobForm').addEventListener('submit',e=>{e.preventDefault();createJob()});$('ruleForm').addEventListener('submit',e=>{e.preventDefault();createRule()});
  $('tokenForm').addEventListener('submit',e=>{e.preventDefault();saveApiToken(false)});$('generateTokenBtn').addEventListener('click',()=>saveApiToken(true));$('copyGeneratedToken').addEventListener('click',async()=>{const el=$('generatedToken');try{await copyTextSafe(el.value,el);toast('Đã sao chép token')}catch(err){toast(err.message||'Không thể sao chép tự động.',true)}});
  $('recoveryForm').addEventListener('submit',e=>{e.preventDefault();rotateRecoveryKey()});$('copyGeneratedRecoveryKey').addEventListener('click',async()=>{const el=$('generatedRecoveryKey');try{await copyTextSafe(el.value,el);toast('Đã sao chép Recovery Key')}catch(err){toast(err.message||'Không thể sao chép tự động.',true)}});
  $('usernameForm').addEventListener('submit',e=>{e.preventDefault();changeUsernameSubmit()});$('passwordForm').addEventListener('submit',e=>{e.preventDefault();changePasswordSubmit()});
  document.addEventListener('submit',e=>{
    const createForm=e.target.closest('[data-custom-integration-create]');if(createForm){e.preventDefault();createCustomIntegration(createForm);return}
    const customForm=e.target.closest('[data-custom-integration-form]');if(customForm){e.preventDefault();saveCustomIntegration(customForm.dataset.customIntegrationForm,customForm);return}
    const form=e.target.closest('[data-integration-form]');if(!form)return;e.preventDefault();saveIntegration(form.dataset.integrationForm,form)
  });
  document.addEventListener('click',e=>{const log=e.target.closest('.log-row');if(log){toggleLogDetail(log.dataset.logIndex);return}const b=e.target.closest('[data-action]');if(!b)return;const a=b.dataset.action,id=b.dataset.id;const actions={'overview-refresh':loadOverview,'new-session':newSession,'integrations-refresh':loadIntegrations,'integration-add':openIntegrationAddPanel,'logs-refresh':loadLogs,'logs-export':exportLogs,'audit-refresh':loadAudit,'events-refresh':loadEvents,'approvals-refresh':loadApprovals,'jobs-refresh':loadJobs,'rules-refresh':loadRules,'knowledge-reindex':reindexKnowledge,'knowledge-search':searchKnowledge,'settings-refresh':loadSettings,'sessions-refresh':loadSessions,'sessions-revoke-others':revokeOtherSessions,'auth-audit-refresh':loadAuthAudit};if(actions[a]){actions[a]();return}if(a==='approval-approve')decideApproval(id,true);if(a==='approval-reject')decideApproval(id,false);if(a==='job-toggle')toggleJob(Number(id),b.dataset.enabled==='1');if(a==='job-delete')deleteJob(Number(id));if(a==='rule-toggle')toggleRule(Number(id),b.dataset.enabled==='1');if(a==='rule-delete')deleteRule(Number(id));if(a==='integration-reset')resetIntegration(id);if(a==='integration-delete-custom')deleteCustomIntegration(id);if(a==='integration-add-cancel'){const panel=$('integrationAddPanel');if(panel)panel.open=false}});
}
async function start(){const ok=await initAuth();if(!ok)return;bindEvents();health();loadOverview();setInterval(health,30000);setInterval(()=>{if(uiState.activeTab==='logs'&&$('logAuto').checked)loadLogs()},5000)}
start().catch(e=>{toast(e.message||String(e),true);reportClientError('startup_error',e.message||String(e),e.stack||'')});
