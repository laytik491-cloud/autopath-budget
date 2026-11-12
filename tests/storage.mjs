import fs from 'node:fs';
const {chromium} = await import(process.env.PLAYWRIGHT_PATH || 'playwright');
const browser = await chromium.launch({headless:true});
const context = await browser.newContext();
const page = await context.newPage();
page.setDefaultTimeout(15000);
const origin = (process.env.APP_URL || 'http://127.0.0.1:8010/').replace(/\/$/, '');
const results = {
 version:'1.0.0',browser:browser.version(),date:'2026-11-11',checks:[],errors:[],
 note:'Маршрутизатор подменён только в тестовом профиле: фиксированные600000м/7200с. Это проверка хранения и расчёта, не свидетельство реального автомобильного маршрута. Исходники приложения не изменялись.'
};
page.on('pageerror',error=>results.errors.push(error.message));
await context.route('https://router.project-osrm.org/route/v1/driving/**',route=>route.fulfill({contentType:'application/json',headers:{'access-control-allow-origin':'*'},body:JSON.stringify({code:'Ok',routes:[{distance:600000,duration:7200,geometry:{type:'LineString',coordinates:[[150.8,59.5],[151.9,60.1]]}}]})}));
await page.goto(origin+'/config.json');
await page.evaluate(async()=>{
 window.sequence=0;window.responses=new Map();
 window.launchWorker=()=>new Promise((resolve,reject)=>{
  window.worker=new Worker('./worker.mjs?instance='+Math.random(),{type:'module'});
  worker.onmessage=event=>{
   const message=event.data;
   if(message.state)window.lastState=message.state;
   if(message.type==='ready')resolve(message.state);
   if(message.fatal)reject(new Error(message.error));
   if(message.id&&responses.has(message.id)){const done=responses.get(message.id);responses.delete(message.id);done(message);}
  };
 });
 window.command=(command,payload={})=>new Promise(resolve=>{
  const id=++sequence;responses.set(id,resolve);worker.postMessage({id,command,payload});
 });
 window.fixture=async(labels=['Точка A · тест хранения','Точка B · тест хранения'])=>{
  await command('set_point',{index:0,point:{label:labels[0],lat:59.5,lon:150.8}});
  await command('set_point',{index:1,point:{label:labels[1],lat:60.1,lon:151.9}});
  await command('update_parameters',{consumption:'8',price:'60',participants:'4'});
  return command('build_route');
 };
 await launchWorker();
});
async function check(id,run){
 console.log('START',id);
 try{const fact=await run();results.checks.push({id,status:'Пройден',fact});console.log('PASS',id);}
 catch(error){results.checks.push({id,status:'Не пройден',fact:error.message});console.log('FAIL',id,error.message);}
}
await check('INF-01',async()=>{
 await page.evaluate(()=>fixture());await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const state=await page.evaluate(()=>lastState);
 if(state.costs.perPerson!=='720.00')throw new Error(JSON.stringify(state));
 return {costs:state.costs,saveStatus:state.saveStatus,source:'mocked OSRM600000m'};
});
await check('INF-02',async()=>{
 const fact=await page.evaluate(async()=>{
  const db=await new Promise((resolve,reject)=>{const request=indexedDB.open('autopath-budget',1);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  const record=await new Promise((resolve,reject)=>{const request=db.transaction('sqliteFiles','readonly').objectStore('sqliteFiles').get('current');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  db.close();const info={bytes:record.bytes.length,header:String.fromCharCode(...record.bytes.slice(0,15))};
  worker.terminate();await launchWorker();return{...info,costs:lastState.costs};
 });
 if(fact.header!=='SQLite format 3'||fact.costs.perPerson!=='720.00')throw new Error(JSON.stringify(fact));return fact;
});
await check('INF-03',async()=>{
 const original=fs.readFileSync('app/storage.mjs','utf8');
 const marker="transaction.objectStore(storeName).put({id: 'current', dbVersion: 1, bytes: new Uint8Array(bytes)});";
 if(!original.includes(marker))throw new Error('Injection marker absent');
 const injected=original.replace(marker,marker+'\n    transaction.abort();');let count=0;
 await context.route('**/storage.mjs',async route=>{count++;await route.fulfill({contentType:'text/javascript',body:injected});});
 await page.evaluate(async()=>{worker.terminate();await launchWorker();await command('update_parameters',{price:'65'});});
 await page.waitForFunction(()=>lastState.saveStatus==='error');
 const failed=await page.evaluate(()=>({costs:lastState.costs,saveStatus:lastState.saveStatus,message:lastState.message}));
 await context.unroute('**/storage.mjs');
 await page.evaluate(async()=>{worker.terminate();await launchWorker();});
 const restored=await page.evaluate(()=>lastState);
 if(failed.costs.total!=='3120.00'||restored.costs.total!=='2880.00'||!count)throw new Error(JSON.stringify({failed,restored,count}));
 return{method:'test-only adapter calls real IndexedDBtransaction.abort()',memoryTotal:failed.costs.total,failedStatus:failed.saveStatus,restoredTotal:restored.costs.total};
});
await check('INF-04',async()=>{
 const fact=await page.evaluate(async()=>{
  worker.terminate();
  const db=await new Promise((resolve,reject)=>{const request=indexedDB.open('autopath-budget',1);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
  await new Promise((resolve,reject)=>{const transaction=db.transaction('sqliteFiles','readwrite');transaction.objectStore('sqliteFiles').put({id:'current',dbVersion:1,bytes:new Uint8Array([1,2,3,4])});transaction.oncomplete=resolve;transaction.onerror=()=>reject(transaction.error);});
  db.close();await launchWorker();const restored=JSON.parse(JSON.stringify(lastState));
  await fixture();await new Promise(resolve=>setTimeout(resolve,100));
  const saved=await new Promise((resolve,reject)=>{const request=indexedDB.open('autopath-budget',1);request.onsuccess=()=>{const db=request.result;const query=db.transaction('sqliteFiles','readonly').objectStore('sqliteFiles').get('current');query.onsuccess=()=>{resolve(Array.from(query.result.bytes));db.close();};};request.onerror=()=>reject(request.error);});
  return{restoreStatus:restored.saveStatus,message:restored.message,afterBuildStatus:lastState.saveStatus,saved};
 });
 if(fact.restoreStatus!=='error'||JSON.stringify(fact.saved)!=='[1,2,3,4]'||fact.afterBuildStatus!=='error')throw new Error(JSON.stringify(fact));return fact;
});
await check('INF-05',async()=>{
 await page.evaluate(()=>command('clear'));await page.waitForFunction(()=>lastState.saveStatus==='saved');
 await page.evaluate(()=>fixture());await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const saving=await page.evaluate(()=>command('update_parameters',{price:'65'}));
 await page.evaluate(()=>command('clear'));await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const fact=await page.evaluate(async()=>{worker.terminate();await launchWorker();return{route:lastState.route,costs:lastState.costs,points:lastState.points};});
 if(fact.route!==null||fact.costs!==null||fact.points.some(point=>point!==null))throw new Error(JSON.stringify(fact));return{...fact,previousResponseStatus:saving.state.saveStatus};
});
await check('INF-07',async()=>{
 await page.evaluate(()=>fixture(['Точка A · учебный пример','Точка B · учебный пример']));
 await page.waitForFunction(()=>lastState.saveStatus==='saved');
 await page.evaluate(async()=>{worker.terminate();await launchWorker();});
 await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const cleared=await page.evaluate(()=>({route:lastState.route,costs:lastState.costs,points:lastState.points}));
 await page.evaluate(async()=>{worker.terminate();await launchWorker();});
 const reopened=await page.evaluate(()=>({route:lastState.route,costs:lastState.costs,points:lastState.points}));
 if(cleared.route!==null||cleared.points.some(Boolean)||reopened.route!==null||reopened.points.some(Boolean))throw new Error(JSON.stringify({cleared,reopened}));return{exactLegacyPairNotRestored:true,atomicClearPersisted:true,cleared,reopened};
});
await check('INF-08',async()=>{
 await page.evaluate(async()=>{await command('clear');await command('set_mode',{mode:'manual'});await command('update_distance',{distanceText:'150'});});
 await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const original=fs.readFileSync('app/storage.mjs','utf8');
 const marker="transaction.objectStore(storeName).put({id: 'current', dbVersion: 1, bytes: new Uint8Array(bytes)});";
 await context.route('**/storage.mjs',route=>route.fulfill({contentType:'text/javascript',body:original.replace(marker,marker+'\n    transaction.abort();')}));
 await page.evaluate(async()=>{worker.terminate();await launchWorker();await command('update_parameters',{price:'65'});});
 await page.waitForFunction(()=>lastState.saveStatus==='error');
 const failed=await page.evaluate(()=>lastState.costs.perPerson);
 await context.unroute('**/storage.mjs');
 await page.evaluate(async()=>{worker.terminate();await launchWorker();});
 const restored=await page.evaluate(()=>lastState);
 if(failed!=='195.00'||restored.costs.perPerson!=='180.00'||restored.mode!=='manual')throw new Error(JSON.stringify({failed,restored}));
 return{abortedManualCandidate:failed,durableManualResult:restored.costs.perPerson};
});
await check('INF-09',async()=>{
 const image=Array.from(fs.readFileSync('tests/fixtures/schema-v1.sqlite'));
 await page.evaluate(async image=>{worker.terminate();await launchWorker();await command('restore',{bytes:image});},image);
 await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const migrated=await page.evaluate(async()=>{
  const db=await new Promise(resolve=>{const request=indexedDB.open('autopath-budget',1);request.onsuccess=()=>resolve(request.result);});
  const record=await new Promise(resolve=>{const request=db.transaction('sqliteFiles').objectStore('sqliteFiles').get('current');request.onsuccess=()=>resolve(request.result);});
  db.close();const version=new DataView(record.bytes.buffer,record.bytes.byteOffset,record.bytes.byteLength).getUint32(60);
  worker.terminate();await launchWorker();return{version,costs:lastState.costs,points:lastState.points};
 });
 if(migrated.version!==2||migrated.costs.perPerson!=='720.00'||migrated.points[0].label!=='A')throw new Error(JSON.stringify(migrated));
 return migrated;
});
await check('INF-06',async()=>{
 const fact=await page.evaluate(async()=>{
  await navigator.serviceWorker.register('./sw.js');await navigator.serviceWorker.ready;
  await new Promise(resolve=>{if(navigator.serviceWorker.controller)resolve();else navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true});});
  const names=await caches.keys();const name=names.find(name=>name==='autopath-budget-1.0.0');
  if(!name)throw new Error('Expectedv1.0.0cache; actual'+names.join(','));
  const cache=await caches.open(name);const requests=await cache.keys();
  return{cache:name,resources:requests.length,externalResources:requests.filter(request=>new URL(request.url).origin!==location.origin).length};
 });
 await page.evaluate(()=>fixture());await page.waitForFunction(()=>lastState.saveStatus==='saved');
 await context.setOffline(true);
 await page.evaluate(async()=>{worker.terminate();await launchWorker();await command('update_parameters',{price:'65',participants:'2'});});
 await page.waitForFunction(()=>lastState.saveStatus==='saved');
 const state=await page.evaluate(()=>lastState);await context.setOffline(false);
 if(state.costs.total!=='3120.00'||state.costs.perPerson!=='1560.00'||fact.externalResources!==0)throw new Error(JSON.stringify({fact,state}));
 return{...fact,costs:state.costs,offlineWorkerRestart:true,saveStatus:state.saveStatus};
});
fs.writeFileSync('tests/results/infrastructure-results.json',JSON.stringify(results,null,2));
console.log(JSON.stringify(results,null,2));await browser.close();

if(results.checks.some(x=>x.status!=='Пройден')||results.errors.length)process.exitCode=1;
