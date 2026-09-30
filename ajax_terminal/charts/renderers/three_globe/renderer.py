from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ajax_terminal.charts.theme import AJAX_BACKGROUND


ASSET_NAME = "three-0.186.0.module.js"
CORE_ASSET_NAME = "three-0.186.0.core.js"


@lru_cache(maxsize=2)
def _asset_source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


class ThreeGlobeRenderer:
    name = "Three.js Globe"

    def __init__(self, asset_path: Path | None = None, core_asset_path: Path | None = None) -> None:
        self.asset_path = asset_path or Path(__file__).resolve().parents[2] / "assets" / ASSET_NAME
        self.core_asset_path = (
            core_asset_path or Path(__file__).resolve().parents[2] / "assets" / CORE_ASSET_NAME
        )

    def render(self, payload: dict[str, object], geojson: dict[str, object]) -> str:
        template = r'''<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body,#viewport{width:100%;height:100%;margin:0;overflow:hidden;background:__BACKGROUND__}
body{font-family:Consolas,"DejaVu Sans Mono",monospace;color:#d8d8d8;user-select:none}
#viewport{position:relative;cursor:grab}
#viewport.dragging{cursor:grabbing}
canvas{display:block;width:100%;height:100%;outline:none}
#hud{position:absolute;top:10px;right:12px;color:#8f99a3;font-size:12px;pointer-events:none}
#tooltip{position:absolute;display:none;z-index:4;min-width:190px;padding:7px 9px;background:#080a0c;
 border:1px solid #50565c;color:#d8d8d8;font-size:12px;line-height:1.45;pointer-events:none}
#tooltip b{color:#ffb000} #tooltip .metric{color:#4f9ebb} #tooltip .muted{color:#8f99a3}
#legend{position:absolute;left:50%;bottom:11px;transform:translateX(-50%);display:flex;gap:9px;
 align-items:center;padding:4px 7px;background:rgba(5,7,8,.84);border:1px solid #30363b;font-size:11px}
.legend-item{display:flex;align-items:center;gap:4px;white-space:nowrap}.swatch{width:22px;height:7px}
#error{position:absolute;inset:0;display:none;align-items:center;justify-content:center;color:#ffb000;font-size:14px}
</style></head><body><div id="viewport"></div><div id="hud">DRAG ROTATE &nbsp;|&nbsp; WHEEL ZOOM &nbsp;|&nbsp; CLICK COUNTRY</div>
<div id="tooltip"></div><div id="legend"></div><div id="error"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script type="module">
const THREE_SOURCE=__THREE_SOURCE__;
const THREE_CORE_SOURCE=__THREE_CORE_SOURCE__;
const THREE_CORE_URL=URL.createObjectURL(new Blob([THREE_CORE_SOURCE],{type:'text/javascript'}));
const THREE_MODULE_SOURCE=THREE_SOURCE.replaceAll("'./three.core.js'",`'${THREE_CORE_URL}'`);
const THREE=await import(URL.createObjectURL(new Blob([THREE_MODULE_SOURCE],{type:'text/javascript'})));
const config=__CONFIG__;
const world=__GEOJSON__;
const viewport=document.getElementById('viewport');
const tooltip=document.getElementById('tooltip');
const legend=document.getElementById('legend');
const errorBox=document.getElementById('error');
const dataByName=new Map((config.data||[]).map(item=>[item.name,item]));
const features=(world.features||[]).filter(feature=>feature && feature.geometry);
let selectedName=config.selectedName||'';
let terminalBridge=null;
if(window.qt && window.QWebChannel){
  new QWebChannel(qt.webChannelTransport,channel=>{terminalBridge=channel.objects.terminalBridge;});
}

function escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function valueColor(value){
  if(value===null || value===undefined || !Number.isFinite(Number(value))) return '#171c20';
  const numeric=Number(value);
  const piece=(config.pieces||[]).find(item=>(item.gt===undefined||numeric>item.gt)&&(item.lte===undefined||numeric<=item.lte));
  return piece ? piece.color : '#171c20';
}
function geometryPolygons(geometry){
  if(!geometry) return [];
  if(geometry.type==='Polygon') return [geometry.coordinates];
  if(geometry.type==='MultiPolygon') return geometry.coordinates;
  return [];
}
function unwrapRing(ring){
  if(!ring || !ring.length) return [];
  const result=[[Number(ring[0][0]),Number(ring[0][1])]];
  for(let index=1;index<ring.length;index++){
    let lon=Number(ring[index][0]);
    const previous=result[index-1][0];
    while(lon-previous>180) lon-=360;
    while(lon-previous<-180) lon+=360;
    result.push([lon,Number(ring[index][1])]);
  }
  return result;
}
function traceRing(context,ring,width,height,shift){
  const points=unwrapRing(ring);
  if(!points.length) return;
  points.forEach((point,index)=>{
    const x=(point[0]+shift+180)/360*width;
    const y=(90-point[1])/180*height;
    if(index===0) context.moveTo(x,y); else context.lineTo(x,y);
  });
  context.closePath();
}
function drawFeature(context,feature,width,height,fill,selected){
  for(const polygon of geometryPolygons(feature.geometry)){
    for(const shift of [-360,0,360]){
      context.beginPath();
      for(const ring of polygon) traceRing(context,ring,width,height,shift);
      context.fillStyle=selected ? '#ffb000' : fill;
      context.fill('evenodd');
      context.strokeStyle=selected ? '#ffffff' : '#596167';
      context.lineWidth=selected ? 2.0 : 0.65;
      context.stroke();
    }
  }
}
function makeTexture(){
  const canvas=document.createElement('canvas');
  canvas.width=2048; canvas.height=1024;
  const context=canvas.getContext('2d');
  context.fillStyle='#070a0c'; context.fillRect(0,0,canvas.width,canvas.height);
  for(const feature of features){
    const name=String(feature.properties?.name||'');
    drawFeature(context,feature,canvas.width,canvas.height,valueColor(dataByName.get(name)?.value),name===selectedName);
  }
  const texture=new THREE.CanvasTexture(canvas);
  texture.colorSpace=THREE.SRGBColorSpace;
  texture.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());
  texture.needsUpdate=true;
  return texture;
}
function spherePoint(lon,lat,radius=1){
  const phi=(lon+180)*Math.PI/180;
  const theta=(90-lat)*Math.PI/180;
  return new THREE.Vector3(
    -radius*Math.cos(phi)*Math.sin(theta),
    radius*Math.cos(theta),
    radius*Math.sin(phi)*Math.sin(theta)
  );
}
function countryCenter(feature){
  const polygons=geometryPolygons(feature.geometry);
  let best=[];
  for(const polygon of polygons){
    if(polygon[0] && polygon[0].length>best.length) best=polygon[0];
  }
  if(!best.length) return [0,0];
  let x=0,y=0,z=0;
  for(const point of best){
    const lon=Number(point[0])*Math.PI/180;
    const lat=Number(point[1])*Math.PI/180;
    x+=Math.cos(lat)*Math.cos(lon); y+=Math.cos(lat)*Math.sin(lon); z+=Math.sin(lat);
  }
  return [Math.atan2(y,x)*180/Math.PI,Math.atan2(z,Math.hypot(x,y))*180/Math.PI];
}
function pointInRing(lon,lat,ring){
  const points=unwrapRing(ring);
  if(points.length<3) return false;
  const reference=points.reduce((sum,point)=>sum+point[0],0)/points.length;
  let testLon=lon;
  while(testLon-reference>180) testLon-=360;
  while(testLon-reference<-180) testLon+=360;
  let inside=false;
  for(let i=0,j=points.length-1;i<points.length;j=i++){
    const xi=points[i][0],xj=points[j][0],yi=points[i][1],yj=points[j][1];
    const crosses=((yi>lat)!==(yj>lat)) && (testLon<(xj-xi)*(lat-yi)/((yj-yi)||1e-12)+xi);
    if(crosses) inside=!inside;
  }
  return inside;
}
function pointInPolygon(lon,lat,polygon){
  if(!polygon.length || !pointInRing(lon,lat,polygon[0])) return false;
  for(let index=1;index<polygon.length;index++) if(pointInRing(lon,lat,polygon[index])) return false;
  return true;
}
function countryAt(lon,lat){
  for(const feature of features){
    for(const polygon of geometryPolygons(feature.geometry)){
      if(pointInPolygon(lon,lat,polygon)) return feature;
    }
  }
  return null;
}

let renderer;
try{
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
}catch(error){
  errorBox.style.display='flex'; errorBox.textContent='3D RENDERER UNAVAILABLE'; throw error;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
renderer.setSize(viewport.clientWidth,viewport.clientHeight,false);
renderer.setClearColor(config.backgroundColor||'__BACKGROUND__',1);
renderer.outputColorSpace=THREE.SRGBColorSpace;
viewport.appendChild(renderer.domElement);

const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(36,Math.max(viewport.clientWidth,1)/Math.max(viewport.clientHeight,1),0.1,100);
camera.position.set(0,0,3.15);
const tiltGroup=new THREE.Group();
const spinGroup=new THREE.Group();
tiltGroup.add(spinGroup); scene.add(tiltGroup);
const globe=new THREE.Mesh(new THREE.SphereGeometry(1,128,64),new THREE.MeshBasicMaterial({map:null}));
spinGroup.add(globe);
globe.material.map=makeTexture(); globe.material.needsUpdate=true;

const atmosphere=new THREE.Mesh(
  new THREE.SphereGeometry(1.025,96,48),
  new THREE.MeshBasicMaterial({color:0x315166,transparent:true,opacity:0.16,side:THREE.BackSide,depthWrite:false})
);
spinGroup.add(atmosphere);
const gridMaterial=new THREE.LineBasicMaterial({color:0x43515a,transparent:true,opacity:0.38});
for(let lat=-60;lat<=60;lat+=30){
  const points=[]; for(let lon=-180;lon<=180;lon+=3) points.push(spherePoint(lon,lat,1.006));
  spinGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),gridMaterial));
}
for(let lon=-150;lon<=180;lon+=30){
  const points=[]; for(let lat=-88;lat<=88;lat+=2) points.push(spherePoint(lon,lat,1.006));
  spinGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),gridMaterial));
}

const raycaster=new THREE.Raycaster();
const pointer=new THREE.Vector2();
if(selectedName){
  const initialFeature=features.find(item=>String(item.properties?.name||'')===selectedName);
  if(initialFeature){
    const center=countryCenter(initialFeature);
    config.view={...(config.view||{}),longitude:center[0],latitude:center[1]};
  }
}
let targetYaw=-Math.PI/2-(config.view?.longitude||0)*Math.PI/180;
let targetPitch=(config.view?.latitude||0)*Math.PI/180;
let targetDistance=config.view?.distance||3.15;
let yaw=targetYaw,pitch=targetPitch,distance=targetDistance;
let dragging=false,moved=false,startX=0,startY=0,lastX=0,lastY=0;

function refreshTexture(){
  const previous=globe.material.map;
  globe.material.map=makeTexture(); globe.material.needsUpdate=true;
  if(previous) previous.dispose();
}
function setView(lon,lat,distanceValue){
  targetYaw=-Math.PI/2-Number(lon||0)*Math.PI/180;
  targetPitch=Math.max(-1.25,Math.min(1.25,Number(lat||0)*Math.PI/180));
  if(distanceValue) targetDistance=Number(distanceValue);
}
function eventHit(event){
  const rect=renderer.domElement.getBoundingClientRect();
  pointer.x=((event.clientX-rect.left)/rect.width)*2-1;
  pointer.y=-((event.clientY-rect.top)/rect.height)*2+1;
  raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObject(globe,false)[0];
  if(!hit) return null;
  const local=globe.worldToLocal(hit.point.clone()).normalize();
  const latitude=Math.asin(Math.max(-1,Math.min(1,local.y)))*180/Math.PI;
  const phi=Math.atan2(local.z,-local.x)*180/Math.PI;
  let longitude=phi-180;
  while(longitude>180) longitude-=360;
  while(longitude<-180) longitude+=360;
  return countryAt(longitude,latitude);
}
function showTooltip(event,feature){
  if(!feature){tooltip.style.display='none';return;}
  const name=String(feature.properties?.name||'');
  const item=dataByName.get(name);
  if(!item || item.value===null || item.value===undefined){
    tooltip.innerHTML=`<b>${escapeHtml(name)}</b><br><span class="muted">DATA UNAVAILABLE</span>`;
  }else{
    tooltip.innerHTML=`<b>${escapeHtml(item.country||name)}</b> &nbsp; ${escapeHtml(item.iso3||'')}<br>`+
      `<span class="metric">${escapeHtml(item.metricLabel||'VALUE')}</span> &nbsp; <b>${escapeHtml(item.displayValue||item.value)}</b><br>`+
      `${escapeHtml(item.period||'')}<br><span class="muted">${escapeHtml(item.source||'UNKNOWN')} | ${escapeHtml(item.status||'')}</span>`;
  }
  tooltip.style.display='block';
  const left=Math.min(event.clientX+14,window.innerWidth-tooltip.offsetWidth-8);
  const top=Math.min(event.clientY+14,window.innerHeight-tooltip.offsetHeight-8);
  tooltip.style.left=`${Math.max(8,left)}px`; tooltip.style.top=`${Math.max(8,top)}px`;
}
renderer.domElement.addEventListener('pointerdown',event=>{
  dragging=true;moved=false;startX=lastX=event.clientX;startY=lastY=event.clientY;
  viewport.classList.add('dragging');tooltip.style.display='none';renderer.domElement.setPointerCapture(event.pointerId);
});
renderer.domElement.addEventListener('pointermove',event=>{
  if(dragging){
    const dx=event.clientX-lastX,dy=event.clientY-lastY;
    if(Math.hypot(event.clientX-startX,event.clientY-startY)>4)moved=true;
    targetYaw+=dx*0.0065; targetPitch=Math.max(-1.25,Math.min(1.25,targetPitch+dy*0.0055));
    lastX=event.clientX;lastY=event.clientY;return;
  }
  showTooltip(event,eventHit(event));
});
renderer.domElement.addEventListener('pointerleave',()=>{if(!dragging)tooltip.style.display='none';});
renderer.domElement.addEventListener('pointerup',event=>{
  dragging=false;viewport.classList.remove('dragging');
  if(!moved){
    const feature=eventHit(event);
    if(feature){
      selectedName=String(feature.properties?.name||'');refreshTexture();showTooltip(event,feature);
      if(terminalBridge)terminalBridge.selectCountry(selectedName);
    }
  }
});
renderer.domElement.addEventListener('wheel',event=>{
  event.preventDefault();targetDistance=Math.max(1.65,Math.min(4.7,targetDistance+event.deltaY*0.0025));
},{passive:false});
renderer.domElement.addEventListener('dblclick',()=>setView(config.view?.longitude||0,config.view?.latitude||0,config.view?.distance||3.15));

for(const piece of config.pieces||[]){
  const item=document.createElement('div');item.className='legend-item';
  const swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=piece.color;
  const label=document.createElement('span');label.textContent=piece.label||'';
  item.append(swatch,label);legend.appendChild(item);
}
function resize(){
  const width=Math.max(viewport.clientWidth,1),height=Math.max(viewport.clientHeight,1);
  renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
}
window.ajaxResize=resize;
window.ajaxCountryAtCoordinates=(longitude,latitude)=>{
  const feature=countryAt(Number(longitude),Number(latitude));
  return feature ? String(feature.properties?.name||'') : '';
};
window.ajaxProjectedCountryPick=name=>{
  const feature=features.find(item=>String(item.properties?.name||'')===String(name||''));
  if(!feature) return '';
  const center=countryCenter(feature);
  scene.updateMatrixWorld(true);
  const projected=globe.localToWorld(spherePoint(center[0],center[1],1).clone()).project(camera);
  const rect=renderer.domElement.getBoundingClientRect();
  const hit=eventHit({
    clientX:rect.left+(projected.x+1)*rect.width/2,
    clientY:rect.top+(1-projected.y)*rect.height/2,
  });
  return hit ? String(hit.properties?.name||'') : '';
};
window.ajaxSelectCountry=name=>{
  selectedName=String(name||'');refreshTexture();
  const feature=features.find(item=>String(item.properties?.name||'')===selectedName);
  if(feature){const center=countryCenter(feature);setView(center[0],center[1],config.view?.distance||3.15);}
};
window.addEventListener('resize',resize);
function animate(){
  yaw+=(targetYaw-yaw)*0.11;pitch+=(targetPitch-pitch)*0.11;distance+=(targetDistance-distance)*0.11;
  spinGroup.rotation.y=yaw;tiltGroup.rotation.x=pitch;camera.position.z=distance;
  renderer.render(scene,camera);requestAnimationFrame(animate);
}
animate();
</script></body></html>'''
        return (
            template.replace("__BACKGROUND__", AJAX_BACKGROUND)
            .replace("__THREE_SOURCE__", json.dumps(_asset_source(str(self.asset_path))))
            .replace("__THREE_CORE_SOURCE__", json.dumps(_asset_source(str(self.core_asset_path))))
            .replace("__CONFIG__", json.dumps(payload, separators=(",", ":")))
            .replace("__GEOJSON__", json.dumps(geojson, separators=(",", ":")))
        )
