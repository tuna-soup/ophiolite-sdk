import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {bootstrap,request,popup,bounds} from './helpers.mjs';
import './style.css';
type Feature={id:string;geometry:{type:'Point';coordinates:[number,number]}|null;properties:Record<string,string|null>};
type Wells={type:'FeatureCollection';features:Feature[]};
// No tile service is contacted: the map draws the wells on a plain background (add a basemap you are licensed to use).
const style:maplibregl.StyleSpecification={version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#f4f1ea'}}]};
function Details({feature}:{feature:Feature}){
 const {name,technical}=popup(feature.properties);
 return <article aria-label={name}><h2>{name}</h2><details><summary>Technical details</summary><dl>{technical.map(([label,value])=><React.Fragment key={label}><dt>{label}</dt><dd>{value}</dd></React.Fragment>)}</dl></details></article>;
}
function App(){
 const container=useRef<HTMLDivElement>(null),map=useRef<maplibregl.Map|null>(null);
 const [wells,setWells]=useState<Wells|null>(null),[unlocated,setUnlocated]=useState(0),[selected,setSelected]=useState<Feature|null>(null),[message,setMessage]=useState('Connecting to the local application…');
 async function load(){
  try{
   await bootstrap();
   const [extent,answer]=await Promise.all([request('extent'),request('wells')]);
   setWells(answer.wells);setUnlocated(answer.unlocated);
   setMessage(extent.count?`${extent.count} wells you may read are located.`:'No well you may read is located.');
   const located=answer.wells.features.filter((f:Feature)=>f.geometry);
   if(container.current&&!map.current){
    try{
     const box=bounds(extent.bbox) as [[number,number],[number,number]]|null;
     const m=new maplibregl.Map({container:container.current,style,...(box?{bounds:box,fitBoundsOptions:{padding:40}}:{center:[0,0],zoom:1})});map.current=m;
     m.on('load',()=>{m.addSource('wells',{type:'geojson',data:{...answer.wells,features:located}});
      m.addLayer({id:'wells',type:'circle',source:'wells',paint:{'circle-radius':6,'circle-color':'#2f6f5e'}});
      m.on('click','wells',e=>{const id=e.features?.[0]?.properties?.entity_id;setSelected(answer.wells.features.find((f:Feature)=>f.id===id)||null);});});
    }catch{setMessage('The map cannot be drawn in this browser; the wells are listed below.');}
   }
  }catch(error:any){setMessage(error.message);}
 }
 useEffect(()=>{void load();},[]);
 return <main><h1>Wells on a map</h1><p>The wells you may read, where the newest source you may read locates them. Coordinates are shown as the server converted them to longitude and latitude.</p>
 <p role="status">{message}</p>
 <div ref={container} className="map" role="region" aria-label="Map of the wells"/>
 {selected&&<Details feature={selected}/>}
 {wells&&<section aria-label="Wells"><h2>Wells</h2><ul>{wells.features.map(f=><li key={f.id}><button onClick={()=>setSelected(f)}>{f.properties.name}</button>{!f.geometry&&' (no location you may read)'}</li>)}</ul>{unlocated>0&&<p>{unlocated} without a location you may read.</p>}</section>}
 <button onClick={()=>void load()}>Retry</button>
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
