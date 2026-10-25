const $ = s => document.querySelector(s);
const el = id => document.getElementById(id);
const state = {docs:[], courses:[], chats:[], chatId:null, scopeCourseId:null, scopeDocIds:[], history:[], busy:false, sourceMap:{}, messageCount:0, scroll:true, responseMode:'auto'};
const esc = s => String(s ?? '').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
let toastTimer;
function toast(msg){let t=el('toast');t.textContent=msg;t.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),4600)}
async function api(path,options={}){
 const r=await fetch(path,options);let data;try{data=await r.json()}catch{data={detail:'Unexpected server response.'}}
 if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:`Request failed (${r.status})`);return data;
}
function setBusy(b){state.busy=b;el('ask-send').disabled=b;el('question').disabled=b;el('gap-btn').disabled=b;el('recall-btn').disabled=b;el('claim-btn').disabled=b;}
function showModal(){el('upload-modal').hidden=false;closeSidebar();el('close-upload').focus()}
function hideModal(){el('upload-modal').hidden=true}
function formatKind(kind){return kind==='slides'?'Lecture slides':'My notes'}
function closeSidebar(){el('sidebar').classList.remove('open');el('mobile-scrim').hidden=true;el('mobile-menu').setAttribute('aria-expanded','false')}
function renderHome(){
 const courses=el('home-courses'), recent=el('home-recent-docs'), quick=el('sidebar-course-list');
 if(!courses||!recent||!quick)return;
 const count=id=>state.docs.filter(d=>d.course_id===id).length;
 quick.innerHTML=state.courses.length?state.courses.map(c=>`<button class="sidebar-course" type="button" data-home-course="${esc(c.id)}" title="Start a chat in ${esc(c.name)}"><span class="sidebar-course-dot"></span><span>${esc(c.name)}</span><span class="sidebar-course-count">${count(c.id)}</span></button>`).join(''):'<div class="no-files">Create a course in Sources.</div>';
 courses.innerHTML=state.courses.length?state.courses.map(c=>`<button class="course-tile" type="button" data-home-course="${esc(c.id)}"><span class="course-initial">${esc(c.name.replace(/[^a-z0-9 ]/ig,'').trim().split(/\s+/).at(-1)?.slice(0,3).toUpperCase()||'C')}</span><span class="course-details"><strong>${esc(c.name)}</strong><small>${count(c.id)} file${count(c.id)===1?'':'s'} · Course chat</small></span><span class="course-arrow" aria-hidden="true">↗</span></button>`).join(''):'<div class="home-empty">No courses yet. Create one in Sources to keep chats focused on the right material.</div>';
 recent.innerHTML=state.docs.length?state.docs.slice(0,5).map(d=>`<a class="recent-doc" href="/api/documents/${encodeURIComponent(d.id)}/file" target="_blank" rel="noopener noreferrer" title="Open ${esc(d.name)}"><span class="recent-doc-icon" aria-hidden="true">▤</span><span class="recent-doc-info"><strong>${esc(d.name)}</strong><small>${esc(courseName(d.course_id)||'Unassigned')} · ${d.page_count} page${d.page_count===1?'':'s'}</small></span><span class="recent-doc-arrow" aria-hidden="true">↗</span></a>`).join(''):'<div class="home-empty">No material yet. Upload your first PDF or set of lecture slides below.</div>';
 el('home-library-count').textContent=`${state.docs.length} file${state.docs.length===1?'':'s'} total`;
}
async function loadDocs(){try{const d=await api('/api/documents');state.docs=d.documents;el('doc-total').textContent=d.documents.length;
 el('file-list').innerHTML=d.documents.length?d.documents.map(doc=>`<div class="file-item"><span class="file-icon">${doc.kind==='slides'?'▤':'▧'}</span><div class="file-label" title="${esc(doc.name)}"><strong>${esc(doc.name)}</strong><small>${esc(courseName(doc.course_id)||'Unassigned')} · ${doc.page_count} page${doc.page_count!==1?'s':''}${doc.ocr_count?' · OCR':''}</small></div><button class="delete-file" title="Remove document" data-delete="${doc.id}">×</button></div>`).join(''):'<div class="no-files">Your notes will appear here.</div>';
 renderHome();await loadOverview(); }catch(e){toast(e.message)}}
