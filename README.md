# 팝콘PC AI (popcorn-ai)

내부자 전용 개발 프로젝트. **현재 단계: 모델링(클릭 가능한 UI 목업 확정).**

## 구조
- `docs/`          기획·프롬프트·디자인·결정 로그
- `design-system/` Vibrant Horizon 토큰, 폰트, 아이콘
- `assets/`        더미 이미지
- `mockups/`       ★ 이 단계의 유일한 산출물 (게이트웨이 + MVP1 S0~S4)

## 원칙
UI(목업)가 확정되기 전에는 백엔드/DB/서버/AI 연동을 만들지 않는다.
자세한 지침은 `CLAUDE.md` 참조.

## 완성 PC 대표 이미지·발행 일괄 처리 순서

아래 순서로 실행한다. 실제 적용(`--apply`)은 owner 승인 문장이 나온 뒤 서버 회귀·배포 점검 담당이 PC 작업창에서 한다. 각 도구는 기본이 조회(dry-run)다.

1. **#31 대표 이미지 등록** `tools/import_pc_media_archive.py`. 기존 원본(`originals/P{코드}.png`)을 재생성 없이 저장소에 올리고 등록·대표 선택까지 한 번에 한다. 먼저 `--archive <폴더> --operator-id <owner> --force-select --report dry.json` 으로 「업로드 예정 / 이미 있음 / 대표 선택 예정 / 등록만 / 보고만」 요약을 확인하고, 이어서 `POPCORN_EXISTING_MEDIA_IMPORT_APPLY=1` 과 `--apply` 를 붙여 같은 명령을 실행한다.
2. **부품 사진 권리 참조값** 서버 env 에 `POPCORN_PART_PHOTO_RIGHTS_REFERENCE=workroom:기록/팝콘AI/결정/popcorn-business-product-photo-use-attestation-20261006.md@v1:8851f92e8e98f041f948cfcda04bfdf4d51949b14fbc4395ba69ada0c88ea6a2` 를 둔다(2026-10-06 사업자 확인서, PC 작업실 원본과 sha256 일치 확인).
3. **일괄 승인** `tools/approve_pc_publication_bulk.py`. 부품 설명 → 부품 사진 → 추천 검토 → 발행 순서로 기존 승인 모듈을 부른다. 먼저 `--operator-id <owner> --report dry.json`, 이어서 `POPCORN_PUBLICATION_BULK_APPROVE_APPLY=1 ... --apply --approval-note "<owner 승인 문장>"`. 대상은 대표 이미지가 선택된 구성이고, `--all` 은 판매중 구성 전체다. 추천 검토 보류 구성·설명 없는 부품은 건드리지 않고 보고만 한다.

세 단계가 끝난 뒤 고객 추천 결과에서 대표 사진이 보이는지 확인한다.
