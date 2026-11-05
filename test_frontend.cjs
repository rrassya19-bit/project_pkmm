const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,checked:false,dataset:{},style:{},classList:{toggle(){},add(){},remove(){}},addEventListener(){},scrollIntoView(){}});return elements.get(id);}
const layer=()=>({addTo(){return this;},clearLayers(){},bindPopup(){return this;}});
const emptyState={enabled:false,interval_minutes:30,bbox:null,points:[],cursor:0,last_run:null,next_run:null,next_at:0,busy:false,current:null,batch_size:5};
const context=vm.createContext({console,Date,Blob,URL,setTimeout,setInterval:()=>0,document:{hidden:false,getElementById:element,querySelector:element,createElement:()=>({click(){}})},L:{map:()=>({setView(){return this;},on(){},fitBounds(){}}),tileLayer:layer,layerGroup:layer,circleMarker:layer,rectangle:layer,geoJSON:layer,latLngBounds:(a,b)=>({getWest:()=>Math.min(a.lng,b.lng),getEast:()=>Math.max(a.lng,b.lng),getSouth:()=>Math.min(a.lat,b.lat),getNorth:()=>Math.max(a.lat,b.lat)})},fetch:async url=>({ok:true,json:async()=>url==='/api/status'?{features:['B2'],firms_configured:false}:url==='/api/monitor'?structuredClone(emptyState):url==='/api/priorities'?{rows:[],active_count:0,potential_count:0,note:'',firms_updated_at:null}:{} }),assert});
vm.runInContext(fs.readFileSync(__dirname+'/static/app.js','utf8'),context);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 vm.runInContext(`chooseArea();assert.equal(pickingArea,true);pickCorner({lat:-3,lng:113});pickCorner({lat:-2,lng:114});assert.equal(pickingArea,false);assert.equal(JSON.stringify(draftBox),'[113,-3,114,-2]');assert.equal($('saveArea').disabled,false);chooseArea();assert.equal(draftBox,null);assert.equal($('saveArea').disabled,true);`,context);
 vm.runInContext(`renderMonitor({enabled:true,interval_minutes:30,bbox:[113,-3,114,-2],points:[{id:'1-1',lat:-2.8,lon:113.2,status:'error',checked_at:null,error:'Piksel tertutup awan',result:null}],busy:false,current:null,batch_size:5,last_run:null,next_run:null});assert.ok($('gridRows').innerHTML.includes('Piksel tertutup awan'));assert.ok(!$('gridRows').innerHTML.includes('Aman menurut model'));assert.equal($('pauseMonitor').textContent,'Jeda');`,context);
 vm.runInContext(`const item=priorityItem({tier:2,lat:-3,lon:114,score:.8,observed_at:new Date().toISOString()},0);assert.ok(item.includes('80.0%'));assert.ok(item.includes('data-lat="-3"'));`,context);
 context.fetch=async()=>({ok:true,json:async()=>({rows:[],historical_potential:[{tier:3,lat:-3,lon:114,score:.8,age_days:15,observed_at:new Date().toISOString()}],note:'',firms_updated_at:null})});
 await vm.runInContext('loadPriorities()',context);
 assert.ok(element('potentialList').innerHTML.includes('citra lama'));
 assert.ok(element('potentialList').innerHTML.includes('80.0%'));
 assert.equal(element('potentialTotal').textContent,'0 terbaru / 1 lama');
 console.log('Frontend logic: PASS (area selection, draft reset, failed pixel status, controls, priority score)');
})().catch(error=>{console.error(error);process.exitCode=1;});
