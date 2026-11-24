import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const html=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
const scripts=[...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m=>m[1]).join('\n');
const parsed=ts.createSourceFile('app.js',scripts,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
assert.equal(parsed.parseDiagnostics.length,0,'inline application JavaScript must parse');
const functions=new Map(parsed.statements.filter(ts.isFunctionDeclaration).map(n=>[n.name?.text,n.getText(parsed)]));
function context(overrides={}){
  const values={state:{saving:false,recording:false,mode:'typed',lang:'en',idx:0,freeText:'Never',selectedOption:'',transcript:'',answers:[],audioChunks:[],backendSessionId:'synthetic',sessionToken:'test-token'},
    questions:[{id:1,text:'Question 1'},{id:2,text:'Question 2'}],currentClientId:'synthetic',
    render(){},storeAudio(){},finishSession:async()=>{},runMatch:async()=>{},tr:x=>x,
    console:{warn(){},log(){}},MediaRecorder:{isTypeSupported:()=>true},Blob,FormData,
    API:'http://127.0.0.1:8000',apiReq:async()=>({}),fetch:async()=>({ok:true,json:async()=>({audio_url:'/audio/test'})}),...overrides};
  return vm.createContext(values);
}
let count=1;
for(const [name,setup,check] of [
  ['failed text save retains current question',c=>{c.apiReq=async()=>{throw new Error('offline');};},c=>{assert.equal(c.state.idx,0);assert.equal(c.state.answers.length,0);assert.equal(c.state.freeText,'Never');assert.match(c.state.notice,/Not saved/);assert.equal(c.state.saving,false);}],
  ['failed recording upload retains recording',c=>{c.state.mode='voice';c.state.selectedOption='Never';c.state.transcript='Never';c.state.audioChunks=[new Blob(['audio'])];c.fetch=async()=>({ok:false,status:503});},c=>{assert.equal(c.state.idx,0);assert.equal(c.state.audioChunks.length,1);assert.equal(c.state.transcript,'Never');}],
  ['successful save advances exactly once',()=>{},c=>{assert.equal(c.state.idx,1);assert.equal(c.state.answers.length,1);assert.equal(c.state.saving,false);}],
]){
  const c=context();setup(c);
  vm.runInContext(functions.get('canContinue')+'\n'+functions.get('saveAnswer'),c);
  await c.saveAnswer();check(c);count++;
  console.log('PASS',name);
}
const c=context({wear:{active:false},wearStopPolling(){},paintAlerts(){},renderLoading(){}});
c.apiReq=async()=>{throw new Error('server report failed');};
vm.runInContext(functions.get('finishSession'),c);
await c.finishSession();
assert.equal(c.state.screen,'assessment');assert.match(c.state.notice,/server report/);assert.equal(c.state.scores,undefined);count++;
console.log('PASS server report failure does not masquerade as a completed report');
const meta=scripts.slice(0,scripts.indexOf('/*'));
const config=vm.createContext({document:{querySelector:()=>({content:'https://example-backend.invalid'})},window:{}});
vm.runInContext(meta.split('//')[0] || '',config);
const bootstrap=html.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
vm.runInContext(bootstrap,config);
assert.equal(config.window.__ERGO_API__,'https://example-backend.invalid');count++;
console.log('PASS configured backend URL is respected');
console.log(`${count}/${count} frontend integrity checks passed`);
