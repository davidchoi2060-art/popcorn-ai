(function () {
  'use strict';

  var P = window.PAI = window.PAI || {};
  var KEY = 'pai-store-finder-entry-v1';
  var TTL = 10 * 60 * 1000;
  var MAX_TEXT = 10000;
  var MAX_PURPOSE = 200;
  var MAX_STORED = 64000;
  var SOURCES = ['home', 'category', 'product', 'global'];
  var FIELDS = ['version', 'entryId', 'timestamp', 'text', 'productId', 'source', 'purpose'];
  var hasOwn = Object.prototype.hasOwnProperty;

  function fail(code, message) {
    var error = new Error(message);
    error.code = code;
    return error;
  }

  function validInput(value) {
    return value && typeof value === 'object' && !Array.isArray(value) &&
      typeof value.text === 'string' && value.text.length <= MAX_TEXT &&
      (value.productId === null || (typeof value.productId === 'string' &&
        /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(value.productId))) &&
      SOURCES.indexOf(value.source) !== -1 &&
      (!hasOwn.call(value, 'purpose') || (typeof value.purpose === 'string' &&
        value.purpose.length <= MAX_PURPOSE));
  }

  function validEntry(value, now) {
    return validInput(value) && value.version === 1 &&
      typeof value.entryId === 'string' && /^[a-f0-9]{32}$/.test(value.entryId) &&
      Number.isSafeInteger(value.timestamp) && value.timestamp > 0 &&
      value.timestamp <= now && now - value.timestamp < TTL &&
      Object.keys(value).every(function (key) { return FIELDS.indexOf(key) !== -1; });
  }

  function nextId() {
    if (!window.crypto || typeof window.crypto.getRandomValues !== 'function') {
      throw fail('finder_entry_unavailable', '입력 내용을 전달할 수 없습니다. 잠시 후 다시 시도해 주세요.');
    }
    var bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (byte) {
      return byte.toString(16).padStart(2, '0');
    }).join('');
  }

  function start(input) {
    input = input === undefined ? {} : input;
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw fail('finder_entry_invalid', '입력 내용을 확인해 주세요.');
    }
    var entry = {
      version: 1,
      entryId: nextId(),
      timestamp: Date.now(),
      text: input.text === undefined ? '' : input.text,
      // This is a local presentation ID, never a sales product_code.
      productId: input.productId === undefined ? null : input.productId,
      source: input.source
    };
    if (hasOwn.call(input, 'purpose')) entry.purpose = input.purpose;
    if (!validEntry(entry, entry.timestamp)) {
      throw fail('finder_entry_invalid', '입력 내용이 올바르지 않거나 너무 깁니다. 내용을 확인해 주세요.');
    }
    var target = typeof P.href === 'function' ? P.href('pc-finder') : null;
    if (target !== 'pc-finder.html') {
      throw fail('finder_entry_route_unavailable', 'PC 추천 화면을 열 수 없습니다. 잠시 후 다시 시도해 주세요.');
    }
    var serialized = JSON.stringify(entry);
    if (serialized.length > MAX_STORED) {
      throw fail('finder_entry_invalid', '입력 내용이 너무 깁니다. 내용을 확인해 주세요.');
    }
    try {
      var storage = window.sessionStorage;
      storage.setItem(KEY, serialized);
      if (storage.getItem(KEY) !== serialized) throw new Error('Storage verification failed');
    } catch (error) {
      throw fail('finder_entry_storage_unavailable', '입력 내용을 전달할 수 없어 이동하지 않았습니다. 현재 입력을 유지해 주세요.');
    }
    window.location.href = target;
    return entry;
  }

  function consume() {
    try {
      var storage = window.sessionStorage;
      var raw = storage.getItem(KEY);
      if (raw === null) return null;
      var entry = null;
      if (typeof raw === 'string' && raw.length <= MAX_STORED) {
        try {
          var parsed = JSON.parse(raw);
          if (validEntry(parsed, Date.now())) entry = parsed;
        } catch (error) { /* Invalid entries are discarded below. */ }
      }
      // Delete before returning, including invalid/expired entries. No other key is touched.
      storage.removeItem(KEY);
      if (storage.getItem(KEY) !== null) return null;
      return entry;
    } catch (error) {
      // A value that cannot be removed must not be delivered and replayed later.
      return null;
    }
  }

  P.finderEntry = { start: start, consume: consume };
}());
