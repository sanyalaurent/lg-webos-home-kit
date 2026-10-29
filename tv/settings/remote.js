/* SPDX-License-Identifier: MIT */
/* ES5 / Node 8. Existing root access only. Never changes services or firmware. */
'use strict';
var fs = require('fs');
var cp = require('child_process');
var STATE = '/var/lib/lg-settings-kit';
var PRELOAD = 'com.webos.service.preloadmanager.supportAppList';
var SPECS = {
  'live-plus-off': {category: 'option', key: 'livePlus', value: 'off'},
  'live-promotion-off': {category: 'option', key: 'livePromotion', value: 'off'},
  'limit-ad-tracking': {category: 'general', key: 'lmt', value: 'on'},
  'handsfree-voice-off': {category: 'general', key: 'voiceLongDistance', value: 'off'},
  'browser-preload-off': {app: 'com.webos.app.browser', value: false},
  'netflix-preload-off': {app: 'netflix', value: false}
};
function canonical(v) {
  if (Array.isArray(v)) return v.map(canonical);
  if (v && typeof v === 'object') {
    var out = {}; Object.keys(v).sort().forEach(function (k) { out[k] = canonical(v[k]); }); return out;
  }
  return v;
}
function equal(a, b) { return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b)); }
function luna(uri, args) {
  var output = cp.execFileSync('/usr/bin/luna-send',
    ['-n', '1', '-w', '5000', '-f', 'luna://' + uri, JSON.stringify(args)],
    {encoding: 'utf8', timeout: 7000, maxBuffer: 524288, input: ''});
  var reply = JSON.parse(output);
  if (reply.returnValue !== true) throw new Error('Luna request refused');
  return reply;
}
function preloadList() {
  var r = luna('com.webos.service.config/getConfigs', {configNames: [PRELOAD]});
  var list = r.configs && r.configs[PRELOAD];
  if (!Array.isArray(list) || list.length > 256) throw new Error('Unknown preload schema');
  return list;
}
function entry(list, app) {
  var matches = list.filter(function (v) { return v && v.id === app; });
  if (matches.length !== 1 || typeof matches[0].isEnabled !== 'boolean')
    throw new Error('Unknown or absent preload entry');
  return matches[0];
}
function read(id) {
  var s = SPECS[id];
  if (!s) throw new Error('Unknown setting');
  if (s.app) return entry(preloadList(), s.app).isEnabled;
  var r = luna('com.webos.settingsservice/getSystemSettings', {category: s.category, keys: [s.key]});
  var v = r.settings && r.settings[s.key];
  if (v !== 'on' && v !== 'off') throw new Error('Unknown setting type/value');
  return v;
}
function write(id, value) {
  var s = SPECS[id];
  if (s.app) {
    if (typeof value !== 'boolean') throw new Error('Invalid preload value');
    var list = preloadList();
    entry(list, s.app).isEnabled = value;
    var configs = {}; configs[PRELOAD] = list;
    luna('com.webos.service.config/setConfigs', {configs: configs});
    if (!equal(preloadList(), list)) throw new Error('Preload round-trip mismatch');
  } else {
    if (value !== 'on' && value !== 'off') throw new Error('Invalid setting value');
    var values = {}; values[s.key] = value;
    luna('com.webos.settingsservice/setSystemSettings', {category: s.category, settings: values});
    if (read(id) !== value) throw new Error('Setting round-trip mismatch');
  }
}
function plan(ids) {
  return ids.map(function (id) {
    try {
      var before = read(id), after = SPECS[id].value;
      return {id: id, before: before, after: after, status: before === after ? 'unchanged' : 'change'};
    } catch (_) { return {id: id, status: 'unsupported_or_unknown'}; }
  });
}
function safeId(id) { return typeof id === 'string' && /^[0-9TZabcdef-]{10,80}$/.test(id); }
function journals() {
  if (!fs.existsSync(STATE)) return [];
  return fs.readdirSync(STATE).filter(function (name) {
    return name.slice(-5) === '.json' && safeId(name.slice(0, -5));
  }).sort().slice(-100).map(function (name) {
    try {
      var r = JSON.parse(fs.readFileSync(STATE + '/' + name, 'utf8'));
      return {backup_id: name.slice(0, -5), status: typeof r.status === 'string' ? r.status : 'unknown'};
    } catch (_) { return {backup_id: name.slice(0, -5), status: 'unknown'}; }
  });
}
function sync() { cp.execFileSync('/bin/sync', [], {timeout: 10000}); }
function prepareState() {
  try { if (fs.lstatSync(STATE).isSymbolicLink()) throw new Error('Unsafe state directory'); }
  catch (e) { if (e.code !== 'ENOENT') throw e; }
  if (!fs.existsSync(STATE)) fs.mkdirSync(STATE, 448);
  if (!fs.statSync(STATE).isDirectory() || fs.statSync(STATE).uid !== 0)
    throw new Error('Unsafe state directory owner');
  fs.chmodSync(STATE, 448);
}
function save(record) {
  var path = STATE + '/' + record.id + '.json';
  var fd = fs.openSync(path + '.new', 'w', 384);
  var encoded = JSON.stringify(record);
  try {
    if (fs.writeSync(fd, encoded) !== Buffer.byteLength(encoded)) throw new Error('Short journal write');
    fs.fsyncSync(fd);
  }
  finally { fs.closeSync(fd); }
  fs.renameSync(path + '.new', path); sync();
  if (!equal(JSON.parse(fs.readFileSync(path, 'utf8')), record)) throw new Error('Journal read-back mismatch');
}
function lock() {
  prepareState();
  var directory = STATE + '/lock';
  if (fs.existsSync(directory)) {
    var old = JSON.parse(fs.readFileSync(directory + '/owner', 'utf8'));
    var boot = fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8');
    var alive = false;
    try { process.kill(old.pid, 0); alive = true; } catch (_) {}
    if (old.boot === boot && alive) throw new Error('Another settings operation is active');
    fs.unlinkSync(directory + '/owner'); fs.rmdirSync(directory);
  }
  fs.mkdirSync(directory, 448);
  fs.writeFileSync(directory + '/owner', JSON.stringify({pid: process.pid,
    boot: fs.readFileSync('/proc/sys/kernel/random/boot_id', 'utf8')}), {mode: 384, flag: 'wx'});
  return function () { fs.unlinkSync(directory + '/owner'); fs.rmdirSync(directory); };
}
function restore(record) {
  return record.operations.map(function (op) {
    try {
      var value = read(op.id);
      if (value === op.before) return {id: op.id, status: 'already_restored'};
      if (value !== op.after) return {id: op.id, status: 'conflict_not_overwritten'};
      write(op.id, op.before);
      return {id: op.id, status: 'restored_verified'};
    } catch (_) { return {id: op.id, status: 'restore_failed_or_unknown'}; }
  });
}
function validRecord(r, id) {
  if (!r || r.schema !== 1 || r.id !== id || !Array.isArray(r.operations) || r.operations.length > 6)
    throw new Error('Invalid private backup');
  var seen = {};
  r.operations.forEach(function (op) {
    var s = SPECS[op.id];
    if (!s || seen[op.id] || op.after !== s.value ||
      (s.app ? typeof op.before !== 'boolean' : op.before !== 'on' && op.before !== 'off'))
      throw new Error('Invalid backup operation');
    seen[op.id] = true;
  });
}
function main(request) {
  if (process.getuid() !== 0) throw new Error('Existing root SSH is required');
  var ids = request.settings;
  if (!Array.isArray(ids) || ids.length > 6 || ids.some(function (id, i) {
    return !Object.prototype.hasOwnProperty.call(SPECS, id) || ids.indexOf(id) !== i;
  })) throw new Error('Invalid setting selection');
  if (request.action === 'plan') return {status: 'preview_only', settings: plan(ids), private_backups: journals()};
  if (request.action !== 'apply' && request.action !== 'rollback') throw new Error('Invalid action');
  var unlock = lock();
  try {
    if (request.action === 'rollback') {
      if (!safeId(request.id)) throw new Error('Invalid backup id');
      var record = JSON.parse(fs.readFileSync(STATE + '/' + request.id + '.json', 'utf8'));
      validRecord(record, request.id);
      var restored = restore(record);
      var complete = restored.every(function (v) { return v.status === 'restored_verified' || v.status === 'already_restored'; });
      record.status = complete ? 'restored' : 'restore_incomplete'; save(record);
      return {status: record.status, backup_id: record.id, settings: restored};
    }
    if (journals().some(function (r) { return ['pending', 'recovery_required', 'restore_incomplete', 'unknown'].indexOf(r.status) !== -1; }))
      throw new Error('Recover the previous private journal before applying again');
    var preview = plan(ids);
    var operations = preview.filter(function (v) { return v.status === 'change'; });
    var unknown = preview.filter(function (v) { return v.status === 'unsupported_or_unknown'; });
    if (!operations.length) return {status: unknown.length ? 'unsupported_or_unknown' : 'unchanged', settings: preview};
    if (!safeId(request.id) || fs.existsSync(STATE + '/' + request.id + '.json')) throw new Error('Invalid/existing backup id');
    var backup = {schema: 1, id: request.id, status: 'pending', operations: operations};
    save(backup); // durable private backup precedes the first mutation
    try {
      operations.forEach(function (op) {
        if (read(op.id) !== op.before) throw new Error('Setting changed since preview');
        write(op.id, op.after);
      });
    } catch (_) {
      var recovery = restore(backup);
      backup.status = recovery.every(function (v) {
        return v.status === 'restored_verified' || v.status === 'already_restored';
      }) ? 'apply_failed_restored' : 'recovery_required'; save(backup);
      return {status: backup.status, backup_id: backup.id, recovery: recovery};
    }
    backup.status = unknown.length ? 'partial_verified' : 'applied_verified'; save(backup);
    return {status: backup.status, backup_id: backup.id, settings: preview,
      note: 'Preload changes are persistent config only; runtime/memory effects are unverified.'};
  } finally { unlock(); }
}
if (typeof module !== 'undefined') module.exports = {SPECS: SPECS, plan: plan, restore: restore, validRecord: validRecord, safeId: safeId};
if (require.main === module) {
  try { process.stdout.write(JSON.stringify(main(JSON.parse(process.argv[2]))) + '\n'); }
  catch (_) { process.stderr.write('Settings operation failed; no private values are printed. Inspect the private journal before retrying.\n'); process.exitCode = 1; }
}
