import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {bootstrap,request,sample} from './helpers.mjs';
import './style.css';
type Asset={asset_id:string;revision:string;name:string;curves:string[]};
type View={descriptor_html:string;axis:number[];values:(number|null)[];unit:string;depth_unit:string};
function App(){
 const [assets,setAssets]=useState<Asset[]>([]),[chosen,setChosen]=useState(0),[view,setView]=useState<View|null>(null),[mnemonic,setMnemonic]=useState('CALC'),[staged,setStaged]=useState(false),[valid,setValid]=useState(false),[receipt,setReceipt]=useState<any>(null),[message,setMessage]=useState('Connecting to the local application…'),[violations,setViolations]=useState<string[]>([]),[busy,setBusy]=useState(false),[recipients,setRecipients]=useState('');
 async function run(action:()=>Promise<void>){setBusy(true);setViolations([]);try{await action();}catch(error:any){setMessage(error.message);setViolations(error.violations||[]);}finally{setBusy(false);}}
 async function list(){const result=await request('list');setAssets(result.assets);setMessage(result.assets.length?'Select a permitted curve.':'No permitted curves are available.');}
 useEffect(()=>{void run(async()=>{await bootstrap();await list();});},[]);
 const asset=assets[chosen],selection=asset?{asset_id:asset.asset_id,revision:asset.revision,curve:asset.curves[0]}:null;
 return <main><h1>Local curve calculation</h1><p>Read an exact version, multiply its values by two, then review and publish a derived curve. Missing samples stay missing.</p>
 <p role="status">{message}</p>{violations.length>0&&<ul aria-label="Corrections needed">{violations.map(v=><li key={v}>{v}</li>)}</ul>}
 <button disabled={busy} onClick={()=>run(list)}>Retry</button>
 <label>Permitted data <select value={chosen} disabled={staged||busy} onChange={e=>{setChosen(Number(e.target.value));setView(null);}}>{assets.map((a,i)=><option key={a.asset_id} value={i}>{a.name}</option>)}</select></label>
 <button disabled={!selection||busy} onClick={()=>run(async()=>{setView(await request('read',selection!));setMessage('Exact source version loaded.');})}>Read curve</button>
 {view&&<><div aria-label="Scientific description" dangerouslySetInnerHTML={{__html:view.descriptor_html}}/><h2>Original samples</h2><table><thead><tr><th>Depth ({view.depth_unit})</th><th>Value ({view.unit})</th></tr></thead><tbody>{view.axis.map((depth,i)=><tr key={i}><td>{depth}</td><td>{sample(view.values[i])}</td></tr>)}</tbody></table>
 <label>New curve name <input value={mnemonic} onChange={e=>{setMnemonic(e.target.value);setValid(false);}} disabled={!!receipt}/></label>
 <button disabled={staged||busy} onClick={()=>run(async()=>{const value=await request('stage',{...selection,mnemonic});setStaged(true);setMessage(value.message);})}>Stage calculation</button>
 <button disabled={!staged||!!receipt||busy} onClick={()=>run(async()=>{const value=await request('validate',{mnemonic});setValid(value.valid);setMessage(value.message);})}>Validate</button>
 <button disabled={!valid||!!receipt||busy} onClick={()=>run(async()=>{const value=await request('publish');setReceipt(value);setMessage(value.message);})}>Publish derived curve</button></>}
 {receipt&&<section aria-label="Saved result"><h2>Derived result saved</h2><a href={receipt.workspace_url}>Open this result in Workspace</a><details><summary>Technical details</summary><pre>{JSON.stringify(receipt.receipt,null,2)}</pre></details><label>Recipients (comma separated) <input value={recipients} onChange={e=>setRecipients(e.target.value)}/></label><button disabled={busy||!recipients.trim()} onClick={()=>run(async()=>{const value=await request('share',{audience:recipients.split(',').map(x=>x.trim()).filter(Boolean)});setMessage(value.message||'The selected recipients can now read this result.');})}>Share result</button></section>}
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
