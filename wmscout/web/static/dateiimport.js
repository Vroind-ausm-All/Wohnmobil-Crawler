/* Dateiimport: Vorschau bleibt Text. Inhalte und Namen werden nie als HTML ausgeführt. */
(function(){
  'use strict';
  var token=(window.SCOUT||{}).token, input=document.getElementById('angebot-dateien');
  if(!token||!input)return;
  var start=document.getElementById('upload-start'), preview=document.getElementById('upload-vorschau'), output=document.getElementById('upload-ergebnis');
  var skip=document.getElementById('upload-ueberspringen');
  var dateien=[], position=0, aktuell=null, zuordnung=null, busy=false, generation=0, gueltig=false;
  function sperren(wert){
    busy=wert;input.disabled=wert;skip.disabled=wert;
    start.disabled=wert||!gueltig||position>=dateien.length;
    preview.querySelectorAll('input,select,button').forEach(function(n){n.disabled=wert;});
  }
  function el(tag,text){var n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
  function zeige(text){output.textContent=text;}
  function lesen(file){return new Promise(function(resolve,reject){
    var r=new FileReader();r.onload=function(){resolve(String(r.result).split(',')[1]);};r.onerror=function(){reject(new Error('Datei konnte nicht gelesen werden.'));};r.readAsDataURL(file);
  });}
  function senden(vorschau){return fetch('/api/import/datei',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Scout-Token':token},
    body:JSON.stringify({name:aktuell.name,inhalt:aktuell.inhalt,vorschau:vorschau,zuordnung:zuordnung||{}})}).then(function(r){return r.json().then(function(d){if(!r.ok)throw new Error(d.fehler||'Import fehlgeschlagen');return d;});});}
  function csvVorschau(d){
    preview.textContent='';preview.appendChild(el('h3','CSV-Felder zuordnen: '+aktuell.name));
    var box=el('div');box.className='csv-zuordnung';zuordnung=d.zuordnung||{};
    Object.keys(d.felder||{}).forEach(function(f){
      var label=el('label',d.felder[f]), select=el('select');select.setAttribute('aria-label',d.felder[f]);
      var leer=el('option','Nicht zuordnen');leer.value='';select.appendChild(leer);
      (d.spalten||[]).forEach(function(s){var o=el('option',s);o.value=s;select.appendChild(o);});select.value=zuordnung[f]||'';
      select.onchange=function(){zuordnung[f]=select.value;};label.appendChild(select);box.appendChild(label);
    });preview.appendChild(box);
    var neu=el('button','Vorschau aktualisieren');neu.type='button';neu.className='btn';neu.onclick=async function(){
      if(busy)return;
      var stand=generation, datei=aktuell;sperren(true);
      try{var d=await senden(true);if(stand===generation&&datei===aktuell)csvVorschau(d);}
      catch(e){if(stand===generation)zeige(e.message);}
      finally{sperren(false);}
    };preview.appendChild(neu);
    preview.appendChild(el('p',String(d.gesamt||0)+' Zeilen. Vorschau der ersten 20 Angebote:'));
    var table=el('table'), head=el('tr');['Titel','Preis','Anbieter','Hinweis'].forEach(function(t){head.appendChild(el('th',t));});table.appendChild(head);
    (d.vorschau||[]).forEach(function(z){var row=el('tr');[z.titel,z.preis,z.anbieter,z.fehler||''].forEach(function(v){row.appendChild(el('td',v==null?'unbekannt':String(v)));});table.appendChild(row);});preview.appendChild(table);
    if(d.fehler&&d.fehler.length) preview.appendChild(el('p',d.fehler.join('\n')));
    start.textContent='CSV mit dieser Zuordnung importieren';start.disabled=false;
  }
  async function weiter(){
    preview.textContent='';zuordnung=null;aktuell=null;skip.hidden=position>=dateien.length;
    if(position>=dateien.length){start.disabled=true;start.textContent='Import abgeschlossen';return;}
    var f=dateien[position], stand=generation, inhalt=await lesen(f);
    if(stand!==generation)return;
    aktuell={name:f.name,inhalt:inhalt};
    if(/\.csv$/i.test(f.name)){
      var datei=aktuell, d=await senden(true);
      if(stand===generation&&datei===aktuell)csvVorschau(d);
    }
    else {preview.appendChild(el('p','Bereit zum Einlesen: '+f.name));start.textContent='Datei importieren';start.disabled=false;}
  }
  skip.onclick=async function(){if(busy)return;sperren(true);try{output.textContent+='\n'+dateien[position].name+': vom Benutzer übersprungen.';position++;await weiter();}catch(e){zeige(e.message);}finally{sperren(false);}};
  input.onchange=function(){
    generation++;skip.hidden=true;dateien=Array.from(input.files||[]);position=0;aktuell=null;zuordnung=null;preview.textContent='';
    var falsch=dateien.find(function(f){return f.size>5000000||!(/\.(csv|html?|eml)$/i).test(f.name);});
    gueltig=!!dateien.length&&!falsch;start.disabled=busy||!gueltig;start.textContent='Dateien prüfen';
    zeige(falsch?'Nicht unterstützt oder größer als 5 MB: '+falsch.name:dateien.length+' Datei(en) ausgewählt.');
  };
  start.onclick=async function(){
    if(busy)return;var stand=generation;sperren(true);
    try{
      if(!aktuell){await weiter();return;}
      var d=await senden(false);
      if(stand!==generation)return;
      var zeile=aktuell.name+': '+(d.neu||0)+' neu, '+(d.aktualisiert||0)+' aktualisiert, '+(d.uebersprungen||0)+' übersprungen, '+(d.fehlerhaft||0)+' fehlerhaft.';
      output.textContent+='\n'+zeile+(d.fehler&&d.fehler.length?'\n'+d.fehler.join('\n'):'')+(d.hinweise&&d.hinweise.length?'\n'+d.hinweise.join('\n'):'');
      document.getElementById('upload-liste').hidden=false;position++;await weiter();
    }catch(e){if(stand===generation)output.textContent+='\n'+e.message;}
    finally{sperren(false);}
  };
})();
