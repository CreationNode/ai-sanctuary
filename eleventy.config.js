import fs from 'node:fs';
import path from 'node:path';

export default function config(site) {
  site.addWatchTarget('registry/');
  site.addWatchTarget('plaques/');
  for (const filename of ['hall.css','hall.js','terminal.jpg','icon.svg']) {
    site.addPassthroughCopy({['hall/assets/'+filename]:'assets/'+filename});
  }
  for (const [family, styles] of [['baskervville',['400-normal','400-italic']],['dm-sans',['400-normal','600-normal']]]) {
    for (const style of styles) {
      const filename=family+'-latin-'+style+'.woff2';
      site.addPassthroughCopy({['node_modules/@fontsource/'+family+'/files/'+filename]:'assets/'+filename});
    }
    site.addPassthroughCopy({['node_modules/@fontsource/'+family+'/LICENSE']:'assets/'+family+'-license.txt'});
  }
  site.addGlobalData('models', () => fs.readdirSync('registry').filter(f => f.endsWith('.yaml'))
    .map(f => JSON.parse(fs.readFileSync(path.join('registry', f), 'utf8').replace(/^\uFEFF/, '')))
    .sort((a,b) => a.release_date.localeCompare(b.release_date) || a.parameters - b.parameters));
  return {dir:{input:'hall',output:'dist'},templateFormats:['11ty.js']};
}