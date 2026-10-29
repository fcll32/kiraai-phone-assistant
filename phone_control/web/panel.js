const $=id=>document.getElementById(id); let loading=false;
const tabs=Array.from(document.querySelectorAll('[data-tab]'));

const scenes={
  settings:{image:'scene-settings.png',title:'把连接准备好',note:'认真接好每一步。'},
  pairing:{image:'scene-pairing.png',title:'接下来交给手机',note:'地址、密码、校验码，整行复制。'},
  guide:{image:'scene-guide.png',title:'一步一步，慢慢来',note:'按步骤完成，随时可以停止。'}
};
function updateScene(name){
  const scene=scenes[name];if(!scene)return;
  const image=$('scene-image');const source='assets/'+scene.image;
  if(image.getAttribute('src')!==source)image.src=source;
  $('scene-title').textContent=scene.title;$('scene-note').textContent=scene.note;
}
function updateCompanion(data){
  // Read-only presentation of the confirmed server snapshot, never a feature switch.
  const sticker=data.connected===true?'connected.png':data.error?'error.png':data.ready===true?'link.png':'rest.png';
  const source='assets/'+sticker;
  if($('status-art').getAttribute('src')!==source)$('status-art').src=source;
}

function hidePassword(){$('password').type='password';$('show-password').textContent='显示密码'}
function activateTab(name,focus=false){const target=tabs.find(tab=>tab.dataset.tab===name);if(!target)return;for(const tab of tabs){const selected=tab===target;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;$('panel-'+tab.dataset.tab).hidden=!selected}if(name!=='pairing')hidePassword();updateScene(name);if(focus)target.focus()}
for(const tab of tabs){tab.onclick=()=>activateTab(tab.dataset.tab);tab.addEventListener('keydown',event=>{const index=tabs.indexOf(tab);let next;if(event.key==='ArrowRight')next=(index+1)%tabs.length;else if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=tabs.length-1;else return;event.preventDefault();activateTab(tabs[next].dataset.tab,true)})}
for(const button of document.querySelectorAll('[data-open-tab]'))button.onclick=()=>activateTab(button.dataset.openTab,true);
async function api(path,options={}){const response=await fetch('/api/plugin/phone_control/'+path,{credentials:'same-origin',cache:'no-store',...options});let data;try{data=await response.json()}catch{throw new Error('无法读取插件信息，请重新登录 KiraAI 后重试')}if(!response.ok)throw new Error(response.status===401?'请重新登录 KiraAI 后打开此页':(typeof data.detail==='string'?data.detail:'操作失败，请稍后重试'));updateCompanion(data);return data}
function message(text,error=false){$('message').textContent=text;$('message').dataset.kind=error?'error':'info'}
async function load(fill=false){const data=await api('setup');if(fill){$('voice-enabled').checked=data.voice_enabled===true;$('shared-entry').checked=data.shared_entry===true;$('listen-port').value=data.listen_port||8443;$('public-ip').value=data.public_ip||'';$('port').value=data.port||5267;$('sessions').value=(data.allowed_sessions||[]).join('\n')}$('state').textContent=data.connected?'手机已连接':data.ready?'等待手机连接':data.listener_enabled?'启动失败':'服务未启动';$('state-badge').dataset.state=data.connected?'connected':data.error?'error':'idle';$('network').textContent=data.shared_entry?`共用入口：放行 TCP ${data.port||5267}，Docker 映射 ${data.port||5267} → ${data.listen_port||8443}。管理网页使用 HTTPS；手机地址复制“手机配对”页的内容。`:`独立连接：放行 TCP ${data.port||8443}，Docker 映射到容器 ${data.listen_port||8443}。`;$('pairing').hidden=!data.ready;$('not-ready-box').hidden=data.ready;$('not-ready').textContent=data.error||(!data.builtin_server?'你正在使用原来的服务器连接。若已连接成功，可以继续使用；切换到内置服务时再保存服务器设置。':'填写并保存设置后，点“保存并启动”，连接信息会显示在这里。');for(const key of ['address','password','fingerprint'])$(key).value=data.ready?data[key]:'';$('expires').textContent=data.ready?`服务器凭证有效期至 ${data.expires}。更换 IP 或凭证更新后，请重新复制校验码。`:'';$('apk').hidden=!data.apk_available;$('apk-note').textContent=data.apk_available?'如果在电脑上下载，把文件发到自己的手机后安装即可。':'插件 ZIP 不含 APK。首次使用请单独下载本项目正式发布的手机 APK；装好后，可在 App 的“应用更新”里下载新版。';updateCompanion(data);return data}
async function submit(action){
  if(loading)return;
  loading=true;for(const id of ['save','start','stop','refresh'])$(id).disabled=true;
  message(action==='stop'?'正在停止…':'正在保存…');
  try{
    const payload=action==='stop'?{action}:{action,voice_enabled:$('voice-enabled').checked,shared_entry:$('shared-entry').checked,listen_port:Number($('listen-port').value),public_ip:$('public-ip').value.trim(),port:Number($('port').value),password:$('new-password').value,allowed_sessions:$('sessions').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean)};
    await api('setup',{method:'POST',headers:{'Content-Type':'application/json','X-Phone-Setup':'1'},body:JSON.stringify(payload)});
    $('new-password').value='';const data=await load(true);
    message(data.error||(data.ready?'✓ 已保存并启动。切换到“手机配对”复制三项到手机；重启会自动恢复。':action==='stop'?'✓ 手机服务已停止。共用管理入口仍可使用；重启后不会自动开启手机服务。':'✓ 已保存，尚未监听端口。准备好后点击“保存并启动”。'),!!data.error);
  }catch(error){message(error.message,true)}finally{loading=false;for(const id of ['save','start','stop','refresh'])$(id).disabled=false}
}
$('setup-form').addEventListener('submit',event=>{event.preventDefault();submit(event.submitter?.id==='start'?'start':'save')});
$('stop').onclick=()=>submit('stop');
$('refresh').onclick=()=>{if(loading)return;$('refresh').disabled=true;load(false).then(data=>message(data.error||'状态已更新',!!data.error)).catch(error=>message(error.message,true)).finally(()=>{$('refresh').disabled=loading})};
$('show-password').onclick=()=>{const visible=$('password').type==='password';$('password').type=visible?'text':'password';$('show-password').textContent=visible?'隐藏密码':'显示密码'};
for(const button of document.querySelectorAll('[data-copy]'))button.onclick=async()=>{const field=$(button.dataset.copy);try{if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(field.value);else{const temporary=document.createElement('textarea');temporary.value=field.value;temporary.style.position='fixed';temporary.style.top='-9999px';document.body.appendChild(temporary);temporary.select();let copied;try{copied=document.execCommand('copy')}finally{temporary.remove()}if(!copied)throw new Error('copy')}message('已复制')}catch{field.focus();field.select();message('浏览器未允许自动复制，请手动选中并复制；密码可先点击“显示密码”。',true)}};
load(true).catch(error=>message(error.message,true));
