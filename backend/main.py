import os, asyncio, subprocess, json, shlex, re, socket, ipaddress, secrets
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parent.parent
WORKSPACE=(ROOT/'workspace').resolve(); WORKSPACE.mkdir(exist_ok=True)
load_dotenv(ROOT/'.env')
app=FastAPI(title='Autonomous Agent Local')
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:8000','http://localhost:8000'],allow_methods=['*'],allow_headers=['*'])
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
SYSTEM_PROMPT=os.getenv('AGENT_SYSTEM_PROMPT','أنت مساعد برمجي محلي. أجب بالعربية، وكن صريحاً بشأن ما نفذته فعلاً. اقترح خطوات عملية ولا تدّع تنفيذ تغييرات لم تحدث.')

class ChatRequest(BaseModel):
    message:str=Field(min_length=1,max_length=50000)
    provider:Optional[str]='gemini'
    history:list[dict]=Field(default_factory=list, max_length=30)
class FileWrite(BaseModel): path:str; content:str
class CommandRequest(BaseModel): command:str
class DeployRequest(BaseModel): path:str='.'; confirm:bool=False
class AgentRequest(BaseModel):
    message:str=Field(min_length=1,max_length=20000)
    provider:Optional[str]='gemini'
    allow_execution:bool=False
class SettingsRequest(BaseModel):
    gemini_api_key:Optional[str]=None
    groq_api_key:Optional[str]=None
    openrouter_api_key:Optional[str]=None
    vercel_token:Optional[str]=None
    max_retries:Optional[int]=Field(default=None,ge=0,le=10)
class LoginRequest(BaseModel): password:str

@app.middleware('http')
async def public_access_guard(request:Request, call_next):
    if os.getenv('PUBLIC_MODE','false').lower() in ('1','true','yes') and request.url.path.startswith('/api/') and request.url.path not in ('/api/status','/api/login'):
        password=os.getenv('APP_PASSWORD','')
        cookie=request.cookies.get('agent_session','')
        if not password: return JSONResponse({'detail':'الاستضافة العامة غير مهيأة؛ اضبط APP_PASSWORD.'},status_code=503)
        if not secrets.compare_digest(cookie,password): return JSONResponse({'detail':'يلزم تسجيل الدخول.'},status_code=401)
    return await call_next(request)

def safe_path(rel):
    p=(WORKSPACE/rel).resolve()
    if p!=WORKSPACE and WORKSPACE not in p.parents: raise HTTPException(400,'المسار خارج مجلد workspace')
    return p

def csv_env(name, default=''):
    return [x.strip() for x in os.getenv(name,default).split(',') if x.strip()]

def fallback_chain(selected):
    order=[selected]+csv_env('FALLBACK_PROVIDERS','gemini,groq,openrouter,ollama')
    result=[]
    for x in order:
        x=x.strip().lower()
        if x in {'gemini','groq','openrouter','ollama'} and x not in result: result.append(x)
    return result

def configured(provider):
    if provider=='ollama': return bool(os.getenv('OLLAMA_ENABLED','false').lower() in ('1','true','yes') or os.getenv('OLLAMA_URL'))
    key_env={'gemini':'GEMINI_API_KEY','groq':'GROQ_API_KEY','openrouter':'OPENROUTER_API_KEY'}[provider]
    return bool(csv_env(key_env))

