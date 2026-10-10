document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('[data-tab]').forEach(tab=>{
      const selected=tab===button;
      tab.setAttribute('aria-pressed',String(selected));
      document.getElementById(tab.dataset.tab).hidden=!selected;
    });
  }));
});
document.addEventListener('DOMContentLoaded',()=>{
  const dialog=document.createElement('dialog');
  dialog.className='evidence-dialog';
  dialog.setAttribute('aria-labelledby','evidence-dialog-title');
  dialog.innerHTML='<header class="evidence-dialog-header"><h2 id="evidence-dialog-title"></h2><button type="button" class="secondary" aria-label="상세 근거 닫기">닫기</button></header><div class="evidence-dialog-body"></div>';
  document.body.append(dialog);
  let opener=null,previousOverflow='';
  dialog.querySelector('button').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{
    if(event.target!==dialog)return;
    const rect=dialog.getBoundingClientRect();
    if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();
  });
  dialog.addEventListener('close',()=>{
    document.body.style.overflow=previousOverflow;
    dialog.querySelector('.evidence-dialog-body').replaceChildren();
    if(opener?.isConnected)opener.focus();
  });
  const desktop=window.matchMedia('(min-width:761px)');
  const expanded=new Map();
  function closeInline(summary) {
    expanded.get(summary)?.remove();expanded.delete(summary);
    summary.setAttribute('aria-expanded','false');
  }
  desktop.addEventListener('change',()=>{
    for(const summary of expanded.keys())closeInline(summary);
    if(dialog.open)dialog.close();
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!dialog.open)for(const summary of expanded.keys())closeInline(summary);
  });
  document.addEventListener('click',event=>{
    const summary=event.target.closest('details.evidence > summary');
    if(!summary)return;
    const details=summary.parentElement;
    if(desktop.matches) {
      event.preventDefault();
      if(expanded.has(summary)){closeInline(summary);return;}
      const parent=details.closest('tr');
      const row=document.createElement('tr');row.className='inline-evidence-row';
      const cell=document.createElement('td');cell.colSpan=parent.cells.length;
      const panel=document.createElement('div');panel.className='inline-evidence-panel';
      const header=document.createElement('header');header.className='evidence-dialog-header';
      const title=document.createElement('h2');title.textContent=(parent.querySelector('strong')?.textContent||'기업')+' · 상세 근거';
      const close=document.createElement('button');close.type='button';close.className='secondary';close.textContent='접기';
      close.addEventListener('click',()=>{closeInline(summary);summary.focus();});
      header.append(title,close);
      const body=document.createElement('div');body.className='inline-evidence-body';
      [...details.children].filter(child=>child!==summary).forEach(child=>body.append(child.cloneNode(true)));
      panel.append(header,body);cell.append(panel);row.append(cell);parent.after(row);
      expanded.set(summary,row);summary.setAttribute('aria-expanded','true');
      return;
    }
    if(typeof dialog.showModal!=='function')return;
    event.preventDefault();opener=summary;
    dialog.querySelector('h2').textContent=(details.closest('tr')?.querySelector('strong')?.textContent||'기업')+' · 상세 근거';
    const body=dialog.querySelector('.evidence-dialog-body');body.replaceChildren();
    [...details.children].filter(child=>child!==summary).forEach(child=>body.append(child.cloneNode(true)));
    previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
    dialog.showModal();body.scrollTop=0;
  });
});
