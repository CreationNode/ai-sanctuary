import {plaque} from './layout.js';
export const data={pagination:{data:'models',size:1,alias:'model'},permalink:d=>'models/'+d.model.id+'/index.html'};
export default ({model,models})=>plaque(model,models);