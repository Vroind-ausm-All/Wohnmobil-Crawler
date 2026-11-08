/* Bestätigte Werte liegen getrennt vom importierten Original. Keine unbemerkte Bestätigung. */
(function(){
 'use strict';
 var token=(window.SCOUT||{}).token;if(!token)return;
 var namen={preis:'Preis in €',ez_jahr:'Erstzulassung',km:'Kilometerstand',marke:'Marke',modell:'Modell',ort:'Ort',art:'Fahrzeugart'};
 function el(tag,text){var x=document.createElement(tag);if(text!==undefined)x.textContent=text;return x;}
 function api(id,data){var options={credentials:'same-origin'};if(data)options={credentials:'same-origin',method:'POST',headers:{'Content-Type':'application/json','X-Scout-Token':token},body:JSON.stringify(data)};
  return fetch('/api/fahrzeug/'+encodeURIComponent(id)+'/angaben',options).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.fehler||'Angaben nicht gespeichert');return d;});});}
 function zeichnen(box,id,d){
  box.textContent='';box.appendChild(el('p','Bestätige nur selbst geprüfte Angaben. Das importierte Original bleibt erhalten; abweichende spätere Importe werden als Konflikt markiert.'));
  var form=el('form'),message=el('p');message.setAttribute('role','status');form.className='sp-form';
  Object.keys(namen).forEach(function(f){
   var z=d.felder[f];if(!z)return;var section=el('div'), label=el('label',namen[f]), input=el('input');label.className='sp-feld';
   input.name=f;input.type=['preis','ez_jahr','km'].includes(f)?'number':'text';input.value=z.wert==null?'':z.wert;
   label.appendChild(input);section.appendChild(label);
   var source=el('p','Import: '+(z.extrahiert==null?'unbekannt':z.extrahiert)+' · '+(z.bestaetigt?'bestätigt am '+new Date(z.bestaetigt_am).toLocaleString('de-DE'):'noch unbestätigt'));
   source.className='meta';if(z.konflikt){source.classList.add('warn');source.textContent+=' · Konflikt mit Import';}section.appendChild(source);
   var choice=el('label',' Diesen Wert bestätigen'),check=el('input');check.type='checkbox';check.name='check-'+f;choice.prepend(check);section.appendChild(choice);
   if(z.bestaetigt){var reset=el('button','Bestätigung zurücknehmen');reset.type='button';reset.className='btn';reset.onclick=function(){api(id,{zuruecksetzen:[f]}).then(function(x){zeichnen(box,id,x);}).catch(function(e){message.textContent=e.message;});};section.appendChild(reset);}
   form.appendChild(section);
  });
  var save=el('button','Geprüfte Angaben bestätigen');save.type='submit';save.className='btn primaer';form.appendChild(save);
  form.onsubmit=function(e){e.preventDefault();var werte={};Object.keys(namen).forEach(function(f){if(form.elements['check-'+f]&&form.elements['check-'+f].checked){var input=form.elements[f];werte[f]=input.value===''?null:input.type==='number'?Number(input.value):input.value;}});
   if(!Object.keys(werte).length){message.textContent='Bitte wähle die geprüften Angaben aus.';return;}
   save.disabled=true;api(id,{werte:werte}).then(function(x){zeichnen(box,id,x);var ok=el('p','Angaben gespeichert.');box.appendChild(ok);var reload=el('a','Bewertung mit bestätigten Angaben anzeigen');reload.href='/';reload.className='btn';box.appendChild(reload);}).catch(function(e){message.textContent=e.message;}).finally(function(){save.disabled=false;});};
  box.appendChild(form);box.appendChild(message);
 }
 document.addEventListener('click',function(e){var button=e.target.closest('[data-angaben-oeffnen]');if(!button)return;
  var box=button.parentNode.querySelector('[data-angaben-box]');button.disabled=true;
  api(button.dataset.angabenOeffnen).then(function(d){zeichnen(box,button.dataset.angabenOeffnen,d);}).catch(function(e){box.textContent=e.message;}).finally(function(){button.disabled=false;});
 });
})();