async def ask_provider(provider, messages):
    if provider=='ollama':
        import httpx
        base=os.getenv('OLLAMA_URL','http://localhost:11434/api/chat')
        models=csv_env('OLLAMA_MODELS',os.getenv('OLLAMA_MODEL','qwen2.5-coder:3b'))
        last=None
        async with httpx.AsyncClient(timeout=float(os.getenv('PROVIDER_TIMEOUT_SECONDS','45'))) as c:
            for model in models[:3]:
                try:
                    r=await c.post(base,json={'model':model,'stream':False,'messages':messages}); r.raise_for_status()
                    return r.json()['message']['content'],model
                except Exception as e: last=e
        raise RuntimeError(str(last or 'Ollama unavailable'))

    from openai import AsyncOpenAI
    if provider=='gemini':
        keys=csv_env('GEMINI_API_KEY'); models=csv_env('GEMINI_MODELS',os.getenv('GEMINI_MODEL','gemini-2.0-flash'))
        base=os.getenv('GEMINI_OPENAI_BASE_URL','https://generativelanguage.googleapis.com/v1beta/openai/')
    elif provider=='groq':
        keys=csv_env('GROQ_API_KEY'); models=csv_env('GROQ_MODELS',os.getenv('GROQ_MODEL','llama-3.3-70b-versatile')); base='https://api.groq.com/openai/v1'
    else:
        keys=csv_env('OPENROUTER_API_KEY'); models=csv_env('OPENROUTER_MODELS',os.getenv('OPENROUTER_MODEL','google/gemini-2.0-flash-exp:free')); base='https://openrouter.ai/api/v1'
    if not keys: raise RuntimeError('لا يوجد مفتاح مهيأ لهذا المزود')
    # عدد المحاولات محدود عمداً: نموذج/مفتاح واحد لكل تجربة ثم الانتقال للمزود التالي.
    attempts=list((key,model) for key in keys[:5] for model in models[:3])[:8]
    last=None
    for key,model in attempts:
        try:
            client=AsyncOpenAI(api_key=key,base_url=base,timeout=float(os.getenv('PROVIDER_TIMEOUT_SECONDS','45')),max_retries=0)
            result=await client.chat.completions.create(model=model,messages=messages)
            content=result.choices[0].message.content
            if content: return content,model
            raise RuntimeError('أعاد المزود رداً فارغاً')
        except Exception as e:
            last=e
            # مهلة قصيرة عند الضغط قبل تجربة بيانات الاعتماد/النموذج التالي.
            await asyncio.sleep(0.25)
    raise RuntimeError(str(last or 'تعذر الوصول للمزود'))

@app.get('/')
def index(): return FileResponse(ROOT/'static/index.html')
@app.get('/manifest.json')
def manifest(): return FileResponse(ROOT/'static/manifest.json',media_type='application/manifest+json')
@app.get('/service-worker.js')
def service_worker(): return FileResponse(ROOT/'static/service-worker.js',media_type='application/javascript')
@app.get('/api/status')
def status(request:Request):
    public=os.getenv('PUBLIC_MODE','false').lower() in ('1','true','yes')
    password=os.getenv('APP_PASSWORD','')
    authenticated=bool(password and secrets.compare_digest(request.cookies.get('agent_session',''),password))
    return {'public_mode':public,'auth_required':public and bool(password),'authenticated':authenticated}
@app.post('/api/login')
def login(body:LoginRequest,request:Request):
    expected=os.getenv('APP_PASSWORD','')
    if not expected or not secrets.compare_digest(body.password,expected): raise HTTPException(401,'كلمة المرور غير صحيحة أو غير مهيأة')
    response=JSONResponse({'ok':True})
    response.set_cookie('agent_session',expected,httponly=True,samesite='strict',secure=request.url.scheme=='https',max_age=86400)
    return response
@app.get('/api/settings')
def get_settings():
    return {'configured':{'gemini':bool(os.getenv('GEMINI_API_KEY')),'groq':bool(os.getenv('GROQ_API_KEY')),'openrouter':bool(os.getenv('OPENROUTER_API_KEY')),'vercel':bool(os.getenv('VERCEL_TOKEN'))},'max_retries':int(os.getenv('MAX_REPAIR_RETRIES','5'))}
@app.put('/api/settings')
def save_settings(body:SettingsRequest):
    from dotenv import set_key
    values={'GEMINI_API_KEY':body.gemini_api_key,'GROQ_API_KEY':body.groq_api_key,'OPENROUTER_API_KEY':body.openrouter_api_key,'VERCEL_TOKEN':body.vercel_token}
    try:
        for key,value in values.items():
            if value and value.strip():
                set_key(str(ROOT/'.env'),key,value.strip(),quote_mode='always'); os.environ[key]=value.strip()
        if body.max_retries is not None:
            os.environ['MAX_REPAIR_RETRIES']=str(body.max_retries)
            set_key(str(ROOT/'.env'),'MAX_REPAIR_RETRIES',str(body.max_retries),quote_mode='never')
    except Exception as e: raise HTTPException(500,'تعذر حفظ الإعدادات: '+str(e)[:200])
    return get_settings()
@app.get('/api/files')
def files(path:str=''):
    base=safe_path(path or '.')
    if not base.exists(): return {'items':[]}
    return {'items':[{'name':x.name,'path':str(x.relative_to(WORKSPACE)),'directory':x.is_dir()} for x in sorted(base.iterdir()) if x.name not in ['.git','node_modules','__pycache__']]}
