import { buildLive990Receipt } from '../packages/sources/index.js';

const result = await buildLive990Receipt('Gates Foundation', '562618866');
console.log(JSON.stringify(result.narrative, null, 2));
