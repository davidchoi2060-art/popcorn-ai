// mvp4_part_images.mjs 결과(JSON)를 표로 줄인다. 표본이 여럿이면 중앙값이고, 표본 수를 함께 적는다.
//   node tools/perf/mvp4_part_images_report.mjs result.json > report.md
import fs from 'node:fs';

const d = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const med = (xs) => { const a = xs.filter((x) => x !== null && x !== undefined).sort((x, y) => x - y); return a.length ? a[Math.floor((a.length - 1) / 2)] : null; };
const kb = (b) => (b === null ? '-' : (b / 1024).toFixed(0) + 'KB');
const k = (s, kind, f) => (s.byKind[kind] ? s.byKind[kind][f] : 0);
const out = [];
out.push(`# /mvp4 부품 사진 측정 — ${d.base}`, '', `측정 ${d.startedAt} ~ ${d.finishedAt} · 비교 ${d.variants.join(' / ')} · 표본(보통 망) ${d.samples}, 느린 망·실패 주입 1`, '');
out.push('열: 구성 GET(offer+registered) · 부품 사진 요청 = 네트워크 200 / 304 / 캐시(memory·disk) · 고유 주소 · 같은 주소를 네트워크로 두 번 이상 받은 수 · 부품 사진 전송 bytes · 카드 첫 부품 사진 표시(중앙값, 단계 시작 기준 ms) · 아이콘 대체 수', '');
const profiles = Object.keys(d.runs[d.variants[0]]);
for (const profile of profiles) {
  out.push(`## ${profile}`, '', '| 단계 | 비교 | n | 구성 GET | 사진 200 | 304 | 캐시 | 고유 | 중복 재전송 | 사진 bytes | 첫 사진 ms | 아이콘 |', '|---|---|---|---|---|---|---|---|---|---|---|---|');
  const steps = Object.keys(d.runs[d.variants[0]][profile][0]);
  for (const step of steps) for (const v of d.variants) {
    const runs = (d.runs[v][profile] || []).map((r) => r[step]).filter(Boolean);
    if (!runs.length) continue;
    const col = (fn) => med(runs.map(fn));
    out.push(`| ${step} | ${v} | ${runs.length} | ${col((s) => k(s, 'offer', 'requests') + k(s, 'registered', 'requests'))} | ${col((s) => k(s, 'part-image', 's200'))} | ${col((s) => k(s, 'part-image', 's304'))} | ${col((s) => k(s, 'part-image', 'cache'))} | ${col((s) => k(s, 'part-image', 'unique'))} | ${col((s) => k(s, 'part-image', 'netDuplicateUrls'))} | ${kb(col((s) => k(s, 'part-image', 'bytes')))} | ${col((s) => s.firstPartPhotoMs.median) ?? '-'} | ${col((s) => (s.dom ? s.dom.partIconsInDom : null)) ?? '-'} |${runs.some((s) => s.error) ? ' 오류 ' + runs.filter((s) => s.error).length + '건: ' + runs.find((s) => s.error).error.replace(/[|\n]/g, ' ').slice(0, 120) : ''}`);
  }
  out.push('');
}
if (d.variantSizes && d.variantSizes.length) {
  const sum = (v) => d.variantSizes.reduce((a, r) => a + (r[v] && r[v].status === 200 ? r[v].bytes : 0), 0);
  const ok = (v) => d.variantSizes.filter((r) => r[v] && r[v].status === 200).length;
  out.push('## 같은 부품 사진의 크기 (detail 원본 vs thumbnail)', '', `부품 ${d.variantSizes.length}종: detail 200 ${ok('detail')}종 합 ${kb(sum('detail'))} · thumbnail 200 ${ok('thumbnail')}종 합 ${kb(sum('thumbnail'))}`, '');
  out.push('| 부품 코드 | detail | ms | 304 재검증 ms | thumbnail | ms | 304 재검증 ms |', '|---|---|---|---|---|---|---|');
  for (const r of d.variantSizes) out.push(`| ${r.code} | ${r.detail.status} ${kb(r.detail.bytes)} | ${r.detail.ms} | ${r.detail.revalidate ? r.detail.revalidate.status + ' ' + r.detail.revalidate.ms : '-'} | ${r.thumbnail.status} ${kb(r.thumbnail.bytes)} | ${r.thumbnail.ms} | ${r.thumbnail.revalidate ? r.thumbnail.revalidate.status + ' ' + r.thumbnail.revalidate.ms : '-'} |`);
}
process.stdout.write(out.join('\n') + '\n');
