import {spawn} from 'node:child_process';
import {createServer} from 'vite';
const backend=spawn(process.env.OPHIOLITE_PYTHON||'python3',['server/app.py',...(process.argv.includes('--live')?[]:['--fixture'])],{stdio:'inherit'});
const vite=await createServer();await vite.listen();vite.printUrls();
let closing=false;
async function close(code=0){if(closing)return;closing=true;backend.kill('SIGTERM');await vite.close();process.exit(code);}
process.on('SIGINT',()=>close());process.on('SIGTERM',()=>close());backend.on('exit',code=>close(code||0));
