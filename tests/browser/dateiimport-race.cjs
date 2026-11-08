/* Deterministischer JavaScript-Regressionstest mit verzögerten Antworten; kein Browsertest.
   Führt das unveränderte Produkt-Skript gegen einen kleinen DOM-/HTTP-Testadapter aus. */
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const script=fs.readFileSync(path.join(__dirname,'../../wmscout/web/static/dateiimport.js'),'utf8');

class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.disabled=false;}
  set textContent(text){this.text=String(text);this.children=[];}
  get textContent(){return this.text||'';}
  appendChild(node){this.children.push(node);return node;}
  setAttribute(){}
  querySelectorAll(selector){
    const tags=selector.split(','), result=[];
    function visit(node){for(const child of node.children){if(tags.includes(child.tagName))result.push(child);visit(child);}}
    visit(this);return result;
  }
}

function testApp(){
  const ids=Object.fromEntries(['angebot-dateien','upload-start','upload-vorschau','upload-ergebnis','upload-ueberspringen','upload-liste']
    .map(id=>[id,new Element(id)]));
  const requests=[];let verzug;
  function vorschau(name){
    const spalte=name==='alt.csv'?'Alter Link':'Neuer Link';
    return {gesamt:1,spalten:[spalte,'Preis'],felder:{url:'Inseratlink',preis:'Kaufpreis'},
      zuordnung:{url:spalte,preis:'Preis'},vorschau:[]};
  }
  const response=(data,ok=true)=>({ok,json:()=>Promise.resolve(data)});
  const context={window:{SCOUT:{token:'synthetisches-testtoken'}},
    document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag)},
    FileReader:class {
      readAsDataURL(file){
        const fertig=()=>{this.result='data:text/csv;base64,'+file.inhalt;this.onload();};
        if(file.spaeter)file.lesenBeenden=fertig;else fertig();
      }
    },
    fetch:(url,options)=>{
      assert.equal(url,'/api/import/datei');
      const data=JSON.parse(options.body);requests.push(data);
      if(data.vorschau&&verzug){const v=verzug;verzug=null;return new Promise(resolve=>{v.antwort=(ok=true)=>resolve(response(
        ok?vorschau(data.name):{fehler:'Veraltete Fehlermeldung'},ok));});}
      return Promise.resolve(response(data.vorschau?vorschau(data.name):{neu:1}));
    }};
  vm.runInNewContext(script,context,{filename:'dateiimport.js'});
  return {ids,requests,auswaehlen(file){ids['angebot-dateien'].files=[file];ids['angebot-dateien'].onchange();},
    verzoegern(){verzug={};return verzug;},
    refresh(){return ids['upload-vorschau'].querySelectorAll('button')[0].onclick();},
    start(){return ids['upload-start'].onclick();}};
}
const datei=(name,extra={})=>({name,inhalt:Buffer.from(name).toString('base64'),size:100,...extra});

async function spaeteVorschau(ok){
  const app=testApp(), {ids,requests}=app;
  app.auswaehlen(datei('alt.csv'));await app.start();
  const verzug=app.verzoegern(), refresh=app.refresh();
  for(const id of ['angebot-dateien','upload-start','upload-ueberspringen'])assert.equal(ids[id].disabled,true,id+' während Vorschau gesperrt');
  assert.ok(ids['upload-vorschau'].querySelectorAll('select').every(s=>s.disabled));
  const anzahl=requests.length;
  await app.start();await ids['upload-ueberspringen'].onclick();
  assert.equal(requests.length,anzahl,'Kein Import oder Dateiwechsler während einer offenen Vorschau');

  // Auch ein bereits eingeplantes change-Ereignis darf keine Antwort der vorherigen Datei übernehmen.
  app.auswaehlen(datei('neu.csv'));await app.start();
  assert.equal(requests.length,anzahl);
  verzug.antwort(ok);await refresh;
  assert.equal(ids['upload-vorschau'].children.length,0,'Alte Vorschau darf nicht die neue Dateiauswahl überschreiben');
  assert.ok(!ids['upload-ergebnis'].textContent.includes('Veraltete Fehlermeldung'));
  await app.start();await app.start();
  assert.deepEqual(requests.filter(r=>!r.vorschau),[{name:'neu.csv',inhalt:Buffer.from('neu.csv').toString('base64'),
    vorschau:false,zuordnung:{url:'Neuer Link',preis:'Preis'}}]);
}

async function spaetesDateilesen(){
  const app=testApp(), alt=datei('alt.csv',{spaeter:true});
  app.auswaehlen(alt);const lesen=app.start();
  app.auswaehlen(datei('neu.csv'));alt.lesenBeenden();await lesen;
  assert.equal(app.requests.length,0,'Veralteter FileReader darf keine Anfrage auslösen');
  await app.start();await app.start();
  assert.ok(app.requests.every(r=>r.name==='neu.csv'));
  assert.equal(app.requests.filter(r=>!r.vorschau)[0].zuordnung.url,'Neuer Link');
}

(async()=>{
  await spaeteVorschau(true);await spaeteVorschau(false);await spaetesDateilesen();
  console.log('Dateiimport-Race-Regression bestanden: Sperren, veraltete Vorschau/Fehler und verzögertes Dateilesen.');
})().catch(error=>{console.error(error);process.exitCode=1;});
