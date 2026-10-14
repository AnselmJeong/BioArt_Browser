# 과학 제작 3단계 검증 — 2026-10-14

## 납품 상태

`/Applications/BioArt Browser.app`과 `dist/BioArt Browser.app`에 적용했다. 두 앱은 ad-hoc 서명 후 `codesign --verify --deep --strict`를 통과했다. 이전 설치본은 `dist/BioArt Browser.pre-phase3.app`에 보관했다. 문서와 출처 원본은 기존 작업 폴더를 계속 사용한다.

## 실제 앱의 저장 → 완전 종료 → 재실행 → 재열기 → 내보내기

macOS 설치 앱의 UI에서 아래 다섯 템플릿을 새 문서로 만들었다. 제목·세포막 두께·표 셀을 UI에서 수정했고, 각 문서의 저장 완료와 내보내기 완료 화면을 확인했다. Cmd-Q로 종료한 뒤 앱 프로세스가 없는 것을 확인하고 다시 실행했다. 저장한 도해 선택기로 다섯 문서를 각각 다시 열어 내보냈다.

| 실제 앱 문서 | ID | revision | 재시작 후 결과 |
| --- | --- | --- | --- |
| 검증 3 · 세포 신호전달 | doc-31cce85e8efc | 4 | 설정·geometry 동일, SVG/PNG 동일, ZIP 정상 |
| 검증 3 · DNA와 전사 | doc-38699dc9fa6a | 3 | 설정·geometry 동일, SVG/PNG 동일, ZIP 정상 |
| 검증 3 · 약물 전달 | doc-b04ba1cb5c8a | 3 | 설정·geometry 동일, SVG/PNG 동일, ZIP 정상 |
| 검증 3 · 실험과 결과 | doc-d79ccf768079 | 4 | 설정·geometry 동일, SVG/PNG 동일, ZIP 정상 |
| 검증 3 · 막 · 분자 브러시 | doc-7dd8f00c9908 | 3 | 설정·geometry 동일, SVG/PNG 동일, ZIP 정상 |

동일성은 화면 문구가 아니라 저장 JSON의 전체 값 비교, SVG/PNG의 SHA-256, ZIP CRC 및 내부 document.json으로 확인했다. 결과와 실제 출력 경로는 `state/phase3-validation/native-restart-results.json`, 이전 값은 같은 디렉터리의 `native-before.json`과 `doc-*-before.json`에 남겼다.

추가 UI 검증:

- 세포막 두께 36 → 52 변경, 연결된 확대 삽화 geometry 갱신 및 저장 확인.
- 표의 머리글을 `결과`, 처리군 농도를 `20`, 결과를 `미측정`으로 변경하고 실제 PNG에서 확인.
- 별도 문서 `doc-a3efdc80e2ca`에서 캔버스 드래그로 막 브러시를 직접 그렸다. 생성 설정과 기준 경로가 저장되었다.
- LaTeX `\frac{a}`는 오류 메시지를 표시하고 추가하지 않았다. 올바른 `J=-D\frac{\partial C}{\partial x}`는 벡터 수식으로 추가·저장·출력했다.
- 표 글자와 확대 삽화가 SVG/PNG에서 사라지는 clipPath 문제를 수정했다. 클리핑 도형을 `<g>` 대신 직접 넣어 resvg에서도 보존한다. 출력 픽셀 회귀 검사를 추가했다.

## 자동 검증

- Python 전체: **81 passed**. 저장·revision·복구·내보내기 기존 회귀 검사와 생성기 버전/범위, 표 검증, 확대 삽화 참조/순환, 클리핑 픽셀 검사 포함.
- Bun 편집기/데스크톱: **15 passed, 57 assertions**. 결정적 seed, 곡선 브러시, 확대 갱신·삭제·복제 참조, 잘못된 LaTeX 거부, 작은 소포/패널 라벨 경계 검사 포함.
- 브라우저 엔진: **51 passed, 0 failed**. 기존 36개(실제 SVG 32개 포함)에 생성기 10종과 과학 도해 5종의 저장·재열기·SVG decode·PNG/ZIP export를 추가했다.
- TypeScript 프로젝트 진단: **0**. 기존 Electrobun SDK 진단 15개는 기존 typecheck 정책에 따라 제외.

브라우저 검사는 개발 서버, 실제 납품 경로 검사는 설치된 macOS 앱에서 별도로 진행했다. 검증 페이지는 패키지에 포함하지 않았다. 최종 JS와 설치된 JS의 SHA-256은 `ca8647ed084faadf5fe8f3475729741f4b6da0d5a3bf80cc0ad878f62628c44a`이다.

## 범위와 제한

10종 생성기와 5종 브러시는 개념 도식이다. 자동 물리 축척이나 실제 분자 구조를 주장하지 않는다. 자기 교차 브러시의 모든 겹침을 해결하지는 않는다. 확대 영역은 수치 좌표로 조정한다. 표는 셀 편집창을 사용하며 셀보다 긴 내용은 클리핑된다. 패널은 내용과 독립된 프레임이다. 현재 검증한 출력은 SVG·PNG·document.json·출처/manifest ZIP이다. PDF/TIFF, 출판용 폰트·DPI·프리플라이트는 다음 출력 단계의 범위다.
