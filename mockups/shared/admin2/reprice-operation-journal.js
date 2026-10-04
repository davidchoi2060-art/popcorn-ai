/* Reprice-only per-tab journal. Absence, HTTP errors and time never confirm failure. */
(function (global) {
  'use strict';
  var KEY = 'popcorn.admin.reprice.operation.v1';
  var FIELDS = ['contract_version', 'canonical_version', 'operation_id', 'actor_id',
    'environment', 'action', 'target', 'request_fingerprint'];
  var RESULTS = ['log_id', 'changed', 'up', 'down', 'locked', 'dropped'];
  var UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  var SHA = /^[0-9a-f]{64}$/;
  function object(v) { return !!v && typeof v === 'object' && !Array.isArray(v); }
  function uuid(v) { return typeof v === 'string' && v.length === 36 && UUID.test(v); }
  function safe(v, positive) { return Number.isSafeInteger(v) && v >= (positive ? 1 : 0); }
  function scope(v) { return ['live', 'selling', 'all'].indexOf(v) !== -1; }
  function copy(v) { return JSON.parse(JSON.stringify(v)); }
  function context(v) {
    return object(v) && v.contract_version === 'admin_operation_v1'
      && v.canonical_version === 'reprice_request_v1' && v.action === 'reprice_apply'
      && safe(v.actor_id, true) && uuid(v.environment);
  }
  function identity(v) {
    if (!context(v) || !uuid(v.operation_id) || !object(v.target)
      || Object.keys(v.target).join(',') !== 'scope' || !scope(v.target.scope)
      || typeof v.request_fingerprint !== 'string' || v.request_fingerprint.length !== 64
      || !SHA.test(v.request_fingerprint)) return null;
    var out = {}; FIELDS.forEach(function (k) { out[k] = copy(v[k]); }); return out;
  }
  function terminal(v, expected, status) {
    var id = identity(v);
    if (status !== 200 || !id || JSON.stringify(id) !== JSON.stringify(expected)
      || !uuid(v.receipt_id) || !object(v.result)) return null;
    var result = {};
    if (v.state === 'applied') {
      if (!RESULTS.every(function (k) { return safe(v.result[k], k === 'log_id'); })) return null;
      RESULTS.forEach(function (k) { result[k] = v.result[k]; });
      if ('scope' in v.result && v.result.scope !== id.target.scope) return null;
    } else if (v.state !== 'rejected') return null;
    return Object.assign(id, {state:v.state, receipt_id:v.receipt_id, result:result});
  }
  function canonical(payload) {
    var e = payload && payload.expected;
    if (!payload || !scope(payload.scope) || !safe(payload.expect_changed, false)
      || !object(e) || Object.keys(e).sort().join(',') !== 'fingerprint,scope,version'
      || !['reprice_basis_v1','reprice_basis_v2'].includes(e.version) || !scope(e.scope) || typeof e.fingerprint !== 'string'
      || e.fingerprint.length !== 64 || !SHA.test(e.fingerprint) || typeof payload.note !== 'string') {
      throw new Error('재산정 요청을 확인할 수 없습니다.');
    }
    // Reject lone UTF-16 surrogates rather than letting TextEncoder replace them.
    for (var i = 0; i < payload.note.length; i++) {
      var c = payload.note.charCodeAt(i);
      if (c >= 0xD800 && c <= 0xDBFF) {
        var n = payload.note.charCodeAt(++i);
        if (!(n >= 0xDC00 && n <= 0xDFFF)) throw new Error('메모의 문자를 확인하십시오.');
      } else if (c >= 0xDC00 && c <= 0xDFFF) throw new Error('메모의 문자를 확인하십시오.');
    }
    return JSON.stringify(['reprice_request_v1', 'reprice_apply', payload.scope,
      String(payload.expect_changed), [e.version, e.scope, e.fingerprint], payload.note]);
  }
  function fingerprint(payload, crypto) {
    if (!crypto || !crypto.subtle || typeof global.TextEncoder !== 'function') {
      return Promise.reject(new Error('요청 확인 기능을 사용할 수 없습니다.'));
    }
    var raw;
    try { raw = new global.TextEncoder().encode(canonical(payload)); }
    catch (error) { return Promise.reject(error); }
    return crypto.subtle.digest('SHA-256', raw).then(function (buffer) {
      return Array.from(new Uint8Array(buffer)).map(function (b) {
        return b.toString(16).padStart(2, '0');
      }).join('');
    });
  }
  function create() {
    var storage, crypto, record = null, failed = false, preparing = false;
    function persist(next) {
      try {
        var raw = JSON.stringify(next);
        storage.setItem(KEY, raw);
        if (storage.getItem(KEY) !== raw) throw new Error('Storage readback failed');
        return true;
      } catch (_) { failed = true; return false; }
    }
    try {
      storage = global.sessionStorage; crypto = global.crypto;
      var raw = storage.getItem(KEY);
      if (raw !== null) {
        var saved = JSON.parse(raw), id = identity(saved.identity);
        if (!object(saved) || saved.version !== 1 || !id
          || ['writing','uncertain','applied','rejected'].indexOf(saved.phase) < 0) throw new Error('Invalid journal');
        var ack = saved.receipt === null ? null : terminal(saved.receipt, id, 200);
        if ((saved.phase === 'applied' || saved.phase === 'rejected')
          ? !ack || ack.state !== saved.phase : saved.receipt !== null) throw new Error('Invalid acknowledgment');
        record = {version:1, identity:id, phase:saved.phase === 'writing' ? 'uncertain' : saved.phase, receipt:ack};
        if (saved.phase === 'writing') persist(record);
      }
    } catch (_) { failed = true; }
    function pending() { return failed || preparing || !!(record && !record.receipt); }
    function matchesContext(value) {
      return context(value) && (!record || ['actor_id','environment','action','contract_version','canonical_version']
        .every(function (k) { return value[k] === record.identity[k]; }));
    }
    function prepare(value, payload, isCurrent) {
      if (pending() || !context(value) || !crypto || typeof crypto.randomUUID !== 'function') {
        return Promise.reject(new Error('이전 요청 결과 또는 요청 확인 기능을 먼저 확인하십시오.'));
      }
      preparing = true;
      var command, owner, op;
      try { command = copy(payload); owner = copy(value); op = crypto.randomUUID(); }
      catch (error) { preparing = false; return Promise.reject(error); }
      return fingerprint(command, crypto).then(function (hash) {
        if (!uuid(op) || (isCurrent && !isCurrent())) throw new Error('미리보기를 다시 확인하십시오.');
        var id = identity(Object.assign({}, owner, {operation_id:op,
          target:{scope:command.scope}, request_fingerprint:hash}));
        if (!id) throw new Error('요청 정보를 확인할 수 없습니다.');
        var next = {version:1, identity:id, phase:'writing', receipt:null};
        if (!persist(next)) throw new Error('요청 확인 기록을 저장하지 못했습니다.');
        record = next;
        return Object.assign(command, {operation_id:op, operation_context:owner, request_fingerprint:hash});
      }).finally(function () { preparing = false; });
    }
    function observe(candidate, status, expected) {
      if (!record || (expected && JSON.stringify(identity(expected)) !== JSON.stringify(record.identity))) return null;
      var ack = terminal(candidate, record.identity, status);
      if (record.receipt) return copy(record); // Preserve the first matched terminal acknowledgment.
      record = {version:1, identity:record.identity, phase:ack ? ack.state : 'uncertain', receipt:ack};
      persist(record);
      return copy(record);
    }
    return {prepare:prepare, observe:observe, pending:pending, matchesContext:matchesContext,
      snapshot:function () { return record && copy(record); }, storageFailed:function () { return failed; }};
  }
  global.RepriceOperationJournal = {create:create, canonical:canonical, fingerprint:fingerprint};
})(window);
