const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const scenario = process.argv[2];
const source = fs.readFileSync(process.argv[3], 'utf8');
const formula = '=ZELERDATA_SKU("local")';
const properties = new Map();
const writes = [];
let reads = 0;
let releases = 0;
let now = 0;
let failure = false;
let change = false;
let busy = false;
let missingLock = false;

function sheet(id, values) {
  return {
    id, values,
    getSheetId: () => id,
    getLastRow: () => values.length,
    getLastColumn: () => Math.max(0, ...values.map(row => row.length)),
    getDataRange: () => ({ getFormulas: () => values.map(row => [...row]) }),
    getRange(row, column, height = 1, width = 1) {
      assert.equal(height, 1);
      assert.ok(width <= 50, 'discovery reads must be bounded');
      const cell = {
        getFormulas() {
          reads += width;
          return [Array.from({ length: width }, (_, offset) =>
            values[row - 1][column - 1 + offset] || '')];
        },
        getFormula() {
          if (change) {
            values[row - 1][column - 1] = '=SUM(1,2)';
            change = false;
          }
          if (scenario === 'deadline') now += 10000;
          return values[row - 1][column - 1] || '';
        },
        setFormula(value) {
          if (failure) throw new Error('write refused');
          assert.equal(value, values[row - 1][column - 1], 'never replace changed text');
          assert.match(value, /^=ZELERDATA_[A-Z0-9_]+\(/i);
          writes.push([id, row, column, value]);
          values[row - 1][column - 1] = value;
        },
      };
      return cell;
    },
  };
}

let sheets = [sheet(1, [[formula]])];
const spreadsheet = {
  getSheets: () => sheets,
  toast: message => assert.ok(!message.includes('formulas refreshed')),
};
const context = {
  SpreadsheetApp: { getActive: () => spreadsheet, getActiveSheet: () => sheets[0] },
  PropertiesService: {
    getDocumentProperties: () => ({
      getProperty: key => properties.get(key) || null,
      setProperty: (key, value) => {
        if (scenario === 'property-failure') throw new Error('property write refused');
        properties.set(key, value);
      },
      deleteProperty: key => properties.delete(key),
    }),
  },
  LockService: {
    getDocumentLock: () => missingLock ? null : ({
      tryLock: timeout => { assert.ok(timeout <= 1000); return !busy; },
      releaseLock: () => { releases++; },
    }),
  },
  Date: { now: () => now },
};
vm.createContext(context);
vm.runInContext(source, context);
const run = () => context.refreshZelerDataResults();

if (scenario === 'tabs') {
  sheets = [sheet(1, [Array(25).fill(formula)]), sheet(2, [[formula, '=SUM(1,2)', 'text']])];
  const first = run();
  assert.equal(first.refreshed, 20);
  assert.equal(first.pending, true);
  assert.equal(first.recalculationVerified, false);
  assert.equal(properties.size, 1);
  sheets.reverse();
  const second = run();
  assert.equal(second.refreshed, 6);
  assert.equal(second.pending, false);
  assert.equal(writes.length, 26);
  assert.equal(new Set(writes.map(write => write.slice(0, 3).join(':'))).size, 26);
  assert.equal(properties.size, 0);
  assert.equal(releases, 2);
} else if (scenario === 'scan') {
  sheets = [sheet(1, [Array(2000).fill(''), [formula]])];
  const first = run();
  assert.equal(first.scanned, 2000);
  assert.equal(reads, 2000);
  assert.equal(first.pending, true);
  assert.equal(first.refreshed, 0);
  const second = run();
  assert.equal(second.refreshed, 1);
} else if (scenario === 'changed') {
  change = true;
  const result = run();
  assert.equal(result.skippedChanged, 1);
  assert.equal(writes.length, 0);
  assert.equal(sheets[0].values[0][0], '=SUM(1,2)');
} else if (scenario === 'busy' || scenario === 'no-document') {
  busy = scenario === 'busy';
  missingLock = scenario === 'no-document';
  const result = run();
  assert.equal(result.pending, true);
  assert.equal(result.status, 'busy');
  assert.equal(reads, 0);
  assert.equal(writes.length, 0);
  assert.equal(properties.size, 0);
  assert.equal(releases, 0);
} else if (scenario === 'failure') {
  failure = true;
  const failed = run();
  assert.equal(failed.status, 'failed');
  assert.equal(failed.pending, true);
  assert.equal(failed.refreshed, 0);
  assert.equal(releases, 1);
  failure = false;
  assert.equal(run().refreshed, 1);
} else if (scenario === 'deadline') {
  sheets = [sheet(1, [Array(30).fill(formula)])];
  const result = run();
  assert.ok(result.refreshed <= 2);
  assert.equal(result.pending, true);
} else if (scenario === 'removed-tab') {
  sheets = [sheet(1, [Array(25).fill(formula)]), sheet(2, [[formula]])];
  run();
  sheets.shift();
  const result = run();
  assert.equal(result.refreshed, 1);
  assert.equal(result.pending, false);
} else if (scenario === 'empty') {
  sheets = [sheet(1, [])];
  assert.equal(run().pending, false);
  assert.equal(reads, 0);
} else if (scenario === 'property-failure') {
  sheets = [sheet(1, [Array(25).fill(formula)])];
  assert.throws(run, /property write refused/);
  assert.equal(releases, 1);
} else if (scenario === 'corrupt-cursor') {
  properties.set('zelerdata.manualRefresh.v1', '{invalid');
  assert.equal(run().refreshed, 1);
  assert.equal(properties.size, 0);
} else {
  throw new Error('unknown scenario');
}
console.log(JSON.stringify({ scenario, passed: true, writes: writes.length, releases }));
