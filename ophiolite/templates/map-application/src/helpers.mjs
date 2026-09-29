let proof='';
export async function bootstrap(){
 const response=await fetch('/api/bootstrap',{method:'POST',headers:{'X-Ophiolite-Bootstrap':'1'}});
 if(!response.ok)throw new Error('Open this application on its configured local address.');
 proof=(await response.json()).proof;
}
export async function request(action,body={}){
 const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Ophiolite-Proof':proof},body:JSON.stringify(body)});
 const value=await response.json();if(!response.ok)throw Object.assign(new Error(value.message),{violations:value.violations||[]});return value;
}
// A well's popup: its name for everyone; identifiers, revision and source row only under "Technical details".
export function popup(properties){
 const technical=[['Well',properties.entity_id],['Source',properties.source_asset_id],['Revision',properties.source_revision],['Row',properties.source_row]].filter(([,value])=>value);
 return {name:properties.name||'Unnamed well',technical};
}
export function bounds(bbox){return bbox?[[bbox[0],bbox[1]],[bbox[2],bbox[3]]]:null;}
