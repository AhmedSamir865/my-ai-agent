(()=>{
 const body=document.body;
 window.mobileNavigate=(view)=>{
  body.classList.remove('body-chat','body-tasks','body-work','body-preview','body-settings');
  body.classList.add('body-'+view);
  document.querySelectorAll('.mobile-tab').forEach(b=>b.classList.toggle('active',b.dataset.view===view));
  if(view==='work'){document.querySelector('[data-pane="editor"]')?.click();loadFiles()}
  if(view==='preview')document.querySelector('[data-pane="preview"]')?.click();
  if(view==='settings')loadSettings();
  if(view==='tasks')document.getElementById('messages')?.scrollTo({top:0,behavior:'smooth'});
 };
 document.querySelectorAll('.mobile-tab').forEach(b=>b.addEventListener('click',()=>mobileNavigate(b.dataset.view)));
 async function ensureLogin(){
  try{
   const s=await fetch('/api/status').then(r=>r.json());if(!s.auth_required||s.authenticated)return true;
   const cached=sessionStorage.getItem('agent-login-attempted');if(cached==='yes')return false;
   const password=prompt('هذه نسخة محمية. أدخل كلمة مرور المشرف للمتابعة:');if(!password)return false;
   const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});
   if(!r.ok){alert('تعذر تسجيل الدخول. تحقق من كلمة المرور.');return false}
   sessionStorage.setItem('agent-login-attempted','yes');return true;
  }catch{return true}
 }
 async function loadSettings(){
  if(!await ensureLogin())return;
  const status=document.getElementById('settings-status');
  try{const r=await fetch('/api/settings');if(!r.ok)throw Error((await r.json()).detail||'تعذر تحميل الإعدادات');const x=await r.json();
   document.getElementById('max-retries').value=x.max_retries;
   status.textContent=`مهيأ: Gemini ${x.configured.gemini?'✓':'—'} · Groq ${x.configured.groq?'✓':'—'} · OpenRouter ${x.configured.openrouter?'✓':'—'} · Vercel ${x.configured.vercel?'✓':'—'}. لا تُعرض المفاتيح المحفوظة.`;
  }catch(e){status.textContent=e.message}
 }
 window.saveSettings=async()=>{
  if(!await ensureLogin())return;
  const payload={gemini_api_key:document.getElementById('setting-gemini').value,groq_api_key:document.getElementById('setting-groq').value,openrouter_api_key:document.getElementById('setting-openrouter').value,vercel_token:document.getElementById('setting-vercel').value,max_retries:Number(document.getElementById('max-retries').value)};
  try{const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const d=await r.json();if(!r.ok)throw Error(d.detail||'تعذر الحفظ');
   ['setting-gemini','setting-groq','setting-openrouter','setting-vercel'].forEach(id=>document.getElementById(id).value='');
   document.getElementById('settings-status').textContent='تم الحفظ. '+`مهيأ: Gemini ${d.configured.gemini?'✓':'—'} · Groq ${d.configured.groq?'✓':'—'} · Vercel ${d.configured.vercel?'✓':'—'}.`;
  }catch(e){alert(e.message)}
 };
 let installPrompt=null;
 window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;const b=document.getElementById('install-pwa');if(b)b.hidden=false});
 window.installPwa=async()=>{if(!installPrompt){alert('على Android افتح قائمة Chrome ثم اختر «تثبيت التطبيق» أو «إضافة إلى الشاشة الرئيسية».');return}installPrompt.prompt();await installPrompt.userChoice;installPrompt=null};
 window.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-pane]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.mobile-tab').forEach(x=>x.classList.toggle('active',x.dataset.view===(b.dataset.pane==='preview'?'preview':b.dataset.pane==='settings'?'settings':'work')));if(b.dataset.pane==='settings')loadSettings()}));
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
  ensureLogin();
 });
})();
