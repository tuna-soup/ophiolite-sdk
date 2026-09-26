import {defineConfig} from 'vite';
export default defineConfig({server:{cors:false,host:'127.0.0.1',port:56110,strictPort:true,allowedHosts:['127.0.0.1'],proxy:{'/api':{target:'http://127.0.0.1:56111',changeOrigin:false}}}});
