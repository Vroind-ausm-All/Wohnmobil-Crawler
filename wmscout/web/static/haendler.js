/* Zentrale Bestandssuche und Tagesübersicht. Suchprofile lösen keinen Portalabruf aus. */
(function () {
  'use strict';
  var token = (window.SCOUT || {}).token, form = document.getElementById('schnellsuche');
  if (!token || !form) return;
  var meldung = document.getElementById('suche-ergebnis');
  function api(url, data) {
    var options = {credentials:'same-origin'};
    if(data !== undefined) options = {credentials:'same-origin',method:'POST',headers:{'Content-Type':'application/json','X-Scout-Token':token},body:JSON.stringify(data)};
    return fetch(url,options).then(function(r){return r.json().then(function(d){if(!r.ok) throw new Error(d.fehler || 'Anfrage fehlgeschlagen'); return d;});});
  }
  function panel(id){
    ['tag','suche','angebote-importieren'].forEach(function(x){var e=document.getElementById(x);if(e)e.hidden=x!==id;});
    document.querySelectorAll('.hauptnav [aria-controls]').forEach(function(a){
      if(a.getAttribute('aria-controls')===id)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');
    });
  }
  document.querySelectorAll('.hauptnav [aria-controls]').forEach(function(a){a.addEventListener('click',function(){panel(a.getAttribute('aria-controls'));});});
  panel(['tag','suche','angebote-importieren'].indexOf(location.hash.slice(1))>=0?location.hash.slice(1):'tag');
  function daten() {
    var f = form.elements, d = {name:f.profilname.value.trim() || 'Aktuelle Suche', aktiv:true, arten:f.art.value ? [f.art.value] : [],
      marken:f.marke.value.trim() ? [f.marke.value.trim()] : [],modell:f.modell.value.trim() || null,
      gebiet:f.plz.value || f.radius.value ? 'umkreis':'bundesweit',gebiet_plz:f.plz.value || null,gebiet_regionen:[]};
    ['preis_min','preis_max','ez_min','ez_max','km_max'].forEach(function(n){ d[n] = f[n].value === '' ? null : Number(f[n].value); });
    d.gebiet_radius_km = f.radius.value === '' ? null : Number(f.radius.value);
    return d;
  }
  form.onsubmit = function(e){
    e.preventDefault();
    meldung.textContent = 'Eingelesene Angebote werden durchsucht …';
    api('/api/suche/vorschau',daten()).then(function(d){
      var auswahl = document.getElementById('profil-filter'); if(auswahl) auswahl.value = '';
      window.scoutProfilFilter(d.treffer); window.scoutListe('alle','chance');
      meldung.textContent = Object.keys(d.treffer).length + ' passende oder noch zu prüfende Inserate im Bestand. Es wurden keine neuen Anzeigen abgerufen.';
      document.getElementById('liste').scrollIntoView({behavior:'smooth',block:'start'});
    }).catch(function(e){meldung.textContent=e.message;});
  };
  form.onreset = function(){
    window.scoutProfilFilter(null); window.scoutListe('alle'); meldung.textContent='Alle eingelesenen Angebote.';
    var auswahl=document.getElementById('profil-filter'); if(auswahl)auswahl.value='';
  };
  document.getElementById('suche-speichern').onclick=function(){
    if(!form.reportValidity()) return;
    if(!form.elements.profilname.value.trim()){meldung.textContent='Bitte gib dem Suchprofil einen Namen.'; form.elements.profilname.focus(); return;}
    api('/api/suchprofile',daten()).then(function(){meldung.textContent='Suchprofil gespeichert.';document.dispatchEvent(new Event('scout-profile-geaendert'));}).catch(function(e){meldung.textContent=e.message;});
  };
  api('/api/suchprofile').then(function(d){document.getElementById('suche-speichern').hidden=!d.darf_aendern;}).catch(function(){});
  document.querySelectorAll('[data-tag-filter]').forEach(function(b){b.onclick=function(){
    window.scoutListe(b.dataset.tagFilter,b.dataset.tagSort);document.getElementById('liste').scrollIntoView({behavior:'smooth'});
  };});
  api('/api/status').then(function(d){
    document.getElementById('quellen-kurz').textContent=d.quellen.map(function(q){
      return q.name+': '+(!q.freigegeben?'nicht freigegeben':!q.laeuft?'deaktiviert':q.sperrgrund?'pausiert':q.suchen?'bereit':'kein Suchauftrag');
    }).join(' · ');
    var erfolge=d.laeufe.filter(function(x){return x.ergebnis==='ok' && x.art!=='suchlauf';}).map(function(x){return x.ende||x.start;}).sort();
    var zeit=d.letzter_erfolgreicher_import || erfolge[erfolge.length-1];
    document.getElementById('import-stand').textContent=zeit?'Letzter erfolgreicher Datenimport: '+new Date(zeit).toLocaleString('de-DE'):'Noch kein erfolgreicher Dateiimport protokolliert.';
  }).catch(function(e){document.getElementById('quellen-kurz').textContent='Quellenstatus konnte nicht geladen werden: '+e.message;});
  api('/api/heute').then(function(d){
    var box=document.getElementById('tages-termine'), termine=d.termine||[];
    if(!termine.length){box.textContent='Keine offenen Besichtigungstermine.';return;}
    var titel=document.createElement('h3');titel.textContent='Anstehende Besichtigungen';box.appendChild(titel);
    termine.slice(0,8).forEach(function(t){var p=document.createElement('p'),a=document.createElement('a');
      a.href='/m#/besichtigung/'+encodeURIComponent(t.id);a.textContent=(t.fahrzeug||'Fahrzeug')+' · '+(t.termin?new Date(t.termin).toLocaleString('de-DE'):'Termin offen');p.appendChild(a);box.appendChild(p);
    });
  }).catch(function(){document.getElementById('tages-termine').textContent='Termine in der Team-Ansicht öffnen.';});
})();
