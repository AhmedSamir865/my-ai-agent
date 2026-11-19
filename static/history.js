// استمرارية سياق المحادثة عبر reload ضمن هذا المتصفح فقط، لا تخزين لمفاتيح API.
(()=>{
 const key='autonomous-agent-chat-v1';
 let history=[];
 try{history=JSON.parse(localStorage.getItem(key)||'[]')}catch{}
 const oldSend=window.send;
 window.send=async function(){
  const box=document.getElementById('prompt'), text=box.value.trim(); if(!text)return;
  box.value=''; window.addMsg(text,'user');
  const list=document.getElementById('tasklist');
  list.innerHTML=['إرسال الطلب','محاولة المزود المختار ثم البدائل المهيأة','حفظ سياق المحادثة'].map(x=>`<div class="task">${x}</div>`).join('');
  try{
   const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,provider:document.getElementById('provider').value,history:history.slice(-20)})});
   const data=await r.json(); if(!r.ok)throw Error(data.detail||'تعذر تنفيذ الطلب');
   const answer=(data.notice?data.notice+'\n\n':'')+data.answer;
   window.addMsg(answer); history.push({role:'user',content:text},{role:'assistant',content:data.answer});
   history=history.slice(-30); localStorage.setItem(key,JSON.stringify(history));
   list.innerHTML=['اكتمل الرد عبر '+data.provider+(data.model?' / '+data.model:''),'تم حفظ سياق المحادثة محلياً'].map(x=>`<div class="task done">${x}</div>`).join('');
  }catch(e){window.addMsg('تعذر إكمال الطلب: '+e.message);list.innerHTML='<div class="task">انتهت المحاولات المحدودة؛ راجع المفاتيح والاتصال أو شغّل Ollama</div>'}
 };
})();
