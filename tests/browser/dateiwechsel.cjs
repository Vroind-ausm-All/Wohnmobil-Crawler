/* Eine verspätete CSV-Vorschau darf nach einem Dateitausch keine alte Zuordnung übernehmen. */
const assert=require('node:assert/strict');

module.exports=async function pruefeDateiwechsel(page,csv){
  let anfragen=0, freigeben, angekommen;
  const verzug=new Promise(resolve=>{freigeben=resolve;});
  const wartet=new Promise(resolve=>{angekommen=resolve;});
  const handler=async route=>{
    const body=route.request().postDataJSON();
    if(body.name!=='wechsel-a.csv'||!body.vorschau||++anfragen!==2)return route.continue();
    const response=await route.fetch();angekommen();
    await verzug;await route.fulfill({response});
  };
  await page.route('**/api/import/datei',handler);
  try{
    await page.locator('#angebot-dateien').setInputFiles({name:'wechsel-a.csv',mimeType:'text/csv',buffer:Buffer.from(csv(31000))});
    await page.locator('#upload-start').click();
    await page.getByRole('button',{name:'Vorschau aktualisieren',exact:true}).click();
    await Promise.race([wartet,new Promise((_,reject)=>{const t=setTimeout(()=>reject(new Error('CSV-Anfrage fehlt')),30000);t.unref();})]);
    for(const selector of ['#angebot-dateien','#upload-start','#upload-ueberspringen','#upload-vorschau select']){
      assert.equal(await page.locator(selector).first().isDisabled(),true,selector+' während Vorschau gesperrt');
    }
    // Playwright kann auch ein gesperrtes Feld befüllen: gezielter Test gegen verspätete Rückrufe.
    await page.locator('#angebot-dateien').setInputFiles({name:'wechsel-b.csv',mimeType:'text/csv',buffer:Buffer.from(csv(33000).replace('Fahrzeugname','Titel B'))});
    freigeben();
    await page.waitForFunction(()=>!document.getElementById('angebot-dateien').disabled);
    assert.equal(await page.locator('#upload-vorschau').innerText(),'');
    assert.equal(await page.locator('#upload-start').innerText(),'Dateien prüfen');
    await page.locator('#upload-start').click();
    await page.getByRole('heading',{name:'CSV-Felder zuordnen: wechsel-b.csv',exact:true}).waitFor();
    const titel=page.getByRole('combobox',{name:'Titel',exact:true});
    await titel.selectOption('Titel B');
    assert.equal(await titel.locator('option[value="Fahrzeugname"]').count(),0);
    await page.locator('#upload-ueberspringen').click();
    await page.waitForFunction(()=>document.getElementById('upload-start').textContent==='Import abgeschlossen');
    console.log('CSV-Dateiwechsel bestanden: Bedienelemente gesperrt, verspätete Vorschau verworfen.');
  }finally{freigeben();await page.unroute('**/api/import/datei',handler);}
};