@app.get('/api/file')
def read_file(path:str):
    p=safe_path(path)
    if not p.is_file(): raise HTTPException(404,'الملف غير موجود')
    if p.stat().st_size>10_000_000: raise HTTPException(413,'حجم الملف يتجاوز 10 ميغابايت؛ حد تشغيلي لحماية الذاكرة')
    return {'path':path,'content':p.read_text(errors='replace')}
@app.put('/api/file')
def write_file(body:FileWrite):
    p=safe_path(body.path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(body.content)
    return {'ok':True,'path':body.path}
@app.post('/api/command')
def command(body:CommandRequest):
    if len(body.command)>5000: raise HTTPException(400,'الأمر طويل جداً')
    blocked=['rm -rf /','sudo ','shutdown','reboot','mkfs','dd if=',' :(){']
    if any(x in body.command for x in blocked): raise HTTPException(403,'الأمر محظور')
    try:
        result=subprocess.run(body.command,shell=True,cwd=WORKSPACE,text=True,capture_output=True,timeout=120,env={**os.environ,'PWD':str(WORKSPACE)})
        return {'stdout':result.stdout[-20000:],'stderr':result.stderr[-12000:],'returncode':result.returncode}
    except subprocess.TimeoutExpired: return {'stdout':'','stderr':'انتهت مهلة الأمر (120 ثانية)','returncode':124}

@app.post('/api/chat')
async def chat(body:ChatRequest):
    messages=[{'role':'system','content':SYSTEM_PROMPT}]
    for item in body.history[-20:]:
        role=item.get('role'); content=item.get('content')
        if role in ('user','assistant') and isinstance(content,str): messages.append({'role':role,'content':content[:12000]})
    messages.append({'role':'user','content':body.message})
    errors=[]
    for provider in fallback_chain(body.provider or 'gemini'):
        if not configured(provider): continue
        try:
            answer,model=await ask_provider(provider,messages)
            return {'answer':answer,'provider':provider,'model':model,'fallback':provider!=(body.provider or 'gemini'),'notice':None if provider==(body.provider or 'gemini') else f'المزود الأساسي غير متاح؛ تم استخدام {provider}.','tasks':['إرسال الطلب','اختيار مزود متاح','استلام الرد']}
        except Exception as e:
            # لا نعيد الطلب بلا نهاية. ننتقل بحد أقصى بين المزودات المهيأة ثم نوضح النتيجة.
            errors.append(f'{provider}: {str(e)[:160]}')
    detail='لم ينجح أي مزود مهيأ ضمن عدد المحاولات المحدود. تحقق من المفاتيح والاتصال أو شغّل Ollama. '+' | '.join(errors[:4])
    raise HTTPException(503,detail)

def extract_json(text):
    text=text.strip()
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I)
    start=text.find('{'); end=text.rfind('}')
    if start<0 or end<start: raise ValueError('رد النموذج ليس JSON صالحاً')
    return json.loads(text[start:end+1])

async def model_call(provider, messages):
    errors=[]
    for name in fallback_chain(provider or 'gemini'):
        if not configured(name): continue
        try: return await ask_provider(name,messages),name
        except Exception as e: errors.append(f'{name}: {str(e)[:120]}')
    raise RuntimeError('لا يوجد مزود متاح: '+'; '.join(errors[:3]))

async def web_search(query):
    def run():
        from ddgs import DDGS
        with DDGS() as ddgs: return list(ddgs.text(query,max_results=5))
    try: return await asyncio.to_thread(run)
    except Exception as e: raise RuntimeError('فشل البحث العام: '+str(e)[:180])

