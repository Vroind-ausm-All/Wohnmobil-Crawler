/* Echter Chromium-Test gegen isolierte Python-App. Keine Marktplatz-Netzaufrufe. */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const path=require('node:path'), fs=require('node:fs'), assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const python=process.env.SCOUT_TEST_PYTHON || path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
const app=spawn(python,['-u',path.join(__dirname,'server.py')],{cwd:root,stdio:['ignore','pipe','pipe']});
let browser;let log='';app.stderr.on('data',d=>{log+=d.toString();});
const ready=new Promise((resolve,reject)=>{
 const timer=setTimeout(()=>reject(new Error('App-Start zu langsam: '+log)),30000);
 app.stdout.on('data',d=>{const m=d.toString().match(/READY (http:\/\/127\.0\.0\.1:\d+)/);if(m){clearTimeout(timer);resolve(m[1]);}});
 app.on('error',reject);app.on('exit',code=>{clearTimeout(timer);reject(new Error('App beendet: '+code+' '+log));});
});
(async()=>{
 const base=await ready;
 const chrome=process.env.SCOUT_CHROMIUM || (fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined);
 browser=await chromium.launch({executablePath:chrome,headless:true,args:process.env.CI?[]:['--no-sandbox']});
 const page=await browser.newPage({locale:'de-DE',viewport:{width:1360,height:1000}}), errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route(/^https?:\/\/(?!127\.0\.0\.1(?::|\/)).*/,route=>route.abort());
 await page.goto(base);
 await page.getByRole('navigation',{name:'Hauptmenü'}).getByRole('link',{name:'Angebote importieren'}).click();
 const csv=(preis)=>'url;Fahrzeugname;preis;km;ez_jahr;ort;anbieter;art\nhttps://www.kleinanzeigen.de/s-anzeige/test/9876543210-220-1234;Knaus Sky TI 650 MEG;'+preis+';85000;2017;74354 Besigheim;privat;Teilintegrierter\n';
 await require('./dateiwechsel.cjs')(page,csv);
 async function upload(name,body,csvFile=true){
  await page.locator('#angebot-dateien').setInputFiles({name,mimeType:csvFile?'text/csv':'text/html',buffer:Buffer.from(body)});
  await page.locator('#upload-start').click();
  if(csvFile){await page.getByRole('button',{name:'CSV mit dieser Zuordnung importieren'}).waitFor();await page.getByRole('combobox',{name:'Titel',exact:true}).selectOption('Fahrzeugname');}
  else await page.getByRole('button',{name:'Datei importieren',exact:true}).waitFor();
  await page.locator('#upload-start').click();
  await page.waitForFunction(()=>document.getElementById('upload-start').textContent==='Import abgeschlossen');
 }
 await upload('angebote.csv',csv(32000));assert.match(await page.locator('#upload-ergebnis').innerText(),/1 neu/);
 await upload('angebote.csv',csv(29000));assert.match(await page.locator('#upload-ergebnis').innerText(),/1 aktualisiert/);
 await upload('angebote.csv',csv(29000));assert.match(await page.locator('#upload-ergebnis').innerText(),/1 übersprungen/);
 const html='<html><article class="aditem" data-adid="9876543211" data-href="/s-anzeige/test/9876543211-220-1234"><h2><a href="/s-anzeige/test/9876543211-220-1234">Hymer B 678</a></h2><p class="aditem-main--middle--price-shipping--price">VB</p><p>Privater Nutzer</p></article><script>window.uploadExecuted=true</script></html>';
 await upload('gespeicherte-seite.html',html,false);assert.match(await page.locator('#upload-ergebnis').innerText(),/1 neu/);
 assert.equal(await page.evaluate(()=>window.uploadExecuted),undefined);
 await page.locator('#upload-liste').click();
 await page.getByRole('navigation',{name:'Hauptmenü'}).getByRole('link',{name:'Fahrzeuge suchen'}).click();
 await page.locator('[name="plz"]').fill('74354');await page.locator('[name="radius"]').fill('100');
 await page.getByRole('button',{name:'Angebote finden',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('suche-ergebnis').textContent.includes('passende'));
 assert.equal(await page.locator('.karte[data-id="9876543210"]:visible').count(),1);
 await page.locator('[name="profilname"]').fill('Reisemobile Süd');await page.getByRole('button',{name:'Suchprofil speichern',exact:true}).click();
 await page.waitForFunction(()=>document.getElementById('suche-ergebnis').textContent.includes('gespeichert'));
 await page.getByRole('button',{name:'Zurücksetzen',exact:true}).click();
 await page.locator('#sort').selectOption('preis');
 assert.equal(await page.locator('#liste .karte').first().getAttribute('data-id'),'9876543210');
 await page.locator('#sort').selectOption('preis_ab');
 assert.equal(await page.locator('#liste .karte').first().getAttribute('data-id'),'9876543210');
 await page.locator('.karte[data-id="9876543210"] [data-oeffnen]').click();
 await page.getByRole('button',{name:'Fahrzeugangaben prüfen und bestätigen'}).click();
 await page.locator('#dlg [name="km"]').fill('86000');await page.locator('#dlg [name="check-km"]').check();
 await page.getByRole('button',{name:'Geprüfte Angaben bestätigen',exact:true}).click();
 await page.getByRole('link',{name:'Bewertung mit bestätigten Angaben anzeigen'}).waitFor();
 assert.match(await page.locator('#dlg [data-angaben-box]').innerText(),/bestätigt am/);
 await page.getByRole('link',{name:'Bewertung mit bestätigten Angaben anzeigen'}).click();
 await page.getByRole('button',{name:'Beste Ankaufchancen',exact:true}).click();
 assert.equal(await page.locator('.karte[data-id="9876543210"]').count(),1);
 assert.match(await page.locator('.karte[data-id="9876543210"]').innerText(),/86.000 km/);
 const termin=await page.evaluate(async()=>{
   const r=await fetch('/api/besichtigung',{method:'POST',headers:{'Content-Type':'application/json','X-Scout-Token':window.SCOUT.token},body:JSON.stringify({anzeige_id:'9876543210',termin:'2026-12-01T10:00',adresse:'Beispielstraße 1, 74354 Besigheim'})});
   if(!r.ok)throw new Error(await r.text());return r.json();
 });
 await page.goto(base+'/m#/besichtigung/'+termin.id);
 await page.locator('[data-fz="fin"]').fill('WVWZZZ1JZXW000001');
 await page.locator('[data-feld="km_abgelesen"]').fill('86000');
 await page.waitForResponse(r=>r.url().includes('/speichern')&&r.status()===200);
 const draftPromise=page.waitForEvent('popup');await page.getByRole('link',{name:'Vertragsentwurf vorbereiten',exact:true}).click();
 const draft=await draftPromise;await draft.waitForLoadState();
 await draft.getByRole('textbox',{name:'Verkäufer: Name',exact:true}).fill('Testverkäufer Beispiel');
 await draft.getByRole('textbox',{name:'Verkäufer: Anschrift',exact:true}).fill('Beispielstraße 1, 74354 Besigheim');
 await draft.getByRole('textbox',{name:'Telefon',exact:true}).fill('0123456789');
 await draft.getByRole('textbox',{name:'E-Mail',exact:true}).fill('beispiel@example.test');
 const speichern=draft.waitForResponse(r=>r.url().includes('/vertragsdaten')&&r.request().method()==='POST');
 await draft.getByRole('button',{name:'Speichern und Entwurf aktualisieren'}).click();
 const gespeichert=await speichern;assert.equal(gespeichert.status(),200);
 await draft.waitForFunction(()=>document.querySelector('main').innerText.includes('beispiel@example.test'));
 assert.match(await draft.locator('main').innerText(),/beispiel@example.test/);
 assert.match(await draft.locator('main').innerText(),/WVWZZZ1JZXW000001/);
 assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes('beispiel@example.test')),false);
 await draft.close();
 await page.setViewportSize({width:390,height:844});await page.goto(base+'/m#/liste/alle');
 await page.locator('#mobil-sort').waitFor();await page.locator('#mobil-sort').selectOption('chance');
 await page.locator('#mobil-sort').waitFor();assert.equal(await page.locator('#mobil-sort').inputValue(),'chance');
 if(process.env.SCOUT_BROWSER_ARTIFACTS){
   const dir=path.resolve(process.env.SCOUT_BROWSER_ARTIFACTS);fs.mkdirSync(dir,{recursive:true});
   await page.screenshot({path:path.join(dir,'mobil.png'),fullPage:true});
   await page.setViewportSize({width:1360,height:1000});await page.goto(base);
   await page.getByRole('navigation',{name:'Hauptmenü'}).waitFor();
   await page.screenshot({path:path.join(dir,'haendler.png'),fullPage:true});
 }
 assert.deepEqual(errors,[]);
 console.log('Browser-Abnahme bestanden: CSV/HTML-Upload, Zuordnung, Reimport, Preissenkung, Suche/Radius, Profil, Sortierung, Bestätigung, Besichtigung/Vertragsentwurf und mobile Ansicht.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();app.kill('SIGTERM');});
