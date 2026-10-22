// Test browser input handling, including Enter, IME, acknowledgment and disconnect.
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const nodes=new Map();
function node(){return {style:{},value:'',disabled:false,textContent:'',handlers:{},replaceChildren(){},append(){},addEventListener(n,f){this.handlers[n]=f;}};}
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},querySelectorAll(){return [];},createElement:node};
let socket;
class WS {static OPEN=1;constructor(){socket=this;this.readyState=1;this.sent=[];}send(m){this.sent.push(JSON.parse(m));}close(){this.readyState=3;}}
const context=vm.createContext({document,WebSocket:WS,location:{protocol:'http:',host:'localhost'},fetch:async()=>({ok:true,json:async()=>[]}),setTimeout(){},clearTimeout(){},setInterval(){}});
const js=fs.readFileSync('web.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(js,context);
vm.runInContext("openTerminal({id:'one',name:'작업'})",context);socket.onopen();
const input=document.getElementById('input');let prevented=false;
input.value='한글 지시';input.handlers.keydown({key:'Enter',isComposing:false,shiftKey:false,preventDefault(){prevented=true;}});
assert(prevented);assert.equal(socket.sent[0].text,'한글 지시');assert.equal(socket.sent[0].enter,true);
assert.equal(input.value,'한글 지시'); // Keep until acknowledged.
socket.onmessage({data:JSON.stringify({type:'ack',id:socket.sent[0].id})});assert.equal(input.value,'');
input.value='조합 중';input.handlers.keydown({key:'Enter',isComposing:true,preventDefault(){throw Error('IME Enter intercepted');}});assert.equal(socket.sent.length,1);
input.handlers.keydown({key:'Enter',isComposing:false,shiftKey:true,preventDefault(){throw Error('Shift Enter intercepted');}});assert.equal(socket.sent.length,1);
socket.readyState=3;document.getElementById('form').onsubmit({preventDefault(){}});assert.equal(input.value,'조합 중');assert.equal(socket.sent.length,1);
console.log('UI: Enter sends text, IME and Shift+Enter preserved, ack required, disconnected input retained');