async def fetch_page(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname: raise ValueError('يسمح بروابط HTTP/HTTPS فقط')
    host=parsed.hostname.lower()
    if host in ('localhost','localhost.localdomain') or host.endswith(('.local','.internal')): raise ValueError('الوصول إلى المضيف المحلي غير مسموح')
    try:
        for item in socket.getaddrinfo(host,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM):
            ip=ipaddress.ip_address(item[4][0])
            if not ip.is_global: raise ValueError('رفض عنوان شبكة خاصة/محلية')
    except socket.gaierror as e: raise ValueError('تعذر حل اسم الموقع: '+str(e))
    import httpx
    from bs4 import BeautifulSoup
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,headers={'User-Agent':'LocalResearchAgent/1.0'}) as client:
        response=await client.get(url)
        if response.is_redirect: raise ValueError('إعادة التوجيه غير متاحة؛ افتح الرابط النهائي مباشرة')
        response.raise_for_status()
        if len(response.content)>2_000_000: raise ValueError('حجم صفحة الويب يتجاوز 2 ميغابايت')
        soup=BeautifulSoup(response.text,'html.parser')
        for tag in soup(['script','style','nav','footer','header','noscript','svg']): tag.decompose()
        return {'url':str(response.url),'title':soup.title.get_text(' ',strip=True) if soup.title else '', 'text':soup.get_text(' ',strip=True)[:14000]}

def run_agent_command(command):
    if not isinstance(command,str) or len(command)>2000: raise ValueError('صيغة الأمر غير صالحة')
    if any(c in command for c in (';','|','&','>','<','`','$','\n','\r')): raise ValueError('الأوامر المركبة/الـ shell غير مسموحة في التنفيذ الآلي')
    args=shlex.split(command)
    if not args: raise ValueError('الأمر فارغ')
    allowed={'python','python3','node','npm','npx','pytest','pip','pip3'}
    if Path(args[0]).name not in allowed: raise ValueError('الأمر ليس ضمن قائمة الأدوات المسموحة')
    if any('..' in part.split('/') for part in args[1:]): raise ValueError('المسارات خارج مساحة العمل غير مسموحة')
    return subprocess.run(args,cwd=WORKSPACE,text=True,capture_output=True,timeout=120,env={**os.environ,'PWD':str(WORKSPACE)})

