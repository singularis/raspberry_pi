var rec=false,poll=null,img=document.getElementById('v'),banner=document.getElementById('banner');
function mmss(s){s=s|0;var m=(s/60)|0;s=s%60;return (m<10?'0':'')+m+':'+(s<10?'0':'')+s;}
function liveOn(){banner.className='';img.src='/video_feed?t='+Date.now();}
function liveOff(){img.removeAttribute('src');banner.className='show';}
function show(j){
  rec=!!(j&&j.recording);
  var b=document.getElementById('rec');
  b.className=rec?'on':'';
  b.textContent=rec?'■ '+mmss(j.elapsed_s):'● Rec';
  document.getElementById('note').textContent=rec?(j.size||'recording'):'';
  if(rec)liveOff(); else liveOn();
  if(rec&&!poll)poll=setInterval(function(){fetch('/record').then(r=>r.json()).then(show);},1000);
  if(!rec&&poll){clearInterval(poll);poll=null;}
}
document.getElementById('rec').onclick=function(e){
  e.preventDefault();
  var start=!rec;
  if(start)liveOff();
  fetch('/record?on='+(start?1:0)).then(r=>r.json()).then(show);
};
document.getElementById('ref').onclick=function(e){
  e.preventDefault();
  fetch('/record').then(r=>r.json()).then(function(j){if(j&&j.recording)show(j);else liveOn();});
};
document.getElementById('dl').onclick=function(e){
  e.preventDefault();
  var note=document.getElementById('note');
  note.textContent='saving';
  fetch('/snap.jpg').then(function(r){
    if(!r.ok)throw new Error('snap');
    var name='pi.jpg';
    var cd=r.headers.get('Content-Disposition')||'';
    var m=cd.match(/filename="([^"]+)"/);
    if(m)name=m[1];
    return r.blob().then(function(b){return {b:b,name:name};});
  }).then(function(got){
    var a=document.createElement('a');
    a.href=URL.createObjectURL(got.b);
    a.download=got.name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    if(!rec)note.textContent='';
  }).catch(function(){note.textContent='no frame';});
};
fetch('/record').then(r=>r.json()).then(show);
