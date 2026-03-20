import { buildCombinedPoliticianReceipt } from '../packages/sources/index.js';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const envPath = resolve(__dirname, '../apps/api/.env');
const envContent = readFileSync(envPath, 'utf8');
const fecKey = envContent.match(/FEC_API_KEY=(.+)/)?.[1]?.trim() ?? 'DEMO_KEY';

const result = await buildCombinedPoliticianReceipt(
  'S0WV00090',
  ['ExxonMobil', 'Chevron', 'American Petroleum Institute', 'Murray Energy'],
  [2021, 2022, 2018, 2024],
  fecKey
);
console.log(JSON.stringify(result.narrative, null, 2));