async function uploadFiles(files){hideModal();if(!files.length)return;
 const kind=document.querySelector('input[name="kind"]:checked')?.value||'notes';let successes=0;
 for(const file of files){toast(`Indexing ${file.name}…`);
  const form=new FormData(); form.append('file',file);form.append('kind',kind);form.append('course_id',el('upload-course').value||'');
  try{const d=await api('/api/upload',{method:'POST',body:form});successes++;
    toast(d.duplicate?`${file.name} is already in your library.`:`Indexed ${file.name}: ${d.pages} pages, ${d.chunks} passages${d.ocr_pages?` (${d.ocr_pages} OCR)` : ''}.`);
  }catch(e){toast(`${file.name}: ${e.message}`)}
 }
 if(successes){await loadDocs();await loadChats()}el('file-input').value='';
}
function courseName(id){return state.courses.find(c=>c.id===id)?.name||'';}
async function loadCourses(){
 try{const d=await api('/api/courses');state.courses=d.courses;
  el('upload-course').innerHTML='<option value="">Unassigned</option>'+d.courses.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');renderHome();
 }catch(e){toast(e.message)}
}
async function openSources(){
 await loadCourses();await loadDocs();
 enterMode('sources','Sources','Files and courses, organized for better answers.',
 `<div class="source-toolbar"><button id="sources-upload" type="button">+ Upload files</button></div><form class="course-create" id="course-create"><input id="course-name" maxlength="80" required minlength="2" placeholder="Course name · e.g. CSE 220" aria-label="Course name"><button type="submit">Create course</button></form><div class="sources-groups" id="course-groups"></div>`);
 renderSources();el('sources-upload').onclick=showModal;
 el('course-create').onsubmit=async e=>{e.preventDefault();const name=el('course-name').value.trim();try{await api('/api/courses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});await loadCourses();await loadDocs();el('course-name').value='';renderSources();toast(`Created ${name}`);}catch(err){toast(err.message)}};
}
function renderSources(){
 const container=el('course-groups');if(!container)return;
 const groups=[...state.courses,{id:'',name:'Unassigned'}];
 container.innerHTML=groups.map(course=>{
  const documents=state.docs.filter(d=>(d.course_id||'')===course.id);
  return `<section class="source-group"><div class="source-group-head"><h3>${esc(course.name)}</h3><span>${documents.length} file${documents.length===1?'':'s'}</span>${course.id?`<button type="button" class="course-chat" data-course-chat="${course.id}">New chat in ${esc(course.name)} ↗</button>`:''}</div>
   ${documents.map(d=>`<div class="source-file"><div><strong>${esc(d.name)}</strong><small>${formatKind(d.kind)} · ${d.page_count} pages</small></div><div class="source-file-controls"><label>Move to <select data-move-doc="${d.id}" aria-label="Course for ${esc(d.name)}"><option value="">Unassigned</option>${state.courses.map(c=>`<option value="${c.id}" ${c.id===d.course_id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></label><button type="button" class="source-file-delete" data-source-delete="${d.id}" aria-label="Remove ${esc(d.name)} from library" title="Delete document">Remove</button></div></div>`).join('')||'<p class="source-empty">No files yet.</p>'}</section>`;
 }).join('');
 container.querySelectorAll('[data-move-doc]').forEach(select=>select.onchange=async()=>{
  try{await api(`/api/documents/${select.dataset.moveDoc}/course`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({course_id:select.value||null})});await loadDocs();renderSources();toast('File moved.');}catch(e){toast(e.message);renderSources()}
 });
 container.querySelectorAll('[data-source-delete]').forEach(btn=>btn.onclick=async()=>{
   if(!confirm('Remove this document and its search index?'))return;
   try{await api(`/api/documents/${encodeURIComponent(btn.dataset.sourceDelete)}`,{method:'DELETE'});await loadDocs();renderSources();toast('Document removed.')}catch(err){toast(err.message)}
 });
 container.querySelectorAll('[data-course-chat]').forEach(btn=>btn.onclick=()=>newConversation(btn.dataset.courseChat));
}
async function loadChats(){
 try{const d=await api('/api/chats');state.chats=d.chats;el('chat-total').textContent=d.chats.length;
  el('chat-list').innerHTML=d.chats.length?d.chats.map(c=>`<div class="chat-item ${state.chatId===c.id?'selected':''}"><button type="button" class="chat-item-open" data-open-chat="${esc(c.id)}" title="${esc(c.title)}"><span class="chat-item-glyph">◌</span><span class="chat-item-title">${esc(c.title)}</span></button><button type="button" class="delete-chat" data-delete-chat="${esc(c.id)}" title="Delete conversation" aria-label="Delete ${esc(c.title)}">×</button></div>`).join(''):'<div class="no-files">Your conversations will appear here.</div>';
 }catch(e){toast(e.message)}
}
function scopeLabel(){if(state.scopeCourseId)return courseName(state.scopeCourseId)||'Course';const ids=state.scopeDocIds;if(!ids.length)return 'Entire library';const docs=state.docs.filter(d=>ids.includes(d.id));return docs.length===1?docs[0].name:`${ids.length} selected sources`}
function updateScopeUI(){const label=scopeLabel();el('composer-source-label').textContent=`· ${label}`;el('chat-scope').textContent=label+' ▾';el('chat-scope').title='Choose sources for this conversation';el('chat-scope').disabled=false;el('question').placeholder='Ask a question…';}
function openScope(){
 if(state.busy)return;
 const list=el('scope-doc-list');
 el('scope-type').innerHTML='<option value="all">Entire library</option>'+state.courses.map(c=>`<option value="course:${c.id}">${esc(c.name)} · Course (all current and future files)</option>`).join('')+'<option value="files">Specific files</option>';
 el('scope-type').value=state.scopeCourseId?'course:'+state.scopeCourseId:state.scopeDocIds.length?'files':'all';
 list.innerHTML=state.docs.length?state.docs.map(d=>`<label class="scope-doc"><input type="checkbox" data-scope-doc="${esc(d.id)}" ${state.scopeDocIds.includes(d.id)?'checked':''}><span><strong>${esc(d.name)}</strong><small>${esc(courseName(d.course_id)||'Unassigned')} · ${d.page_count} pages</small></span></label>`).join(''):'<div class="no-files">Upload files first.</div>';
 const sync=()=>{list.hidden=el('scope-type').value!=='files'};el('scope-type').onchange=sync;sync();
 el('scope-modal').hidden=false;el('close-scope').focus();
}
function closeScope(){el('scope-modal').hidden=true}
async function saveScope(){
 const type=el('scope-type').value;
 const course=type.startsWith('course:')?type.slice(7):null;
 const ids=type==='files'?[...document.querySelectorAll('[data-scope-doc]:checked')].map(i=>i.dataset.scopeDoc):[];
 if(type==='files'&&!ids.length){toast('Choose at least one file.');return}
 try{
  const changed = state.chatId && (state.scopeCourseId!==course || JSON.stringify(state.scopeDocIds)!==JSON.stringify(ids));
  if(changed && state.history.length){newConversation(course);state.scopeDocIds=ids;}
  else if(state.chatId){await api(`/api/chats/${state.chatId}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({course_id:course||'',doc_ids:ids})});await loadChats()}
  state.scopeCourseId=course;state.scopeDocIds=ids;updateScopeUI();closeScope();
  toast(course?`Chat limited to ${courseName(course)}.`:ids.length?'Chat limited to selected files.':'Chat uses the entire library.');
 }catch(e){toast(e.message)}
}
async function openChat(id){if(state.busy)return;
 try{const data=await api(`/api/chats/${id}`);const chat=data.chat;state.chatId=chat.id;state.scopeCourseId=chat.course_id||null;state.scopeDocIds=chat.doc_ids;state.sourceMap={};state.messageCount=0;state.history=[];
 el('messages').innerHTML='';el('chat-title').textContent=chat.title;el('source-panel').hidden=true;startChat();
 for(const msg of chat.messages){if(msg.role==='user'){el('messages').insertAdjacentHTML('beforeend',`<div class="message-user"><div class="user-bubble">${esc(msg.content)}</div></div>`);state.history.push({role:'user',content:msg.content});}
  else{const d=msg.response||{status:'insufficient',direct:[{text:msg.content,source_ids:[]}],sources:[]};const mid=sourceRegister(d.sources||[]);el('messages').insertAdjacentHTML('beforeend',answerHtml(d,mid));state.history.push({role:'assistant',content:msg.content});}}
 state.history=state.history.slice(-10);updateScopeUI();await loadChats();jumpBottom();closeSidebar();}
 catch(e){toast(e.message)}
}
function newConversation(courseId=null){if(state.busy)return;if(typeof courseId!=='string')courseId=null;state.chatId=null;state.scopeCourseId=courseId;state.scopeDocIds=[];state.history=[];state.sourceMap={};state.messageCount=0;el('chat-title').textContent='New conversation';el('messages').innerHTML=`<div class="chat-welcome"><strong>What would you like to know?</strong><p>${courseId?`Ask about ${esc(courseName(courseId))} or anything else.`:'Choose a course or simply ask a question.'}</p></div>`;el('question').value='';el('source-panel').hidden=true;startChat();updateScopeUI();loadChats();closeSidebar();el('question').focus();}
function setActiveNav(name){document.querySelectorAll('[data-nav]').forEach(b=>b.classList.toggle('active',b.dataset.nav===name));el('crumb-current').textContent=({home:'Home',lens:'Chats',radar:'Coverage radar',recall:'Recall lab',claim:'Claim inspector',sources:'Sources'})[name]||'Home';}
function startChat(){el('composer-wrap').hidden=false;el('landing').hidden=true;el('mode-section').hidden=true;el('chat').hidden=false;setActiveNav('lens');}
function clearChat(){el('composer-wrap').hidden=true;el('main-scroll').scrollTop=0;setActiveNav('home');state.chatId=null;state.scopeCourseId=null;state.scopeDocIds=[];state.history=[];state.sourceMap={};updateScopeUI();el('messages').innerHTML='';el('chat').hidden=true;el('mode-section').hidden=true;el('landing').hidden=false;el('source-panel').hidden=true;el('question').value='';el('question').focus();closeSidebar()}
function jumpBottom(){const m=el('main-scroll');m.scrollTo({top:m.scrollHeight,behavior:'smooth'})}
function inlineMarkup(text){
 // Escape first: notes and model responses are untrusted strings, not HTML.
 return esc(text).replace(/`([^`\n]{1,120})`/g,'<code>$1</code>')
  .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
  .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g,'<em>$1</em>');
}
function renderProse(text){
 // Safe Markdown subset: no raw HTML, scripts, images or external dependencies.
 const lines=String(text||'').replace(/\r/g,'').split('\n'), blocks=[];
 let bullets=[],ordered=[],para=[],code=[],codeLang='',inCode=false;
 const flushPara=()=>{if(para.length){blocks.push(`<p>${para.map(inlineMarkup).join(' ')}</p>`);para=[]}};
 const flushLists=()=>{if(bullets.length){blocks.push(`<ul>${bullets.map(t=>`<li>${inlineMarkup(t)}</li>`).join('')}</ul>`);bullets=[]}
   if(ordered.length){blocks.push(`<ol>${ordered.map(t=>`<li>${inlineMarkup(t)}</li>`).join('')}</ol>`);ordered=[]}};
 const flushCode=()=>{blocks.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);code=[];inCode=false;codeLang=''};
 for(const line of lines){const raw=line.trim();
   if(raw.startsWith('```')){flushPara();flushLists();if(inCode)flushCode();else{inCode=true;codeLang=raw.slice(3).trim()}continue}
   if(inCode){code.push(line);continue}
   if(!raw){flushPara();flushLists();continue}
   if(/^[-*•]$/.test(raw))continue; // fix stray '-' and '*' appearing from bad bullets
   // Document topic labels like **Fundamentals** need their own visual line.
   const boldTitle=raw.match(/^\*\*([^*\n]{3,100})\*\*$/);
   if(boldTitle){flushPara();flushLists();blocks.push(`<h3 class="concept-title">${inlineMarkup(boldTitle[1])}</h3>`);continue}
   const heading=raw.match(/^(#{1,4})\s+(.+)$/);
   if(heading){flushPara();flushLists();const level=Math.min(heading[1].length+1,5);blocks.push(`<h${level}>${inlineMarkup(heading[2])}</h${level}>`);continue}
   const bullet=raw.match(/^(?:[-*•]\s+)(.+)$/);
   if(bullet){flushPara();if(ordered.length)flushLists();bullets.push(bullet[1]);continue}
   const numbered=raw.match(/^\d+[.)]\s+(.+)$/);
   if(numbered){flushPara();if(bullets.length)flushLists();ordered.push(numbered[1]);continue}
   flushLists();para.push(raw);
 }
 if(inCode)flushCode();flushPara();flushLists();return blocks.join('')||'<p></p>';
}
function citations(st,sources,messageId){
 const found=new Set();return (st.source_ids||[]).map(sid=>{
  const src=sources.find(s=>s.id===sid);if(!src)return '';
  const key=`${src.doc_id}:${src.page}`;if(found.has(key))return '';found.add(key);
  return `<button class="source-ref" type="button" data-sid="${esc(sid)}" data-msg="${messageId}" title="Open ${esc(src.document)}, page ${src.page}">p. ${src.page}<span aria-hidden="true"> ↗</span></button>`;
 }).join(' ');
}
function answerHtml(d,messageId){
 const sources=d.sources||[];
 if(d.status==='conversation'){
  const general=d.answer_mode==='general';
  return `<article class="assistant-bubble reply"><div class="assistant-name">ProofNotes <span class="reply-mode">${general?'General knowledge · not from your notes':'Conversation'}</span></div><div class="answer-direct readable">${renderProse(d.direct?.[0]?.text||'')}</div>${d.note?`<p class="answer-note">${esc(d.note)}</p>`:''}${sources.length?`<details class="source-disclosure"><summary>Related passages · not verification</summary><div class="source-link-list">${sources.map(s=>sourceButton(s,messageId)).join('')}</div></details>`:''}</article>`;
 }
 if(d.status!=='answered'){
  const passages=sources.map(src=>`<div class="related-passage"><button class="source-row" type="button" data-sid="${esc(src.id)}" data-msg="${messageId}">${esc(src.document)} · page ${src.page} ↗</button><blockquote>${esc((src.quotes||[])[0]||'')}</blockquote></div>`).join('');
  return `<article class="assistant-bubble reply"><div class="assistant-name">ProofNotes <span class="reply-mode">Evidence not established</span></div><div class="answer-direct readable">${renderProse(d.direct?.[0]?.text||'I couldn’t verify an answer from these documents.')}</div>${passages?`<details class="source-disclosure"><summary>Inspect possible references (${sources.length})</summary>${passages}</details>`:''}</article>`;
 }
 const isOverview=d.answer_mode==='outline';
 const isStudy=d.answer_mode==='study_guide'||d.answer_mode==='syllabus';
 const direct=(d.direct||[]).map(x=>`<div class="answer-line">${renderProse(x.text)}<div class="statement-cites">${citations(x,sources,messageId)}</div></div>`).join('');
 // Keep substantive overviews readable; additional topics are there on demand.
 const expanded=(d.detail||[]).map(x=>`<div class="answer-line">${renderProse(x.text)}<div class="statement-cites">${citations(x,sources,messageId)}</div></div>`);
 const detail=expanded.length ? (isStudy ? `<div class="study-sections">${expanded.join('')}</div>` : isOverview ?
   `<div class="overview-excerpt">${expanded.slice(0,2).join('')}</div>${expanded.length>2?`<details class="answer-details"><summary>Show ${expanded.length-2} more topic${expanded.length-2!==1?'s':''}</summary><div class="detail-body">${expanded.slice(2).join('')}</div></details>`:''}` :
   `<details class="answer-details"><summary>More detail</summary><div class="detail-body">${expanded.join('')}</div></details>`) : '';
 const uniqueSources=[];const seen=new Set();for(const src of sources){const key=`${src.doc_id}:${src.page}`;if(seen.has(key))continue;seen.add(key);uniqueSources.push(src)}
 const sourceLinks=uniqueSources.map(s=>`<button class="source-row" type="button" data-sid="${esc(s.id)}" data-msg="${messageId}">${esc(s.document)} · p. ${s.page} ↗</button>`).join('');
 const next=d.next_question?`<button class="next-question" type="button" data-next="${esc(d.next_question)}">${esc(d.next_question)} ↗</button>`:'';
 const origin=isStudy?'Study guide · cited slides':isOverview?'Notes overview':d.answer_mode==='syllabus'?'From your syllabus':d.answer_mode==='extractive'?'From your notes':'Notes explanation · check citations';
 return `<article class="assistant-bubble reply"><div class="assistant-name">ProofNotes <span class="reply-mode">${origin}</span></div><div class="answer-direct readable">${direct}</div>${detail}${d.extra?`<section class="practice-extra"><h3>${esc(d.extra_label||'AI-generated examples · not from your notes')}</h3>${renderProse(d.extra)}</section>`:''}${sourceLinks?`<details class="source-disclosure"><summary>View sources · ${uniqueSources.length} page${uniqueSources.length!==1?'s':''}</summary><div class="source-link-list">${sourceLinks}</div></details>`:''}${next}</article>`;
}
async function ask(q){q=(q||'').trim();if(!q||state.busy)return;
 startChat();el('question').value='';state.scroll=true;const welcome=el('messages').querySelector('.chat-welcome');if(welcome)welcome.remove();
 el('messages').insertAdjacentHTML('beforeend',`<div class="message-user"><div class="user-bubble">${esc(q)}</div></div>`);
 const loading=document.createElement('div');loading.className='assistant-bubble';loading.innerHTML=`<div class="assistant-name">ProofNotes · thinking</div><div class="typing"><span></span><span></span><span></span></div>`;
 el('messages').appendChild(loading);jumpBottom();setBusy(true);
 try{if(!state.chatId){const made=await api('/api/chats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({doc_ids:state.scopeDocIds,course_id:state.scopeCourseId})});state.chatId=made.chat.id;}
   const d=await api(`/api/chats/${state.chatId}/ask`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,model:el('model-select').value,response_mode:state.responseMode})});
   const messageId=++state.messageCount;state.sourceMap[messageId]=d.sources||[];loading.outerHTML=answerHtml(d,messageId);
   state.history.push({role:'user',content:q});state.history.push({role:'assistant',content:(d.direct||[]).map(x=>x.text).join(' ')});
   state.history=state.history.slice(-10);await loadChats();const chat=state.chats.find(c=>c.id===state.chatId);if(chat)el('chat-title').textContent=chat.title;
 }catch(e){loading.outerHTML=`<div class="assistant-bubble"><div class="notice">${esc(e.message)}</div></div>`;toast(e.message)}
 finally{setBusy(false);el('question').focus();jumpBottom()}
}
function findMatches(text,quotes){let spans=[];
 for(const quote of quotes){const parts=quote.trim().split(/\s+/).filter(Boolean);if(!parts.length)continue;
 const pat=parts.map(x=>x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('\\s+');
 try{const re=new RegExp(pat,'gi');let match;while((match=re.exec(text))!==null){spans.push([match.index,match.index+match[0].length]);if(!match[0].length)break;}}catch(e){}
 }
 spans.sort((a,b)=>a[0]-b[0]);const merged=[];for(const s of spans){let last=merged.at(-1);if(last&&s[0]<=last[1])last[1]=Math.max(last[1],s[1]);else merged.push([...s]);}
 let output='',p=0;for(const [a,b] of merged){output+=esc(text.slice(p,a))+'<mark>'+esc(text.slice(a,b))+'</mark>';p=b;}return output+esc(text.slice(p));
}
async function openSource(src){try{const page=await api(`/api/documents/${encodeURIComponent(src.doc_id)}/pages/${src.page}`);
 el('source-title').textContent=src.document;el('source-page').textContent=`Page ${src.page}`;el('source-ocr').textContent=page.ocr?'OCR transcription':'';
 el('source-text').innerHTML=findMatches(page.text,src.quotes||[]);
 const isPdf=src.document.toLowerCase().endsWith('.pdf');
 el('pdf-preview').hidden=!isPdf;
 if(isPdf){
  const quote=(src.quotes||[])[0]||'';
  el('pdf-image').src=`/api/documents/${encodeURIComponent(src.doc_id)}/pages/${src.page}/pdf-preview?quote=${encodeURIComponent(quote)}`;
  el('pdf-image').onerror=()=>{el('pdf-preview').hidden=true};
 }else{el('pdf-image').removeAttribute('src')}

 el('original-link').href=`/api/documents/${encodeURIComponent(src.doc_id)}/file#page=${src.page}`;
 el('source-panel').hidden=false;el('source-text').scrollTop=0;
 const mark=el('source-text').querySelector('mark');if(mark)mark.scrollIntoView({block:'center'});
 }catch(e){toast(e.message)}}
async function loadOverview(){try{const d=await api('/api/overview');el('stat-docs').textContent=d.documents;el('stat-pages').textContent=d.pages;el('stat-passages').textContent=d.evidence_passages;}catch(e){/* status still visible */}}
function sourceRegister(sources){const id=++state.messageCount;state.sourceMap[id]=sources||[];return id;}
function sourceButton(src,msg){return `<button class="source-chip" data-msg="${msg}" data-sid="${esc(src.id)}">↗ ${esc(src.document)} · p.${src.page}</button>`;}
function enterMode(name,title,subtitle,html){el('source-panel').hidden=true;el('composer-wrap').hidden=true;el('landing').hidden=true;el('chat').hidden=true;el('mode-section').hidden=false;el('mode-title').textContent=title;el('mode-subtitle').textContent=subtitle;el('mode-content').innerHTML=html;closeSidebar();el('main-scroll').scrollTop=0;state.mode=name;setActiveNav(name);}
function openLens(){if(state.chatId){startChat();el('main-scroll').scrollTop=0;el('question').focus();}else newConversation();}
function openClaim(){enterMode('claim','Claim Inspector','State a fact from your notes. We look for direct support or explicit contradiction — not generic AI agreement.',`<form class="mode-panel mode-form" id="claim-form"><label for="claim-input"><strong>Put a claim on trial</strong></label><textarea class="mode-input" id="claim-input" placeholder="Example: The lecture says a t-test always requires a known population standard deviation." required minlength="5" maxlength="700"></textarea><button class="mode-button" type="submit">Inspect evidence ↗</button><span class="mode-note">A claim is marked unclear unless the documents explicitly support or disprove it.</span></form><div id="claim-result"></div>`);el('claim-form').onsubmit=e=>{e.preventDefault();inspectClaim()};}
async function inspectClaim(){if(state.busy)return;const claim=el('claim-input').value.trim();if(claim.length<5)return;const pane=el('claim-result');pane.innerHTML='<div class="mode-panel">Checking the available passages…</div>';setBusy(true);
 try{const d=await api('/api/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({claim,model:el('model-select').value})});const msg=sourceRegister(d.sources);
 const labels={supported:'Supported by notes',contradicted:'Contradicted by notes',unclear:'Not established'};
 pane.innerHTML=`<div class="mode-panel"><span class="claim-verdict ${esc(d.verdict)}">${labels[d.verdict]||'Unclear'}</span><p>${esc(d.explanation)}</p>${(d.sources||[]).map(src=>sourceButton(src,msg)).join('')}<p class="mode-note">Model judgment is not a formal proof. Open the quotation and verify it yourself.</p></div>`;
 }catch(e){pane.innerHTML=`<div class="mode-panel">${esc(e.message)}</div>`}finally{setBusy(false)}}
async function runGaps(){if(state.busy)return;enterMode('radar','Coverage Radar','Where might your own notes be thinner than the professor’s slides?',`<div class="mode-panel" id="radar-result">Comparing the on-device embeddings of your lecture slides and notes…</div>`);setBusy(true);
 try{const result=await api('/api/gaps',{method:'POST'});const msg=sourceRegister(result.gaps.map(g=>g.source));
 el('radar-result').innerHTML=`<strong>Potential blind spots · ${result.gaps.length} passages</strong><p class="mode-note">${esc(result.disclaimer)}</p>${result.gaps.map((g,i)=>`<div class="radar-flag"><strong>${i+1}. ${esc(g.title)}</strong><p>${esc(g.explanation)}</p><p>Closest match found: ${esc(g.nearest.document)} · p.${g.nearest.page}</p>${sourceButton(g.source,msg)}</div>`).join('')||'<p>No candidate passages found.</p>'}`;
 }catch(e){el('radar-result').textContent=e.message}finally{setBusy(false)}}
const recallState={cards:[],index:0,revealed:false,correct:0,review:0,missed:[],seenKey:'',lastDisplayed:''};
function rotateRecall(cards,key){
 const shuffled=[...cards];
 for(let i=shuffled.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[shuffled[i],shuffled[j]]=[shuffled[j],shuffled[i]];}
 let shown=[];try{shown=JSON.parse(localStorage.getItem(key)||'[]');if(!Array.isArray(shown))shown=[];}catch{shown=[];}
 const seen=new Set(shown);
 if(shuffled.every(c=>seen.has(c.question))){shown=[];seen.clear();}
 shuffled.sort((a,b)=>Number(seen.has(a.question))-Number(seen.has(b.question)));
 if(shuffled.length>1 && shuffled[0].question===shown.at(-1)){
   const swap=shuffled.findIndex(c=>c.question!==shown.at(-1));
   if(swap>0)[shuffled[0],shuffled[swap]]=[shuffled[swap],shuffled[0]];
 }
 return shuffled.slice(0,12);
}
function rememberRecall(card){
 const st=recallState;
 if(!st.seenKey||st.lastDisplayed===card.question)return;
 st.lastDisplayed=card.question;
 try{const shown=JSON.parse(localStorage.getItem(st.seenKey)||'[]');
   shown.push(card.question);localStorage.setItem(st.seenKey,JSON.stringify(shown.slice(-150)));
 }catch{} // Private mode must not break practice.
}
function showRecall(){
 const st=recallState,card=st.cards[st.index],c=el('recall-result');if(!c)return;
 if(!card){c.innerHTML='<div class="recall-empty">No source-backed concept questions were found. Try Mixed difficulty or choose a richer lecture file.</div>';return;}
 rememberRecall(card);
 const msg=sourceRegister([card.source]);
 c.innerHTML=`<div class="recall-topline"><span>Question ${st.index+1} of ${st.cards.length} <span class="recall-level">${esc(card.difficulty||'easy')}</span>${card.generated?' <span class="recall-ai-label">AI draft · check source</span>':''}</span><span>${st.correct} remembered · ${st.review} review</span></div>
 <div class="recall-track"><span style="width:${100*st.index/st.cards.length}%"></span></div>
 <h3 class="recall-question">${esc(card.question)}</h3>
 ${st.revealed?`<div class="recall-divider"></div><div class="recall-answer-label">Answer</div><p class="recall-answer">${esc(card.answer)}</p><div class="recall-citation">${sourceButton(card.source,msg)}</div><div class="recall-actions"><button type="button" data-recall="again" class="recall-secondary">Need review</button><button type="button" data-recall="know" class="recall-primary">I got it <span aria-hidden="true">✓</span></button></div>`:
 `<p class="recall-prompt">Think it through first. The supporting source appears after you reveal the answer.</p><div class="recall-actions"><button type="button" data-recall="reveal" class="recall-primary">Reveal answer</button></div>`}`;
}
function recallSources(){
 const select=el('recall-doc');if(!select)return;
 const previous=select.value;
 select.innerHTML='<option value="all">All study notes (syllabi excluded)</option>'+state.courses.map(c=>`<option value="course:${c.id}">${esc(c.name)} · Course</option>`).join('')+state.docs.filter(d=>!/(syllab|course[ _-]?(outline|policy)|grading[ _-]?policy)/i.test(d.name)).map(d=>`<option value="doc:${d.id}">${esc(d.name)}</option>`).join('');
 if([...select.options].some(o=>o.value===previous))select.value=previous;
 else if(state.scopeCourseId)select.value='course:'+state.scopeCourseId;
 else if(state.scopeDocIds.length===1)select.value='doc:'+state.scopeDocIds[0];
 else select.value='all';
}
async function loadRecall(advanced=false){
 if(state.busy)return;
 const value=el('recall-doc')?.value||'all';
 const difficulty=el('recall-difficulty')?.value||'mixed';
 el('recall-result').innerHTML='<p class="recall-loading" role="status">'+(advanced?'Creating local AI questions (first time may take longer)…':'Loading questions…')+'</p>';
 el('recall-doc').disabled=true;el('recall-difficulty').disabled=true;el('recall-refresh').disabled=true;el('recall-advanced').disabled=true;setBusy(true);
 const controller=new AbortController();
 const timeout=setTimeout(()=>controller.abort(),advanced?40000:12000);
 try{
  const payload={model:el('model-select').value,difficulty,advanced,doc_ids:value.startsWith('doc:')?[value.slice(4)]:[],course_id:value.startsWith('course:')?value.slice(7):null};
  const d=await api('/api/recall',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
  const seenKey=`proofnotes-recall:${value}:${difficulty}:${advanced?'ai':'fast'}`;
  Object.assign(recallState,{cards:rotateRecall(d.cards||[],seenKey),seenKey,lastDisplayed:'',index:0,revealed:false,correct:0,review:0,missed:[]});showRecall();
 }catch(e){el('recall-result').textContent=e.name==='AbortError'?'Request timed out. Quick decks do not need Ollama; try New questions again.':e.message}
 finally{clearTimeout(timeout);setBusy(false);el('recall-doc').disabled=false;el('recall-difficulty').disabled=false;el('recall-refresh').disabled=false;el('recall-advanced').disabled=false;}
}
function openRecall(){
 if(state.busy)return;
 enterMode('recall','Recall Lab','Remember the material. Check the original slide afterward.',
 `<div class="recall-toolbar"><div class="recall-field"><label for="recall-doc">Study material</label><select id="recall-doc" aria-label="Choose document for Recall Lab"></select></div><div class="recall-field"><label for="recall-difficulty">Difficulty</label><select id="recall-difficulty" aria-label="Question difficulty"><option value="mixed">Mixed</option><option value="easy">Easy</option><option value="hard">Hard</option></select></div><button type="button" id="recall-refresh" class="recall-refresh">New questions ↻</button><button type="button" id="recall-advanced" class="recall-refresh" title="Optional: local 9B generation, then saved for next time">AI challenge</button></div><section class="recall-card" id="recall-result" aria-live="polite"></section><p class="recall-footnote">Test concepts, not slide numbers. Questions are based on your notes; verify important answers with the cited passage.</p>`);
 recallSources();el('recall-refresh').onclick=()=>loadRecall();el('recall-advanced').onclick=()=>loadRecall(true);el('recall-doc').onchange=()=>loadRecall();el('recall-difficulty').onchange=()=>loadRecall();
 loadRecall();
}
function recallAction(action){
 if(action==='reveal'){recallState.revealed=true;showRecall();return;}
 if(action==='know')recallState.correct++;
 else if(action==='again'){recallState.review++;recallState.missed.push(recallState.cards[recallState.index]);}
 else if(action==='review-missed'){
  Object.assign(recallState,{cards:[...recallState.missed],index:0,revealed:false,correct:0,review:0,missed:[]});showRecall();return;
 }else if(action==='restart'){loadRecall();return;}else return;
 recallState.index++;recallState.revealed=false;
 if(recallState.index>=recallState.cards.length){
  el('recall-result').innerHTML=`<div class="recall-complete"><span>Round complete</span><h3>${recallState.correct} of ${recallState.cards.length} remembered</h3><p>${recallState.review?`${recallState.review} questions marked for review.`:'All questions marked as remembered.'}</p><div class="recall-actions">${recallState.missed.length?'<button type="button" class="recall-secondary" data-recall="review-missed">Review missed</button>':''}<button type="button" class="recall-primary" data-recall="restart">Start again</button></div></div>`;
 }else showRecall();
}
async function checkReadiness(){try{const h=await api('/api/health');const selected=el('model-select').value || h.default_model;
 const modelGood=h.installed_models.includes(selected), embedGood=h.installed_models.includes(h.embedding_model),read=h.ollama_connected&&modelGood&&embedGood;
 const messages=[];if(!h.ollama_connected)messages.push('Ollama not running');else {if(!modelGood)messages.push(`Pull ${selected} using: ollama pull ${selected}`);if(!embedGood)messages.push(`Pull ${h.embedding_model}`)}
 if(!h.ocr_installed)messages.push('Tesseract not installed (needed only for scanned docs)');
 el('readiness').textContent=read?`Ready to study  ·  ${selected}  ·  All inference on this Mac`:`Setup needed  ·  ${messages.join(' · ')||'check installed models'}`;
 el('readiness').classList.toggle('bad',!read);document.querySelector('.verify-chip')?.classList.toggle('unavailable',!read);if(document.querySelector('.verify-chip'))document.querySelector('.verify-chip').lastChild.textContent=read?' On-device':' Setup needed';if(!read)toast('Install or start the required local models. Check the setup README.');
 }catch(e){el('readiness').textContent='● Backend unavailable';el('readiness').classList.add('bad');document.querySelector('.verify-chip')?.classList.add('unavailable');if(document.querySelector('.verify-chip'))document.querySelector('.verify-chip').lastChild.textContent=' Offline';}}
function init(){
 state.responseMode='auto';
 loadCourses().then(loadDocs);loadChats();updateScopeUI();
 const storedModel=localStorage.getItem('proofnotes_model');if(storedModel && [...el('model-select').options].some(o=>o.value===storedModel)){el('model-select').value=storedModel;}
 el('model-select').onchange=()=>{localStorage.setItem('proofnotes_model',el('model-select').value);checkReadiness()};checkReadiness();
 el('brand-home').onclick=clearChat;el('home-btn').onclick=clearChat;el('new-chat').onclick=newConversation;el('chat-scope').onclick=openScope;el('close-scope').onclick=closeScope;el('scope-modal').onclick=e=>{if(e.target===el('scope-modal'))closeScope()};el('save-scope').onclick=saveScope;el('mobile-menu').onclick=()=>{const open=!el('sidebar').classList.contains('open');el('sidebar').classList.toggle('open',open);el('mobile-scrim').hidden=!open;el('mobile-menu').setAttribute('aria-expanded',String(open))};el('mobile-scrim').onclick=closeSidebar;
 el('home-manage-sources').onclick=openSources;el('sidebar-add-course').onclick=async()=>{await openSources();el('course-name')?.focus()};el('home-start-chat').onclick=newConversation;el('home-add-notes').onclick=showModal;el('add-doc').onclick=showModal;el('upload-primary').onclick=e=>{e.stopPropagation();showModal()};
 el('dropzone').onclick=showModal;el('dropzone').onkeydown=e=>{if(e.target===el('dropzone')&&(e.key==='Enter'||e.key===' ')){e.preventDefault();showModal()}};
 el('close-upload').onclick=hideModal;el('upload-modal').onclick=e=>{if(e.target===el('upload-modal'))hideModal()};
 el('choose-files').onclick=()=>el('file-input').click();el('file-input').onchange=e=>uploadFiles([...e.target.files]);
 for(const evt of ['dragenter','dragover'])el('dropzone').addEventListener(evt,e=>{e.preventDefault();el('dropzone').classList.add('dragover')});
 for(const evt of ['dragleave','drop'])el('dropzone').addEventListener(evt,e=>{e.preventDefault();el('dropzone').classList.remove('dragover')});
 el('dropzone').addEventListener('drop',e=>uploadFiles([...e.dataTransfer.files]));
 el('ask-form').onsubmit=e=>{e.preventDefault();ask(el('question').value)};
 el('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask(el('question').value)}};
 document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if(el('chat').hidden)newConversation();else el('question').focus()}if(e.key==='Escape'){hideModal();closeScope();el('source-panel').hidden=true;closeSidebar()}});
 document.addEventListener('click',async e=>{
  const course=e.target.closest('[data-home-course]');if(course){newConversation(course.dataset.homeCourse);return;}
  const open=e.target.closest('[data-open-chat]');if(open){await openChat(open.dataset.openChat);return;}
  const removeChat=e.target.closest('[data-delete-chat]');if(removeChat){if(confirm('Delete this conversation and all its messages? (Notes stay untouched.)')){await api(`/api/chats/${removeChat.dataset.deleteChat}`,{method:'DELETE'});if(state.chatId===removeChat.dataset.deleteChat)newConversation();await loadChats();}return;}
  const example=e.target.closest('[data-question]');if(example)ask(example.dataset.question);
  const cite=e.target.closest('[data-sid]');if(cite){const src=(state.sourceMap[Number(cite.dataset.msg)]||[]).find(s=>s.id===cite.dataset.sid);if(src)openSource(src)}
  const next=e.target.closest('[data-next]');if(next)ask(next.dataset.next);
  const del=e.target.closest('[data-delete]');if(del&&confirm('Remove this document and its search index?')){try{await api(`/api/documents/${del.dataset.delete}`,{method:'DELETE'});await loadDocs();toast('Document removed.')}catch(err){toast(err.message)}}
 });
 el('close-source').onclick=()=>el('source-panel').hidden=true;
 el('sources-btn').onclick=openSources;el('gap-btn').onclick=runGaps;el('recall-btn').onclick=openRecall;el('claim-btn').onclick=openClaim;el('lens-btn').onclick=openLens;
 document.querySelectorAll('[data-action]').forEach(btn=>btn.onclick=()=>({lens:openLens,radar:runGaps,recall:openRecall,claim:openClaim}[btn.dataset.action]||openLens)());
 document.addEventListener('click',e=>{const action=e.target.closest('[data-recall]');if(action)recallAction(action.dataset.recall)});
}
init();
