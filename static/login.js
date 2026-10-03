'use strict';
const $=id=>document.getElementById(id);
function message(id,text,bad=true){const el=$(id);el.textContent=text;el.className='message '+(bad?'bad':'good');}
function clearMessage(id){const el=$(id);el.textContent='';el.className='message hidden';}
async function post(path,body){
  const r=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const text=await r.text();let data;try{data=JSON.parse(text)}catch{data={detail:text}}
  if(!r.ok)throw new Error(data.detail||data.message||'Yêu cầu thất bại');return data;
}
$('loginForm').addEventListener('submit',async e=>{
  e.preventDefault();clearMessage('loginMessage');$('loginBtn').disabled=true;
  try{await post('/api/auth/login',{username:$('username').value.trim(),password:$('password').value});location.replace('/');}
  catch(err){message('loginMessage',err.message,true)}finally{$('loginBtn').disabled=false;}
});
$('showReset').addEventListener('click',()=>{$('loginCard').classList.add('hidden');$('resetCard').classList.remove('hidden');clearMessage('resetMessage');});
$('backLogin').addEventListener('click',()=>{$('resetCard').classList.add('hidden');$('loginCard').classList.remove('hidden');clearMessage('loginMessage');});
$('resetForm').addEventListener('submit',async e=>{
  e.preventDefault();clearMessage('resetMessage');
  if($('newPassword').value!==$('confirmPassword').value){message('resetMessage','Hai mật khẩu mới không khớp.',true);return;}
  $('resetBtn').disabled=true;
  try{await post('/api/auth/reset-password',{username:$('resetUsername').value.trim(),recovery_key:$('recoveryKey').value,new_password:$('newPassword').value});message('resetMessage','Đã đặt lại mật khẩu. Bạn có thể quay lại đăng nhập.',false);$('recoveryKey').value='';$('newPassword').value='';$('confirmPassword').value='';}
  catch(err){message('resetMessage',err.message,true)}finally{$('resetBtn').disabled=false;}
});
