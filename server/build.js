import {build} from 'esbuild';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
await build({entryPoints:[path.join(root,'public/app.js')],bundle:true,format:'iife',minify:true,
  nodePaths:[path.join(root,'server/node_modules')],outfile:path.join(root,'public/app.bundle.js')});
console.log('Built offline browser bundle');
