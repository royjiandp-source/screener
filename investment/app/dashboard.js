(() => {
  const $ = id => document.getElementById(id);
  const chosen = new Set();
  const offsets = {observation:0, value:0};
  const pages = {observation:null, value:null};
  const marketNames = {KR:'한국',SG:'싱가포르',US:'미국'};
  const initial = new URLSearchParams(location.search);
  offsets.observation = Number(initial.get('observation_offset') || 0);
  offsets.value = Number(initial.get('value_offset') || 0);
  let job = null, timer = null, revision = 0, refreshingCatalog = false;
  try { job = localStorage.getItem('two-track-job'); } catch (_) {}
  const status = message => { $('global-state').textContent = message; };
  const fmt = (v, unit='') => v == null ? '미확인' : typeof v === 'number' ? v.toLocaleString(undefined,{maximumFractionDigits:2})+unit : String(v);
  async function request(url, options) {
    const r = await fetch(url, options);
    const j = await r.json();
    if (!r.ok) throw Error(typeof j.detail === 'string' ? j.detail : '자료·입력·연결 상태를 확인하세요.');
    return j;
  }
  const post = (url, body) => request(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function params() { return {market:$('market').value || null,query:$('sector-query').value,min_score:Number($('min-score').value)}; }
  async function refresh() {
    const mine = ++revision, p = params();
    const q = new URLSearchParams({query:p.query,min_score:p.min_score,observation_offset:offsets.observation,value_offset:offsets.value});
    if(p.market) q.set('market',p.market);
    try {
      const r = await request('api/report?'+q);
      if(mine!==revision) return;
      for (const [id,key] of [['observation-body','observations'],['value-body','values'],['coverage','coverage']]) $(id).innerHTML = r.fragments[key];
      document.querySelectorAll('[data-listing]').forEach(el => { el.checked=chosen.has(el.dataset.listing); });
      const sources=Object.entries(r.coverage).filter(([market])=>!p.market||market===p.market);
      const running=sources.some(([,source])=>source.status==='refreshing');
      const failed=sources.some(([,source])=>['connection_unavailable','source_error'].includes(source.status));
      if(refreshingCatalog){status(running?'목록 갱신 중':failed?'목록 갱신 실패 · 이전 자료는 보존했습니다.':'목록 갱신 완료 · 현재 목록 범위를 확인하세요.');if(!running)refreshingCatalog=false;}
      pages.observation=r.observations; pages.value=r.value_candidates;
      for(const track of ['observation','value']) {
        const page=pages[track],start=page.total ? page.offset+1 : 0,end=Math.min(page.offset+page.limit,page.total);
        $(track+'-summary').textContent=`현재 표시 ${page.items.length.toLocaleString()}개 / ${track==='observation'?'검색 결과':'기준 충족'} ${page.total.toLocaleString()}개`;
        $(track+'-count').textContent=`${start}–${end} / ${page.total.toLocaleString()}개`;
        document.querySelectorAll(`[data-page="${track}"]`).forEach(b => { b.disabled=Number(b.dataset.direction)<0 ? page.offset===0 : page.offset+page.limit>=page.total; });
      }
      const url=new URL(location.href); url.search=q.toString(); history.replaceState(null,'',url);
    } catch(e) { status(e.message); }
  }
  async function poll() {
    if(!job) return;
    try {
      const j=await request('api/discovery/jobs/'+encodeURIComponent(job));
      const names={queued:'대기',running:'분석 중',completed:'완료',cancelled:'취소',interrupted:'중단',error:'실패'};
      $('job-state').textContent=`${names[j.state]||j.state} · 처리 ${j.completed+j.failed}/${j.total} · 수집·계산 실패 ${j.failed}`;
      $('cancel-job').disabled=!['queued','running'].includes(j.state);
      $('resume-job').hidden=j.state!=='interrupted';
      if(['completed','cancelled','error','interrupted'].includes(j.state)) {
        clearInterval(timer); timer=null; await refresh();
      }
    } catch(e) { $('job-state').textContent=e.message; clearInterval(timer);timer=null; }
  }
  async function start(url,body) {
    const r=await post(url,body);job=r.id;
    try { localStorage.setItem('two-track-job',job); } catch(_) {}
    $('job-state').textContent=r.note||'작업을 시작했습니다.';
    clearInterval(timer); timer=setInterval(poll,3000); await poll();
  }
  function catchAction(fn) { return async e => { try { await fn(e); } catch(err) {status(err.message);} }; }
  $('market-form').onsubmit=catchAction(async e=>{e.preventDefault();offsets.observation=0;offsets.value=0;chosen.clear();$('funds-panel').replaceChildren();await refresh();});
  $('sector-form').onsubmit=catchAction(async e=>{e.preventDefault();offsets.observation=0;chosen.clear();await refresh();});
  $('value-form').onsubmit=catchAction(async e=>{e.preventDefault();offsets.value=0;await refresh();});
  $('evaluate-market').onclick=catchAction(()=>start('api/discovery/evaluate-market',{market:params().market}));
  $('enrich-all').onclick=catchAction(()=>start('api/discovery/enrich',{query:params().query,market:params().market}));
  $('enrich-selected').onclick=catchAction(()=>start('api/discovery/enrich',{listing_ids:[...chosen]}));
  $('evaluate-selected').onclick=catchAction(()=>start('api/discovery/evaluate',{listing_ids:[...chosen]}));
  $('cancel-job').onclick=catchAction(async()=>{await post('api/discovery/jobs/'+job+'/cancel',{});$('job-state').textContent='취소 요청됨 · 진행 중인 종목 처리 후 반영됩니다.';});
  $('resume-job').onclick=catchAction(async()=>{await post('api/discovery/jobs/'+job+'/resume',{});clearInterval(timer);timer=setInterval(poll,3000);await poll();});
  $('catalog-refresh').onclick=catchAction(async()=>{
    const market=params().market;if(!market) throw Error('목록을 갱신할 시장을 선택하세요.');
    const r=await post('api/discovery/refresh?market='+market,{});
    status(r.started ? '목록 갱신 중 · 새 목록이 확보되면 상태가 바뀝니다.' : r.reason);
    if(r.started){refreshingCatalog=true;setTimeout(refresh,3000);}
  });
  async function loadFunds(offset=0) {
    const p=params(),q=new URLSearchParams({query:p.query,offset,limit:20});if(p.market)q.set('market',p.market);
    const r=await request('api/discovery/funds?'+q),box=$('funds-panel');box.replaceChildren();
    const heading=document.createElement('p');heading.textContent=`관련 ETF ${r.total}개 · 표시 ${r.total?offset+1:0}–${Math.min(offset+r.limit,r.total)}개 · 구성·NAV는 자금 유입을 의미하지 않습니다.`;box.append(heading);
    const list=document.createElement('div');list.className='funds-list';
    for(const fund of r.items){
      const item=document.createElement('div');item.className='fund-item';
      const label=document.createElement('label'),cb=document.createElement('input');cb.type='checkbox';cb.dataset.listing=fund.listing.id;cb.checked=chosen.has(fund.listing.id);
      label.append(cb,document.createTextNode(`${marketNames[fund.listing.market]} · ${fund.listing.name} (${fund.listing.ticker})`));item.append(label);
      const info=document.createElement('small');info.textContent=fund.flows.map(f=>`${f.kind} · ${f.period} · ${f.data.source}`).join(' / ')||'자료 미수집';item.append(info);
      const b=document.createElement('button');b.className='text-button';b.type='button';b.dataset.detail=fund.listing.id;b.textContent='ETF 상세';item.append(b);list.append(item);
    }box.append(list);
    for(const [name,next,disabled] of [['ETF 이전',Math.max(0,offset-r.limit),offset===0],['ETF 다음',offset+r.limit,offset+r.limit>=r.total]]){const b=document.createElement('button');b.textContent=name;b.className='secondary';b.disabled=disabled;b.onclick=catchAction(()=>loadFunds(next));box.append(b);}
  }
  $('show-funds').onclick=catchAction(()=>loadFunds());
  $('manager-refresh').onclick=catchAction(async()=>{
    status('미국 기관 분기 공시를 수집하고 있습니다.');
    const r=await post('api/discovery/institution/sec13f?manager_cik='+encodeURIComponent($('manager-cik').value),{});
    status(r.note||r.status);await refresh();
  });
  $('import-data').onclick=catchAction(async()=>{
    const file=$('data-import').files[0];if(!file)throw Error('자료 파일을 선택하세요.');if(file.size>10000000)throw Error('자료 파일을 10MB 이하로 나누어 주세요.');
    const body=JSON.parse(await file.text());await post(body.kind?'api/discovery/flows/import':'api/discovery/import',body);
    status('자료를 저장했습니다.');await refresh();
  });
  async function showDetail(id) {
    const d=await request('api/discovery/detail?listing_id='+encodeURIComponent(id));
    const box=$('detail-panel');box.hidden=false;box.replaceChildren();
    const close=document.createElement('button');close.textContent='상세 닫기';close.className='secondary';close.onclick=()=>{box.hidden=true;};box.append(close);
    const h=document.createElement('h3');h.textContent=d.listing.name+' · '+d.listing.ticker;box.append(h);
    const dl=document.createElement('dl');const field=(k,v)=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=v==null?'미확인':typeof v==='object'?JSON.stringify(v):String(v);dl.append(dt,dd);};
    field('분석일',d.analysis_day);field('관찰 점수',d.leadership.score);field('점수 보류 사유',d.leadership.missing.join(' · '));field('관찰 기준일',d.leadership.as_of);field('비교 ETF',d.leadership.benchmark);
    for(const [k,v]of Object.entries(d.leadership.signals||{}))field(k,fmt(v));
    for(const c of d.institution_changes||[]){field('기관·기준 분기',`${c.manager} · ${c.previous_quarter||'이전 분기 미확인'} → ${c.quarter}`);field('보유 주식 수 변화',fmt(c.shares_change,'주'));field('보유 가치 변화',fmt(c.value_change,' '+c.currency));}
    for(const f of d.flows||[]){field('자료 종류·기준일',f.kind+' · '+f.period);field('출처·공개 시각',f.data.source+' · '+f.available_at);for(const [k,v] of Object.entries(f.data))if(k!=='source')field(k,v);}
    if(!(d.flows||[]).length)field('관찰·ETF·기관 자료','미수집');box.append(dl);
    if(d.listing.market==='KR'&&d.listing.type!=='etf'){
      const b=document.createElement('button');b.textContent='최근 30일 기관 순매수 수집';b.onclick=catchAction(async()=>{
        const end=new Date(),start=new Date(end);start.setDate(start.getDate()-30);
        const q=new URLSearchParams({listing_id:id,start:start.toISOString().slice(0,10),end:end.toISOString().slice(0,10)});
        const r=await post('api/discovery/institution/refresh?'+q,{});status(r.note||r.status);await showDetail(id);await refresh();
      });box.append(b);
    }box.scrollIntoView({block:'start'});
  }
  document.addEventListener('change',e=>{if(e.target.matches('[data-listing]')){const id=e.target.dataset.listing;e.target.checked?chosen.add(id):chosen.delete(id);}});
  document.addEventListener('click',catchAction(async e=>{
    const detail=e.target.closest('[data-detail]');if(detail)await showDetail(detail.dataset.detail);
    const page=e.target.closest('[data-page]');if(page){const track=page.dataset.page;offsets[track]=Math.max(0,offsets[track]+Number(page.dataset.direction)*pages[track].limit);await refresh();}
  }));
  refresh();if(job){timer=setInterval(poll,3000);poll();}
  // Skip background refresh while the user reads a company detail or the detail panel.
  const reading=()=>document.querySelector('details.company[open]')||!$('detail-panel').hidden;
  setInterval(()=>{if(!document.hidden&&!timer&&!reading())refresh();},30000);
})();
