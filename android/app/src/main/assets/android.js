'use strict';

const main = document.querySelector('#main');
const monthNames = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
const dayNames = ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
const pad = value => String(value).padStart(2,'0');
const today = () => {const d=new Date();return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;};
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const hours = minutes => String(minutes/60).replace('.',',');
const money = cents => (cents/100).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €';
const rateInput = cents => (cents/100).toFixed(2).replace('.',',');
const label = month => `${monthNames[Number(month.slice(5))-1]} de ${month.slice(0,4)}`;
const capital = text => text.charAt(0).toUpperCase()+text.slice(1);
const dayLabel = day => {const [y,m,d]=day.split('-').map(Number);return `${dayNames[new Date(y,m-1,d).getDay()]}, ${d} de ${monthNames[m-1]} de ${y}`;};
const options = selected => Array.from({length:48},(_,i)=>{const n=(i+1)*30;return `<option value="${n}" ${n===selected?'selected':''}>${hours(n)} h</option>`;}).join('');
const quick = {};
let lastMonth=null;
let toastTimer;

function call(action, values={}) {
  if (!window.HorasNative) throw new Error('Abre Horas desde la aplicación Android para acceder a tus registros.');
  const result=JSON.parse(window.HorasNative.call(JSON.stringify({action,...values})));
  if (!result.ok) throw new Error(result.error || 'No se ha podido completar la acción.');
  return result.data;
}
function toast(message) {
  const el=document.querySelector('#toast');el.textContent=message;el.hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>{el.hidden=true;},6000);
}
function navigate(route) {
  if(location.hash==='#'+route) render(); else location.hash=route;
}
function route() {
  const [path,query]=(location.hash.slice(1)||'/calendar').split('?');
  return {path,params:new URLSearchParams(query||'')};
}
function monthRoute(month){return '/calendar?month='+encodeURIComponent(month);}
function entryRoute(day){return '/entry?day='+encodeURIComponent(day);}
function adjacent(month,delta){const [y,m]=month.split('-').map(Number),d=new Date(y,m-1+delta,1);return `${d.getFullYear()}-${pad(d.getMonth()+1)}`;}
function badge(paid){return `<span class="badge ${paid?'paid':''}">${paid?'✓ Cobrado':'◷ Pendiente'}</span>`;}
function render() {
  const {path,params}=route();
  document.querySelectorAll('[data-nav]').forEach(link=>{
    const selected=link.dataset.nav===(path==='/entry'?'calendar':path.slice(1));
    if(selected)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  try {
    if(path==='/settings') main.innerHTML=settingsPage();
    else if(path==='/history') main.innerHTML=historyPage(Number(params.get('year')||new Date().getFullYear()));
    else if(path==='/entry') main.innerHTML=entryPage(params.get('day')||today());
    else main.innerHTML=calendarPage(params.get('month')||today().slice(0,7));
    document.title='Horas · Cálculo de horas mensuales';
  } catch(error) {
    main.innerHTML=`<section class="panel narrow error-page"><h1>No se ha podido completar.</h1><p role="alert">${esc(error.message)}</p><a class="button primary" href="#/calendar">Volver al calendario</a></section>`;
  }
}

function calendarPage(month) {
  const data=call('month',{month});lastMonth=data;
  const minutes=quick[month]||data.prefs.default_minutes;
  const entries=new Map(data.entries.map(item=>[item.day,item]));
  const [y,m]=month.split('-').map(Number),first=(new Date(y,m-1,1).getDay()+6)%7,days=new Date(y,m,0).getDate();
  const cells=[];
  for(let index=0;index<Math.ceil((first+days)/7)*7;index++) {
    const n=index-first+1;
    if(n<1||n>days){cells.push('<div class="calendar-cell outside" aria-hidden="true"></div>');continue;}
    const day=`${month}-${pad(n)}`,item=entries.get(day),isToday=day===today();
    const cellClass=`calendar-cell ${item?'recorded':''} ${isToday?'today':''} ${index%7>=5?'weekend':''}`;
    const number=`<span class="day-number">${n}</span>`;
    if(item) cells.push(`<div class="${cellClass}"><a class="day-content" href="#${entryRoute(day)}" aria-label="Editar ${dayLabel(day)}: ${hours(item.minutes)} horas" ${isToday?'aria-current="date"':''}>${number}<span class="day-hours">${hours(item.minutes)}<small> h</small></span><span class="day-note">${item.note?'<span class="note-dot" aria-hidden="true"></span>':''}<span class="desktop-only"> ${esc(item.note.slice(0,18)||'Registrado')}</span></span></a></div>`);
    else cells.push(`<div class="${cellClass}"><button class="day-content empty-day" data-action="quick" data-day="${day}" data-minutes="${minutes}" aria-label="Registrar ${hours(minutes)} horas el ${dayLabel(day)}" ${isToday?'aria-current="date"':''}>${number}<span class="day-add" aria-hidden="true">＋</span></button></div>`);
  }
  const prev=adjacent(month,-1),next=adjacent(month,1);
  const records=data.entries.slice().reverse().map(item=>`<a class="record-row" href="#${entryRoute(item.day)}"><span class="record-date">${item.day.slice(8)}<small>${label(month)}</small></span><span class="record-note">${esc(item.note||'Sin nota')}</span><strong>${hours(item.minutes)} h</strong><span class="muted" aria-hidden="true">→</span></a>`).join('');
  return `<div class="page-heading"><div><h1>Cálculo de horas mensuales</h1><p class="muted">Toca el calendario y agrega las horas.</p></div><a class="button primary" href="#${entryRoute(today().slice(0,7)===month?today():month+'-01')}">＋ Añadir registro</a></div>
    ${data.rate_cents===0?'<div class="notice" role="status">La tarifa de este mes está a 0 €/h. <a href="#month-rate" data-action="focus-rate"><strong>Configúrala aquí</strong></a> para calcular lo que has ganado.</div>':''}
    <section class="stats" aria-label="Resumen del mes"><div class="stat"><span class="stat-label">HORAS DEL MES <span aria-hidden="true">◷</span></span><strong>${hours(data.minutes)}<small> h</small></strong><span class="stat-caption">${data.days} ${data.days===1?'día registrado':'días registrados'}</span></div><div class="stat"><span class="stat-label">TARIFA POR HORA <span aria-hidden="true">€</span></span><strong>${money(data.rate_cents)}</strong><button class="stat-caption text-link" data-action="focus-rate">Cambiar tarifa de este mes ↓</button></div><div class="stat total-stat"><span class="stat-label">ACUMULADO DEL MES <span aria-hidden="true">€</span></span><strong>${money(data.total)}</strong><span class="stat-caption">${data.paid?'✓ Marcado como cobrado':data.days?'Pendiente de cobro':'Todo empieza con el primer día'}</span></div></section>
    <div class="calendar-layout"><section class="panel calendar-panel" aria-label="Calendario mensual"><div class="calendar-heading"><div class="month-heading"><h2>${capital(label(month))}</h2><span class="small muted">Selecciona un día para anotar tus horas</span></div><div class="month-navigation">${prev>='2000-01'?`<a class="icon-button" href="#${monthRoute(prev)}" aria-label="Mes anterior">‹</a>`:''}<a class="button compact" href="#/calendar">Hoy</a>${next<='2100-12'?`<a class="icon-button" href="#${monthRoute(next)}" aria-label="Mes siguiente">›</a>`:''}</div></div>
    <div class="quick-controls"><label for="quick-hours"><span class="quick-dot" aria-hidden="true"></span>Registro rápido</label><select id="quick-hours" data-month="${month}" aria-describedby="quick-help">${options(minutes)}</select><span id="quick-help" class="small muted">Toca un día vacío para guardar ${hours(minutes)} h.</span></div><div class="calendar-weekdays" aria-hidden="true">${['LUN','MAR','MIÉ','JUE','VIE','SÁB','DOM'].map(d=>`<span>${d}</span>`).join('')}</div><div class="calendar-grid">${cells.join('')}</div><div class="calendar-footer"><span><i class="legend-dot" aria-hidden="true"></i> Día registrado</span><span class="muted">Toca un registro para editarlo.</span></div></section>
    <aside class="month-sidebar"><section class="panel balance-panel"><p class="eyebrow">LAS CUENTAS DEL MES</p><h2>${capital(label(month))}</h2><div class="calculation"><span>${hours(data.minutes)} h</span><span>×</span><span>${money(data.rate_cents)}/h</span></div><p class="balance-total">${money(data.total)}</p>${badge(data.paid)}${data.days?`<div class="paid-form"><button class="button full" data-action="paid">${data.paid?'Marcar como pendiente':'✓ Marcar como cobrado'}</button></div>`:''}<button class="export-link" data-action="csv" data-month="${month}">↓ Descargar mes en CSV</button></section>
    <section class="panel rate-panel" id="month-rate"><h2>Tarifa de este mes</h2><p class="small muted">Solo se aplica a ${label(month)}.</p><form id="rate-form" data-month="${month}"><label for="month-rate-input">Euros por hora</label><div class="rate-input"><input id="month-rate-input" name="rate" type="text" inputmode="decimal" value="${rateInput(data.rate_cents)}" required><span>€/h</span></div><button class="button full" type="submit">Guardar tarifa</button><p class="form-error" role="alert"></p></form></section><div class="tip"><span aria-hidden="true">＋</span><p><strong>A tu ritmo.</strong> Cambia las horas habituales en <a href="#/settings">Ajustes</a>. Los días que ya has guardado se conservan.</p></div></aside></div>
    <section class="panel records-panel"><div class="section-heading"><h2>Registros del mes <span class="count">${data.days}</span></h2><span class="small muted">${hours(data.minutes)} h en total</span></div>${records?'<div class="records-list">'+records+'</div>':'<div class="empty-state"><span aria-hidden="true">◷</span><h3>Tu mes empieza aquí</h3><p>Toca un día del calendario para guardar tus primeras horas.</p></div>'}</section>`;
}

function entryPage(day) {
  const item=call('entry',{day}),prefs=call('preferences');
  const minutes=item?item.minutes:prefs.default_minutes;
  return `<div class="narrow"><a class="back-link" href="#${monthRoute(day.slice(0,7))}">← Volver al calendario</a><div class="page-heading"><div><p class="eyebrow">UN DÍA A LA VEZ</p><h1>${item?'Editar':'Añadir'} registro</h1><p class="muted">${capital(dayLabel(day))}</p></div></div><section class="panel"><form id="entry-form" data-revision="${item?item.revision:0}">
    ${item?`<input type="hidden" name="day" value="${day}">`:`<label for="entry-day">Día</label><input id="entry-day" type="date" name="day" min="2000-01-01" max="2100-12-31" value="${day}" required>`}
    <label for="entry-hours">Horas trabajadas</label><div class="hours-control"><button class="icon-button" type="button" data-action="step" data-step="-0.5" aria-label="Restar media hora">−</button><input id="entry-hours" name="hours" type="number" inputmode="decimal" min="0.5" max="24" step="0.5" value="${minutes/60}" required aria-describedby="hours-help"><button class="icon-button" type="button" data-action="step" data-step="0.5" aria-label="Añadir media hora">＋</button><span>horas</span></div><p id="hours-help" class="small muted">En intervalos de media hora. Por ejemplo: 1,5 h.</p><div class="presets" aria-label="Cantidades habituales">${[.5,1,1.5,2,3,4,8].map(n=>`<button type="button" class="preset" data-action="preset" data-hours="${n}" aria-pressed="${n===minutes/60}">${String(n).replace('.',',')} h</button>`).join('')}</div><label for="entry-note">Nota <span class="optional">opcional</span></label><textarea id="entry-note" name="note" rows="3" maxlength="500" placeholder="Algo que quieras recordar de este día…">${esc(item?item.note:'')}</textarea><p class="field-help">La tarifa se calcula con el mes de la fecha elegida. Puedes ajustarla desde su calendario.</p><p class="form-error" role="alert"></p><div class="form-actions"><a class="button" href="#${monthRoute(day.slice(0,7))}">Cancelar</a><button class="button primary" type="submit">Guardar registro</button></div></form></section>
    ${item?`<details class="danger-zone"><summary>Eliminar este registro</summary><p class="small">Se eliminarán las ${hours(minutes)} h de este día.</p><button class="button danger" data-action="delete" data-day="${day}" data-revision="${item.revision}">Confirmar eliminación</button></details>`:''}</div>`;
}

function historyPage(year) {
  const months=call('history',{year});
  const minutes=months.reduce((s,m)=>s+m.minutes,0),total=months.reduce((s,m)=>s+m.total,0),pending=months.reduce((s,m)=>s+(m.paid?0:m.total),0);
  return `<div class="page-heading"><div><p class="eyebrow">MES A MES</p><h1>Tus horas, con perspectiva.</h1><p class="muted">Lo que has trabajado y lo que has ganado.</p></div><form id="year-form" class="year-picker"><label for="year">Año</label><input id="year" name="year" type="number" min="2000" max="2100" value="${year}" required><button class="button" type="submit">Ver</button></form></div><section class="stats" aria-label="Resumen del año"><div class="stat"><span class="stat-label">HORAS EN ${year}</span><strong>${hours(minutes)}<small> h</small></strong><span class="stat-caption">La suma de todo el año</span></div><div class="stat"><span class="stat-label">PENDIENTE DE COBRO</span><strong>${money(pending)}</strong><span class="stat-caption">Meses sin marcar como cobrados</span></div><div class="stat total-stat"><span class="stat-label">ACUMULADO DEL AÑO</span><strong>${money(total)}</strong><span class="stat-caption">Cada mes con su propia tarifa</span></div></section><section class="panel history-panel"><div class="section-heading"><h2>Los 12 meses de ${year}</h2><span class="small muted">Abre un mes para ver sus registros</span></div><div class="table-scroll"><table><caption class="sr-only">Horas y remuneración de cada mes de ${year}</caption><thead><tr><th scope="col">Mes</th><th scope="col">Días</th><th scope="col">Horas</th><th scope="col">Tarifa / h</th><th scope="col">Acumulado</th><th scope="col">Estado</th></tr></thead><tbody>${months.map(m=>`<tr class="${m.days?'':'no-records'}"><th scope="row"><a href="#${monthRoute(m.month)}">${capital(label(m.month))}</a></th><td>${m.days}</td><td>${hours(m.minutes)} h</td><td>${m.days?money(m.rate_cents):'—'}</td><td><strong>${money(m.total)}</strong></td><td>${m.days?badge(m.paid):'<span class="small muted">Sin registros</span>'}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total del año</th><td></td><td>${hours(minutes)} h</td><td></td><td>${money(total)}</td><td></td></tr></tfoot></table></div></section>`;
}

function settingsPage() {
  const prefs=call('preferences');
  return `<div class="page-heading"><div><p class="eyebrow">A TU MANERA</p><h1>Pequeños ajustes. Menos pasos.</h1><p class="muted">Deja tus valores habituales preparados para la próxima vez.</p></div></div><p class="offline-note">Tus datos se guardan en este dispositivo. Horas funciona sin conexión, sin servidor y sin contraseña.</p><div class="settings-grid"><section class="panel"><div class="section-heading"><h2>Tus valores habituales</h2><span class="section-icon" aria-hidden="true">≡</span></div><form id="prefs-form"><label for="default-hours">Horas por defecto</label><select id="default-hours" name="minutes">${options(prefs.default_minutes)}</select><p class="field-help">La cantidad inicial del registro rápido. Los días guardados no cambian.</p><label for="default-rate">Tarifa habitual (€/hora)</label><input id="default-rate" name="rate" type="text" inputmode="decimal" value="${rateInput(prefs.default_rate_cents)}" required><p class="field-help">Se aplica al primer registro de cada mes nuevo. Los meses ya iniciados conservan su tarifa.</p><button class="button primary" type="submit">Guardar preferencias</button><p class="form-error" role="alert"></p></form></section>
    <div class="settings-stack"><section class="panel"><h2>Tus datos, contigo</h2><p class="muted">Guarda una copia de todos los meses, horas, notas y preferencias en una carpeta que elijas.</p><button class="button" data-action="backup">↓ Guardar copia JSON</button><p class="field-help">Compatible con las copias de Horas para servidor. Puedes pasar tus registros de una versión a otra, sin sincronización automática.</p><details class="restore-details"><summary>Restaurar una copia</summary><p class="small">Sustituye todos los registros y preferencias de este dispositivo. Antes de restaurar, se conserva una copia de los datos actuales. El límite es de 2 MB.</p><button class="button danger" data-action="import">Seleccionar copia JSON</button></details>${prefs.has_previous_backup?'<button class="button" data-action="previous">↓ Guardar copia anterior a la restauración</button>':''}</section><section class="panel"><h2>Solo en este dispositivo</h2><p class="muted">Los registros se guardan en una base SQLite privada. La aplicación no solicita acceso a Internet ni usa cuentas o contraseñas.</p><p class="field-help">Desinstalar Horas o borrar sus datos elimina los registros locales. Guarda una copia JSON antes si quieres conservarlos.</p><p class="small muted">Android 8.0 o posterior · Versión 1.0.0</p></section></div></div>`;
}

document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]');if(!button)return;
  event.preventDefault();
  try {
    const action=button.dataset.action;
    if(action==='quick') {
      const day=button.dataset.day,created=call('quick',{day,minutes:Number(button.dataset.minutes)});
      if(!created){navigate(entryRoute(day));return;}
      render();toast(`Guardado: ${hours(Number(button.dataset.minutes))} h el ${dayLabel(day)}.`);
    } else if(action==='paid') {
      call('paid',{month:lastMonth.month,paid:lastMonth.paid?0:1,minutes:lastMonth.minutes,rate_cents:lastMonth.rate_cents});render();toast('Estado de cobro actualizado.');
    } else if(action==='focus-rate') {
      document.querySelector('#month-rate').scrollIntoView({block:'center'});document.querySelector('#month-rate-input').focus();
    } else if(action==='csv') call('export',{kind:'csv',month:button.dataset.month});
    else if(action==='backup'||action==='previous') call('export',{kind:action});
    else if(action==='import') call('import');
    else if(action==='delete') {
      call('delete',{day:button.dataset.day,revision:Number(button.dataset.revision)});navigate(monthRoute(button.dataset.day.slice(0,7)));toast('Registro eliminado.');
    } else if(action==='step'||action==='preset') {
      const input=document.querySelector('#entry-hours');
      const amount=action==='preset'?Number(button.dataset.hours):(Number(input.value)||0)+Number(button.dataset.step);
      input.value=Math.min(24,Math.max(.5,amount));input.dispatchEvent(new Event('input',{bubbles:true}));
    }
  } catch(error){toast(error.message);}
});
document.addEventListener('change',event=>{
  if(event.target.id==='quick-hours'){quick[event.target.dataset.month]=Number(event.target.value);render();}
});
document.addEventListener('input',event=>{
  if(event.target.id==='entry-hours') document.querySelectorAll('[data-hours]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.hours)===Number(event.target.value))));
});
document.addEventListener('submit',event=>{
  event.preventDefault();const form=event.target,values=new FormData(form);
  try {
    if(form.id==='prefs-form') {
      call('preferences_save',{minutes:Number(values.get('minutes')),rate:values.get('rate')});Object.keys(quick).forEach(k=>delete quick[k]);render();toast('Preferencias guardadas. La tarifa se aplicará a los meses nuevos.');
    } else if(form.id==='rate-form') {
      call('rate',{month:form.dataset.month,rate:values.get('rate')});render();toast('Tarifa del mes guardada.');
    } else if(form.id==='entry-form') {
      const day=values.get('day');call('save',{day,minutes:Number(values.get('hours'))*60,note:values.get('note'),revision:Number(form.dataset.revision)});navigate(monthRoute(day.slice(0,7)));toast('Registro guardado.');
    } else if(form.id==='year-form') navigate('/history?year='+values.get('year'));
  } catch(error){const out=form.querySelector('.form-error');if(out)out.textContent=error.message;toast(error.message);}
});
window.nativeFinished=(message,refresh)=>{if(refresh)render();toast(message);};
window.goBack=()=>{
  const {path,params}=route();
  if(path==='/entry'){navigate(monthRoute((params.get('day')||today()).slice(0,7)));return true;}
  if(path!=='/calendar'||params.get('month')){navigate('/calendar');return true;}
  return false;
};
window.addEventListener('hashchange',()=>{render();window.scrollTo(0,0);});
render();
