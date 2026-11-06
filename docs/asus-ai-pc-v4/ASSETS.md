# ASUS 기획전 자산 목록

2026-11-05 · PC2 Claude. 재생성: `build_assets.py`. 전부 `mockups/mvp4/assets/images/asus/`에 있다.

## 원본

| 원본 | 제작 | SHA256 |
|---|---|---|
| v5 gt502-black-cutout.png (1254x1254 RGBA) | PC1 내장 image_gen | 1E4751EDB978744B142F4E94C707233D7C63720DDF9C83F3826B2B3351AE428C |
| v5 gt502-desktop-hero.png (2172x724) | PC1 내장 image_gen | BA527A3AB78A4A2CD4F7F690DCF6A928CC031032D56242C1CDF9FC9FB18887FB |
| v5 gt502-mobile-hero.png (1122x1402) | PC1 내장 image_gen | 35E386B350B310C0911CA7CFBDA3D39FBC61A052F053CEE0BDBFC8FD8E08EA23 |
| v3 pc/01-banner.png | PC1 AI 생성 시안 | BF30694C44C584EE519023CBF9E8D9A8EE95B11190A761E1DAB9F4229083C42D |
| v3 pc/03-business.png | PC1 AI 생성 시안 | 16A9F169AD96800CFBCFA10913AF9F14D833AF642D22EF58E2D68336B71390F5 |
| v3 pc/04-video.png | PC1 AI 생성 시안 | CC0FE380E4E5B25B1C9D8FE97BDEB3039A6EFCDA355E49683AA7D47193D0CC6F |
| v3 mobile/04-video.png | PC1 AI 생성 시안 | 393FC7844E67919F8742216D455E9A4C497225574C518A1CB59EADDB027EB558 |
| v3 mobile/05-local-ai.png | PC1 AI 생성 시안 | 02D5DE9BA5453C8D1B3D795E1A34E50C70DCD1E959530C093A04BDFA4F7EA898 |

공식 GT502 사진(`reference-ASUS-GT502-black-official.png`)은 PC1이 생성 시 외형 참고로만 썼고, 이 저장소의 화면 소재에 넣지 않았다.

## 화면 소재

