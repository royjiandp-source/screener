document.addEventListener('DOMContentLoaded', () => {
  const rows=JSON.parse(document.getElementById('static-results').textContent);
  const input=document.getElementById('sector-query'), market=document.getElementById('static-market');
  const aliases={'반도체':'semiconductor','인공지능':'artificial intelligence','전력':'power','원전':'nuclear','보안':'security','클라우드':'cloud','데이터센터':'data center','로봇':'robot','바이오':'biotech'};
  let offset=0,matched=[];
  const fold=x=>String(x||'').toLowerCase();
  const includes=(s,q)=>fold(s).includes(q);
  function update(reset=true) {
    if(reset)offset=0;
    const q=fold(input.value.trim()), terms=[q,aliases[q]].filter(Boolean);
    const direct=rows.filter(r=>(!market.value||r.market===market.value)&&q&&(includes(r.name,q)||fold(r.ticker)===q||fold(r.code)===q));
    const peers=new Set(direct.flatMap(r=>r.industries.map(l=>r.market+'|'+l)));
    matched=rows.filter(r=>(!market.value||r.market===market.value)&&(!q||terms.some(t=>includes(r.name,t)||includes(r.ticker,t)||r.labels.some(l=>includes(l,t))||includes(r.evidence,t))||r.industries.some(l=>peers.has(r.market+'|'+l))));
    const own=new Set(direct.map(r=>r.id));matched.sort((a,b)=>Number(own.has(b.id))-Number(own.has(a.id)));
    document.getElementById('observation-body').innerHTML=matched.slice(offset,offset+50).map(r=>r.html).join('')||'<tr><td colspan="12">조건에 맞고 가격이 확인된 종목이 없습니다.</td></tr>';
    document.getElementById('observation-summary').textContent=`현재 표시 ${Math.min(50,Math.max(0,matched.length-offset))}개 / 검색 결과 ${matched.length}개 · 가격 하한 충족·가격 확인 종목 기준`;
    document.getElementById('static-prev').disabled=offset===0;
    document.getElementById('static-next').disabled=offset+50>=matched.length;
  }
  document.getElementById('sector-form').addEventListener('submit',e=>{e.preventDefault();update();});
  input.addEventListener('input',()=>update());market.addEventListener('change',()=>update());
  document.getElementById('static-prev').addEventListener('click',()=>{offset=Math.max(0,offset-50);update(false);});
  document.getElementById('static-next').addEventListener('click',()=>{offset+=50;update(false);});
  update();
});
