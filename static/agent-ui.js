(()=>{
 const header=document.querySelector('.top'), button=document.createElement('button');
 button.className='small';button.textContent='تنفيذ آلي';button.title='تخطيط وتنفيذ خطوات محدودة داخل workspace';
 header.insertBefore(button,header.querySelector('.deploy'));
 button.onclick=async()=>{
  const box=document.getElementById('prompt'),message=box.value.trim();
  if(!message){alert('اكتب وصف المهمة في مربع المحادثة أولاً.');return}
  const ok=confirm('سيقوم الوكيل بإعداد خطة، وكتابة ملفات وتشغيل أوامر مسموحة داخل workspace. قد تنفذ npm أوامر تثبيت وتشغيل برمجيات. النشر السحابي غير تلقائي ويتطلب موافقة منفصلة. هل تتابع؟');
  if(!ok)return;
  box.value='';window.addMsg(message,'user');button.disabled=true;button.textContent='ينفذ…';
  document.getElementById('tasklist').innerHTML='<div class="task">يخطط وينفذ حتى 10 خطوات؛ إصلاح الأوامر الفاشلة حتى 5 مرات لكل أمر</div>';
  try{
   const response=await fetch('/api/agent',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,provider:document.getElementById('provider').value,allow_execution:true})});
   const data=await response.json();if(!response.ok)throw Error(data.detail||'تعذر تشغيل الوكيل');
   let report='الملخص: '+data.summary+'\n\n';
   for(const item of data.results){report+=`الخطوة ${item.step} (${item.tool}): ${item.ok?'نجحت':'تعذرت'}\n`;
    if(item.detail)report+=item.detail+'\n';if(item.repair_attempts)report+='محاولات الإصلاح: '+item.repair_attempts+'\n';
    if(item.output)report+='الأمر: '+(item.command||'')+'\n'+(item.output.stdout||'')+(item.output.stderr||'')+'\n';
    if(item.error)report+='السبب: '+item.error+'\n';
    if(item.data)report+=JSON.stringify(item.data).slice(0,3500)+'\n';report+='\n';
   }
   if(data.final_answer)report+='\n\nالخلاصة البحثية:\n'+data.final_answer;
   if(data.report_path)report+='\n\nملف التقرير: '+data.report_path;
   report+='الحالة: '+(data.completed?'اكتملت الخطوات دون أخطاء مُبلّغ عنها':'تحتاج بعض الخطوات إلى مراجعة')+'. النشر غير تلقائي.';
   window.addMsg(report);
   document.getElementById('tasklist').innerHTML=data.results.map(x=>`<div class="task ${x.ok?'done':''}">${x.step}. ${x.tool} — ${x.ok?'نجاح':'مراجعة مطلوبة'}${x.repair_attempts?' (إصلاح '+x.repair_attempts+')':''}</div>`).join('')||'<div class="task">لم تُنشأ خطوات</div>';
  }catch(e){window.addMsg('تعذر التنفيذ الآلي: '+e.message);document.getElementById('tasklist').innerHTML='<div class="task">تعذر تنفيذ الخطة؛ راجع اتصال النموذج والإعدادات</div>'}
  finally{button.disabled=false;button.textContent='تنفيذ آلي'}
 };
})();