@app.post('/api/agent')
async def autonomous_agent(body:AgentRequest):
    if not body.allow_execution: raise HTTPException(400,'يلزم تفعيل التنفيذ ومراجعته قبل بدء الوكيل')
    system=('أنت وكيل برمجي يستخدم أدوات محلية. أعد JSON فقط بالشكل {"steps":[{"tool":"write_file","path":"index.html","content":"..."},{"tool":"run_command","command":"..."},{"tool":"web_search","query":"..."},{"tool":"fetch_url","url":"..."}],"summary":"..."}. '
            'حد أقصى 10 خطوات. لا تطلب أدوات غير مدرجة. لإنشاء تقرير اكتب محتواه بملف. لا تطلب النشر تلقائياً. اجعل أوامر التشغيل قصيرة ولا تستخدم shell chaining أو أوامر حذف.')
    (planning,provider)=await model_call(body.provider,[{'role':'system','content':system},{'role':'user','content':body.message}])
    try: plan=extract_json(planning[0])
    except Exception as e: raise HTTPException(502,'تعذر تحليل خطة الوكيل: '+str(e))
    steps=plan.get('steps',[])
    if not isinstance(steps,list) or len(steps)>10: raise HTTPException(400,'الخطة غير صالحة أو تتجاوز 10 خطوات')
    results=[]
    for index,step in enumerate(steps,1):
        if not isinstance(step,dict): continue
        tool=step.get('tool'); result={'step':index,'tool':tool,'ok':False}
        try:
            if tool=='write_file':
                rel=step.get('path',''); content=step.get('content','')
                if not isinstance(content,str) or len(content)>1_000_000: raise ValueError('محتوى الملف غير صالح أو يتجاوز ميغابايت')
                target=safe_path(rel); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content)
                result.update(ok=True,detail=f'حُفظ {rel}')
            elif tool=='web_search':
                data=await web_search(str(step.get('query',''))[:300]); result.update(ok=True,data=data)
            elif tool=='fetch_url':
                data=await fetch_page(str(step.get('url',''))); result.update(ok=True,data=data)
            elif tool=='run_command':
                command=step.get('command','')
                proc=await asyncio.to_thread(run_agent_command,command)
                output={'stdout':proc.stdout[-8000:],'stderr':proc.stderr[-6000:],'returncode':proc.returncode}
                repair=0
                repair_limit=max(0,min(int(os.getenv('MAX_REPAIR_RETRIES','5')),10))
                while proc.returncode!=0 and repair<repair_limit:
                    repair+=1
                    repair_prompt=('فشل أمر مشروع داخل workspace. أصلح الخطأ ذاتياً. أعد JSON فقط: {"files":[{"path":"...","content":"..."}],"command":"أمر تحقق مسموح"}. '
                                   'لا تستخدم shell chaining أو حذفاً. رسالة الخطأ:\n'+output['stderr']+'\nstdout:\n'+output['stdout']+'\nالأمر السابق: '+str(command))
                    (repair_response,_)=await model_call(body.provider,[{'role':'system','content':'أنت مصلح أخطاء برمجية. التزم بـ JSON المطلوب.'},{'role':'user','content':repair_prompt}])
                    fix=extract_json(repair_response[0])
                    for file in fix.get('files',[])[:3]:
                        target=safe_path(file.get('path','')); content=file.get('content','')
                        if not isinstance(content,str) or len(content)>1_000_000: raise ValueError('ملف إصلاح غير صالح')
                        target.parent.mkdir(parents=True,exist_ok=True); target.write_text(content)
                    command=fix.get('command',command)
                    proc=await asyncio.to_thread(run_agent_command,command)
                    output={'stdout':proc.stdout[-8000:],'stderr':proc.stderr[-6000:],'returncode':proc.returncode}
                result.update(ok=proc.returncode==0,command=command,output=output,repair_attempts=repair)
            else: raise ValueError('أداة غير معروفة')
        except Exception as e: result['error']=str(e)[:500]
        results.append(result)
    summary=plan.get('summary','اكتمل تنفيذ الخطوات المسموحة؛ راجع النتائج قبل الاعتماد.')
    research=[x for x in results if x.get('tool') in ('web_search','fetch_url') and x.get('ok')]
    final_answer=None; report_path=None
    if research:
        evidence=json.dumps(research,ensure_ascii=False)[:24000]
        try:
            (final_result,_)=await model_call(body.provider,[
                {'role':'system','content':'اكتب خلاصة بحث عربية مستندة حصراً إلى مقتطفات البحث والصفحات المقدمة. لا تخترع حقائق. اذكر روابط المصادر كما وردت، وافصل ما لا يمكن التحقق منه.'},
                {'role':'user','content':'طلب المستخدم: '+body.message+'\nنتائج المصادر:\n'+evidence}
            ])
            final_answer=final_result[0]
            folder=safe_path('reports'); folder.mkdir(parents=True,exist_ok=True)
            report_path='reports/research-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.md'
            safe_path(report_path).write_text('# تقرير بحث\n\n'+final_answer+'\n',encoding='utf-8')
            results.append({'step':len(results)+1,'tool':'write_report','ok':True,'detail':'حُفظ التقرير: '+report_path})
        except Exception as e:
            final_answer='تعذر إعداد الخلاصة النهائية: '+str(e)[:200]
    return {'provider':provider,'summary':summary,'final_answer':final_answer,'report_path':report_path,'results':results,'completed':all(x.get('ok') for x in results) if results else True,'limits':{'plan_steps':10,'repair_attempts_per_command':max(0,min(int(os.getenv('MAX_REPAIR_RETRIES','5')),10)),'deployment':'يتطلب تأكيداً منفصلاً'}}

@app.get('/api/preview')
def preview(path:str='index.html'):
    p=safe_path(path)
    if not p.is_file(): raise HTTPException(404,'لا توجد صفحة معاينة؛ أنشئ workspace/index.html')
    return FileResponse(p)
@app.post('/api/deploy')
def deploy(body:DeployRequest):
    if not body.confirm: raise HTTPException(400,'يلزم تأكيد صريح قبل النشر')
    token=os.getenv('VERCEL_TOKEN')
    if not token: raise HTTPException(400,'أضف VERCEL_TOKEN في .env')
    target=safe_path(body.path)
    if not target.is_dir(): raise HTTPException(400,'المسار ليس مجلداً')
    cmd=['npx','--yes','vercel','--yes','--token',token]
    try:
        r=subprocess.run(cmd,cwd=target,text=True,capture_output=True,timeout=300)
        output=(r.stdout+'\n'+r.stderr)[-12000:]
        return {'returncode':r.returncode,'output':output}
    except subprocess.TimeoutExpired: raise HTTPException(504,'انتهت مهلة النشر')

@app.websocket('/ws')
async def websocket(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            msg=await ws.receive_text(); await ws.send_json({'type':'status','message':'اتصال مباشر جاهز','echo':msg})
    except WebSocketDisconnect: pass
