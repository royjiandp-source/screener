document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{
    document.querySelectorAll('[data-tab]').forEach(tab=>{
      const selected=tab===button;
      tab.setAttribute('aria-pressed',String(selected));
      document.getElementById(tab.dataset.tab).hidden=!selected;
    });
  }));
});
