// Vercel build command. Only the public API origin is written into browser code.
import {writeFileSync} from 'node:fs';
const api = process.env.PUBLIC_API_BASE_URL?.replace(/\/$/, '');
if (!api || !api.startsWith('https://')) throw new Error('Set PUBLIC_API_BASE_URL to your HTTPS Cloud Run URL in Vercel.');
new URL(api);
writeFileSync('frontend/js/deployment-config.js', 'window.ABHYASAM_API_BASE = ' + JSON.stringify(api) + ';\n');
console.log('Frontend configured for Cloud Run.');
