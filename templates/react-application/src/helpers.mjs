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
export function sample(value){return value===null?'Missing':String(value);}