| 파일 | 원본 | 제작 | 재가공 | 쓰는 곳 | SHA256 |
|---|---|---|---|---|---|
| bg-arcs.webp | v5 gt502-desktop-hero.png | PC1 내장 image_gen 생성 | 제품이 없는 왼쪽 x=0~1340만 자름, WebP 변환 | 상세 상단·하단 문의 띠 배경 | C0D59F172BDA727AF3D10AC2D33F936158AA26A28995CD84BC5B8E48859EE1DE |
| gt502-black-cutout.webp | v5 gt502-black-cutout.png | PC1 내장 image_gen 생성 | 1254→800px 축소, WebP 변환. 비율 유지 | 상품 카드, 상세 상단, 다른 구성 보기, 문의 안내 | 5C3C8C44F4E5BE09B5188E48CC9ED15F5EEDA63583840EE6C89BA429519AC3D0 |
| hero-desktop.webp | v5 gt502-desktop-hero.png | PC1 내장 image_gen 생성 | WebP 변환만(2172x724) | 홈 배너(PC·모바일 하단), 서브메인 PC 상단 | 8AB04BBF9C31952EBA6149875D4268AB735A904B9E6F5383F1B3B78EB86CDAA3 |
| hero-mobile.webp | v5 gt502-mobile-hero.png | PC1 내장 image_gen 생성 | WebP 변환만(1122x1402) | 서브메인 모바일 상단 | 6F58FA08DB5F3A55565AA212B4C9E226745DC44508376E2D133E603C38E03991 |
| logo-asus-white.png | v3 pc/01-banner.png | PC1 AI 생성 시안 | 로고 영역만 추출, 흰색 단색화 | 기획전 상단 띠 | F1BDF6FBFC7FEFF711E91E273ACDF247243B2059A0DA5BB784DC76CE7EA84ADF |
| use-ai-1.webp | v3 mobile/05-local-ai.png | PC1 AI 생성 시안 | GT302 오른쪽 모니터만 자름, 2배 확대 | 로컬 AI 활용 01 | A7D5B8D0E1DEC3CC6F3B54D1757C1A2EE62C8C9882A8883FC77585BFA14B85EA |
| use-ai-2.webp | v3 mobile/05-local-ai.png | PC1 AI 생성 시안 | GT302 오른쪽 모니터만 자름, 2배 확대 | 로컬 AI 활용 02 | F6D5B6BFC3DD9819DE6980D8510338F792816CBFC3BE8815ADD17C78ABC9294B |
| use-ai-3.webp | v3 mobile/05-local-ai.png | PC1 AI 생성 시안 | GT302 오른쪽 모니터만 자름, 2배 확대 | 로컬 AI 활용 03 | 46DEB0381F2F0A59FA94D1ECA20AFFF1769588FB32CD74A46B46691243F7AE68 |
| use-business-1.webp | v3 pc/03-business.png | PC1 AI 생성 시안 | 모니터 영역 자름, 사용 예시 배지 제거, 2배 확대 | 문서·업무 활용 01 | 69F7C9D84A15C8493323EAD794269F854635650BB7B4334607FB503742680F46 |
| use-business-2.webp | v3 pc/03-business.png | PC1 AI 생성 시안 | 모니터 영역 자름, 사용 예시 배지 제거, 2배 확대 | 문서·업무 활용 02 | C0AEC29E7006A8E1A9407D2077F522E8039A31D932030812613B9E74A34C878F |
| use-business-3.webp | v3 pc/03-business.png | PC1 AI 생성 시안 | 모니터 영역 자름, 사용 예시 배지 제거, 2배 확대 | 문서·업무 활용 03 | 31AA8385B1C0466A944B58D45D59EA2E2200CC24AB892325B290A20A99BABFB8 |
| use-video-1.webp | v3 mobile/04-video.png | PC1 AI 생성 시안 | GT302 왼쪽만 자름, 배지 제거, 2배 확대 | 영상·디자인 활용 01 | 4B62B84175057E0E40AFEE28B1B5983A78C9488A6A7CD50660240AF610FD69D3 |
| use-video-2.webp | v3 mobile/04-video.png | PC1 AI 생성 시안 | GT302 왼쪽만 자름, 배지 제거, 2배 확대 | 영상·디자인 활용 02 | 575B1D7849CA9275BDAADB2BA901BCE5825775E02912A759E033EC4727AD14F5 |
| use-video-3.webp | v3 pc/04-video.png | PC1 AI 생성 시안 | GT302 왼쪽만 자름, 배지 제거, 2배 확대 | 영상·디자인 활용 03 | 5BA758B3ECB28035070975657CF5C533FB2B0322DECA66C13DCF47F6FA5FE00A |

## 사용 조건

- GT502 소재는 내부가 빈 케이스 연출이다. 완제 조립 사진이나 호환성 증거가 아니다. 화면에 「제품 이미지는 연출이며 실제 구성과 다를 수 있습니다.」를 실제 글자로 표시한다.
- 푸른 빛은 외부 조명 연출이며 RGB 부품 포함을 뜻하지 않는다. 작은 각인은 실제 제품과 다를 수 있어 확대 소개하지 않는다.
- 공식 사진과 ASUS 상표의 외부 사용 승인은 완료되지 않았다. ASUS 로고는 v3 AI 시안에서 추출한 것이라 공식 로고 파일로 교체를 검토해야 한다. 외부 공개 전 ASUS 확인이 필요하다.
- 사용 예시는 실측 화면이 아니라 AI 생성 예시다. GT302가 보이는 영역은 잘라내고 썼고, 인물 사진은 GT302·잘못된 배지가 섞여 쓰지 않았다.
- 그래픽카드·쿨러 소재를 새로 만들지 않는다. 상세 구성 표의 부품 사진은 몰 상품번호가 같은 기존 사진을 쓰고, 그 사진이 없거나 모델을 확인할 수 없는 7종은 제조사 공식 페이지 사진을 저장소에 둔다(`api/asus_campaign.part_thumbnail`, 출처 `assets/images/parts/ASUS-OFFICIAL-SOURCES.json`, 2026-11-06 사용자 지시). 공식 사진의 외부 사용 승인 여부는 위 항목과 같이 확인되지 않았다.
- 초기 자체 합성 소재(gt502-build-*, gpu-render, banner-home, bg-hero)는 v5 수령 후 삭제했고 커밋하지 않았다.
