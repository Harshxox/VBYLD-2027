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
  const values={state:{saving:false,recording:false,mode:'typed',lang:'en',idx:0,freeText:'Never',selectedOption:'Never',transcript:'',answers:[],audioChunks:[],backendSessionId:'synthetic',sessionToken:'test-token'},
    questions:[{id:1,text:'Question 1',options:['Never','Often']},{id:2,text:'Question 2',options:['Never','Often']}],currentClientId:'synthetic',
    render(){},storeAudio(){},getAudioForClient:()=>({}),matchTimer:null,matchSeq:0,setTimeout,clearTimeout,finishSession:async()=>{},runMatch:async()=>{},tr:x=>x,
    console:{warn(){},log(){},error(){}},MediaRecorder:{isTypeSupported:()=>true},Blob,FormData,
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
  vm.runInContext(['canContinue','recordingBlob','audioExtension','goToQuestion','saveAnswer'].map(n=>functions.get(n)).join('\n'),c);
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
function load(c,names){vm.runInContext(names.map(n=>functions.get(n)).join('\n'),c)}
{
  const c=context();load(c,['recordingBlob','audioExtension']);
  c.state.audioMimeType='audio/mp4';c.state.audioChunks=[new Blob(['test'],{type:'audio/mp4'})];
  assert.equal(c.recordingBlob().type,'audio/mp4');assert.equal(c.audioExtension('audio/mp4'),'m4a');
  console.log('PASS recording keeps its actual MIME type and matching extension');count++;
}
{
  const c=context();c.state.idx=1;c.state.answers=[{qId:1,answer:'Often',transcript:'Most days'}];
  load(c,['goToQuestion']);await c.goToQuestion(0);
  assert.equal(c.state.selectedOption,'Often');assert.equal(c.state.freeText,'Most days');assert.equal(c.state.transcript,'Most days');
  console.log('PASS previous question restores saved answer and transcript');count++;
}
{
  const c=context();c.state.selectedOption='';c.state.freeText='an ambiguous response';
  load(c,['canContinue','saveAnswer']);await c.saveAnswer();assert.equal(c.state.idx,0);assert.match(c.state.notice,/select the option/);
  console.log('PASS unresolved free text cannot silently score a neutral answer');count++;
}
{
  let finished=0,saves=0;const c=context({finishSession:async()=>{finished++},apiReq:async()=>{saves++}});
  c.state.reportPending=true;load(c,['canContinue','saveAnswer']);await c.saveAnswer();
  assert.equal(finished,1);assert.equal(saves,0);
  console.log('PASS report retry does not upload or save the last answer again');count++;
}
{
  let request;const c=context({adminToken:'admin-test',_fetchWithTimeout:async(url,opts)=>{request={url,...opts};return {ok:true,blob:async()=>new Blob(['pdf'])}}});
  load(c,['protectedBlob']);await c.protectedBlob('/api/sessions/test/report.pdf');
  assert.equal(request.headers['X-Session-Token'],'test-token');assert.ok(!request.url.includes('test-token'));
  await c.protectedBlob('/api/sessions/test/audio/q1.wav',true);assert.equal(request.headers.Authorization,'Bearer admin-test');
  await assert.rejects(c.protectedBlob('https://outside.invalid/recording'),/Invalid media path/);
  console.log('PASS protected PDF and audio fetches authenticate without putting tokens in URLs');count++;
}
{
  const clip=new Blob(['previous clip']);
  const c=context({navigator:{mediaDevices:{getUserMedia:async()=>{throw new Error('permission denied')}}}});
  c.state.mode='voice';c.state.audioChunks=[clip];load(c,['toggleRecording']);await c.toggleRecording();
  assert.equal(c.state.audioChunks[0],clip);assert.equal(c.state.requestingMic,false);assert.match(c.state.notice,/Microphone unavailable/);
  console.log('PASS microphone failure retains previous audio and releases the control');count++;
}
{
  const c=context();let stopped=false,listener;
  c.state.recording=true;c.state.recorder={state:'recording',addEventListener:(event,fn)=>{listener=fn},stop(){
    Promise.resolve().then(()=>{c.state.audioChunks.push(new Blob(['final chunk']));this.state='inactive';stopped=true;listener()});
  }};
  load(c,['stopRecording']);await c.stopRecording({quiet:true});
  assert.ok(stopped);assert.equal(c.state.audioChunks.length,1);assert.equal(c.state.recording,false);
  console.log('PASS stopping waits for the final recorder chunk');count++;
}
console.log(`${count}/${count} frontend integrity checks passed`);
