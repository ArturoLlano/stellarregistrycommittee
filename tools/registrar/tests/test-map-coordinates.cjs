const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..', '..', '..', 'public');
const ctx = { URLSearchParams, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(root, 'assets/js/map-coordinates.js'), 'utf8'), ctx);
const choose = ctx.TSRCMapCoordinates.forEntry;
const old = {object: {coordinates: {ra_hms:'18 00 00', dec_dms:'+20 00 00'}, inscription:{name:'Test'}}};
const visual = {object: {...old.object, coordinatesV:{ra_hms:'12 00 00',dec_dms:'-00 30 00'}}};
assert.equal(choose(old).raDeg,270);
assert.equal(choose(visual).raDeg,180);
assert.equal(choose(visual).decDeg,-0.5);
assert.equal(choose({object:{...old.object,coordinatesV:{ra_deg:0,dec_deg:0}}}).raDeg,0);
assert.equal(choose({object:{...old.object,coordinatesV:{ra_hms:'12 00 00'}}}).raDeg,270);
assert.equal(choose({object:{...old.object,coordinatesV:{ra_deg:999,dec_deg:0}}}).raDeg,270);

// Exercise the actual registry URL builder and iframe selection.
const registry = fs.readFileSync(path.join(root,'__app/registry.html'),'utf8');
const controls = {};
ctx.$ = id => controls[id] ||= {style:{},setAttribute(){}};
ctx.window = {open(){}};
const start=registry.indexOf('    function buildSkyUrl');
const end=registry.indexOf('    // Show internal notice',start);
vm.runInContext(registry.slice(start,end),ctx);
for(const [entry, expectedRA] of [[old,270],[visual,180]]){
  ctx.enableMap(entry,'Test','SAO 1');
  const url = new URL(controls.tsrcSkyFrame.src,'http://localhost');
  assert.equal(Number(url.searchParams.get('ra')),expectedRA);
  assert.equal(Number(url.searchParams.get('fov')),15);
}
for(const name of ['sky/index.html','__app/registry.html']){
  for(const match of fs.readFileSync(path.join(root,name),'utf8').matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)) {
    if(match[1].trim()) new vm.Script(match[1]);
  }
}
console.log('PASS: legacy fallback, visual preference, zero coordinates, invalid-pair fallback, actual iframe URLs, page syntax');
