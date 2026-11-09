const {chromium}=require(process.env.HOME+'/.beakerlab-tools/node_modules/playwright');
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1100,height:900}});
await p.goto('file://'+process.argv[2]);await p.waitForTimeout(2500);
const out=await p.evaluate(()=>{const r={};for(const c of document.querySelectorAll('canvas')){if(!c.id||!window.Chart)continue;const ch=Chart.getChart(c);if(!ch)continue;
 r[c.id]={labels:ch.data.labels,sets:ch.data.datasets.map(d=>({label:d.label,data:d.data}))};}return r;});
for(const id of ['grw','gday','glv','gfun','srcc']){const o=out[id];if(!o){console.log(id,'none');continue;}console.log('== '+id);console.log(' labels',JSON.stringify(o.labels));for(const s of o.sets)console.log(' ',s.label,JSON.stringify(s.data));}
await b.close();})();
