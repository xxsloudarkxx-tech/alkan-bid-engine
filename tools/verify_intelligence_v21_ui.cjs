/* Same full V2 browser acceptance, extended with catalog, drag/drop and actual costs. */
process.env.ALKAN_V21='1';
process.env.ALKAN_AUDIT_DIR=require('node:path').resolve(__dirname,'../data/v21_audit');
require('./verify_intelligence_ui.cjs');
