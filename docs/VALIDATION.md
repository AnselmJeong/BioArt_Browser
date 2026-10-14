# 구현 및 검증 · 2026-09-24

## 실제 데이터

- 작품 933개, manifest 파일 9,525개를 모두 대조.
- 유효 9,524개: SHA-256 재계산·로그 비교, PNG 전체 디코딩, SVG 파싱·안전한 파생본 렌더링 성공.
- MRI SVG `782376`: `.part` 유지, 서버 재요청도 HTTP 성공/0바이트. 사용 불가로 제외.
- 원본 페이지 933개 수집: ID·제목 일치 931개, 충돌 2개 (`202`, `690` → 응답 `601 / Domestic Cat`). 원문 해시·HTML 보존, 충돌 메타데이터는 검색 내용에 사용하지 않음.
- 계획서의 과거 `567` ID 불일치는 이번 요청에서 재현되지 않음. 현재 응답은 `567 / Pulmonary Alveolus`와 일치.
- 9,524개 provisional representation의 미검토 내용 카드와 검토 대기열. 64개 파일럿 명단·이미지 비교판 준비.

## 자동 검증

`uv run pytest -q`: 52개 테스트 통과. 인벤토리 재실행, 파일 손상 감지, 한영·부분 관계·직접 범위 검색, 필터/페이지, 원본 보존, 경로/심볼릭 링크 이탈 거부, SVG 외부 참조/스크립트 제거, 출처 manifest, 네 구도 렌더링, revision 충돌·잘림, HTTP 토큰/Origin/Host 제한, 세션 저장을 검증. 네 구도 각각 1–8개 자산의 범위·겹침을 검사했고, 복사 중 원본이 바뀌면 내보내기를 게시하지 않는 회귀 검증도 포함.

공식 MCP SDK stdio 클라이언트로 8개 도구 발견 및 검색 → 상세 → 실제 ImageContent → 정확한 SVG 내보내기 → 장면 생성·수정 → SVG/PNG 내보내기를 완주. 로그: `state/mcp-validation.json`. 이 과정은 Codex/Claude에 실제 등록한 제품별 호환성 검사와 구별함.

35개 로컬 질의: 측정 환경·카탈로그 버전·질의별 결과/시간은 `search-evaluation.json`. 준비된 인덱스/메모리 상태에서 p95 약 1.25ms. 콜드 시작과 썸네일 읽기 제외. 사람의 relevance 정답셋이 없으므로 Precision@10·Recall@20 미측정.

## 단계별 상태

| 단계 | 상태 | 남은 작업 |
|---|---|---|
| P0 | 구현·전체 검증 | 외부 서버의 빈 MRI 파일은 해결되지 않음 |
| P1 | 공개 페이지 수집·정체성 검사 구현 | source representation mapping, 격리된 2개 작품 확인 |
| P2 | 64개 파일럿 준비 | 모델 분석, 비용/품질 측정, 사람 검토 |
| P3 | 모든 파일의 명시적인 미해결 상태 등록 | 실제 전체 시각 주석 배치·모델 어댑터·검토 이력 편집 |
| P4 | 제목/원본 키워드/별칭/1단계 폐–폐포 관계 기준선 | embedding, 폭넓은 온톨로지, 수동 정답셋 평가 |
| P5 | 탐색 UI 구현 | 아래 데스크톱/브라우저 검증 상태 참조 |
| P6 | stdio 구현·SDK 클라이언트 전달 검증 | 사용자 제품별 등록·이미지 전달 검사 |
| P7 | 제한된 도해 제작 초기 기능 | 자유 배치 UX, 개별 연결선/그룹 편집, 목표 SVG 편집기 검증 |

구현 계획의 모든 연구·주석 완료 조건을 달성했다고 주장하지 않습니다. 사용 가능한 브라우저 앱과 데이터 기반을 제공하며 미완료 데이터는 UI에 표시합니다.

## 원본·출력·보안

- 원본 폴더 변경 없음. DB/캐시/주석/프로젝트/내보내기는 별도 경로.
- UI 서버는 127.0.0.1의 포트만 사용. 외부 페이지의 변경 요청을 토큰/Origin 검사로 거부. Host 검증. 임의 파일 읽기/임의 출력 위치 API 없음.
- SVG 미리보기는 스크립트·외부 링크 제거 후 PNG로 렌더링. SVG export 장면은 자산별 격리된 data 이미지로 ID/CSS/gradient 충돌 방지. clipart 내부 편집을 제공한다는 의미는 아님.
- 장면 수정은 revision 검사. 현재 엔진은 회전·반전을 허용하지 않음. 자산 비율 유지. 포함된 PNG는 manifest에 raster로 명시.
- 패키지는 로컬 ad-hoc 서명, Developer ID 및 공증 미실시.

## UI 검증 기록

브라우저: 실제 화면에서 `폐` 검색, 직접/관련 결과의 구분, source 정보, PNG/SVG 변형 선택, 트레이 추가와 저장 확인. 비교판 표시 중 blob 이미지 CSP 누락을 발견해 수정한 뒤 실제 800×220 이미지 로딩을 확인. 트레이는 새로고침 후 복원되었고, 전체/확대 장면의 객체 크기·좌표 변경 → revision 갱신 → SVG·PNG·출처 내보내기를 UI에서 완주. 결과 예: `exports/scene-a7c52c665509-r3-4ae5af/`.

macOS 앱: 번들 빌드 완료. 첫 실행에서 OS의 외장 볼륨 접근 허용이 필요함. 실제 창과 권한 대기 안내 화면 확인. macOS TCC의 `SystemPolicyRemovableVolumes` 허용 대기 때문에 현재 네이티브 창에서 카탈로그가 로딩되는 단계는 아직 검증하지 못함. 권한은 우회하지 않았으며 사용자에게 시스템 요청 허용을 안내함. 앱 서명 무결성은 `codesign --verify --deep --strict` 통과.

## Electrobun 전환 검증

후속 요청으로 Swift 셸을 Electrobun 2.0.1/Bun으로 변경했다. Python 52개 + Bun 4개 테스트, 내장 런타임의 제한된 PATH 실행·카탈로그 검색·정상 종료·부모 소실 복구, 서명 무결성을 검증했다. Finder 실행의 외장 볼륨 접근 권한 대기는 남아 있다. 정확한 명령과 검증 구분은 [DESKTOP.md](DESKTOP.md)에 기록한다.

## 대화형 제작실 · 0.3.0 · 2026-09-24

- Python 테스트 **64 passed**. 기존 카탈로그/장면/서버 회귀와 신규 Codex 프로토콜, 제한된 자산 선택, 유효 좌표, 텍스트 이스케이프, 출처 내보내기, 실제 이미지 바이트 수신, 이전 수동 편집 전달, 취소/즉시 취소, 실패 시 이전 결과 보존, 재시작 복구, 프로세스 간 작업 잠금과 프로젝트별 버전 경계를 검사했다.
- Bun 데스크톱 테스트 **4 passed**. 프로젝트 TypeScript 진단 **0**; 기존 Electrobun SDK 내부 진단 15개는 기존 typecheck 스크립트의 제외 범위다.
- Codex CLI 0.154.0 + ChatGPT 구독으로 원본 조합과 ImageGen을 실제 실행했다. 원본 조합/AI 생성 모두 `completed` 결과와 저장 파일을 확인했다. 별도 OpenAI 이미지 API 키는 사용하지 않았다.
- 실제 UI: 폐·폐포 선택 → 원본 조합 → 현재 도해를 참고한 AI 재생성 → 한글 라벨 추가 → 끌어 이동/좌표 저장 → 내보내기 완료 → 이전 버전 선택 → 서버/화면 재시작 후 프로젝트 복원을 확인했다.
- 내보낸 ZIP을 재열어 project.json, scene.json, figure.svg, figure.png, generated.png, manifest.json, SOURCES.md를 확인했다. PNG는 1400×850이고 시각적으로 검토했다. 원본 해상도 생성 PNG도 보존된다. 기록: `state/studio-validation.json`.
- 아이콘은 Healthy neuron (BIOART-000197, Public Domain 표기)을 참고한 ImageGen 결과다. RGBA 원본과 16–1024px macOS iconset, ICNS를 생성했다. 앱의 CFBundleIconFile과 번들 ICNS 체크섬이 소스 ICNS와 일치한다.
- `dist/BioArt Browser.app`을 실제 실행해 제작실, 저장한 결과, ChatGPT 구독 연결 상태를 확인했다. 기존 문서의 0.2.0 TCC 대기 상태와 구별되는 이번 실행 결과다.
- 앱 번들은 ad-hoc 서명 검증을 통과했다. Developer ID 서명/공증은 수행하지 않았다.

과학적 내용의 정확성, 생성 시 원본 형태 보존, 모든 Codex 버전/계정, 타사 SVG 편집기의 호환성을 보장하는 검증은 아니다. 생성 테스트는 기능 경로 검증이다.

최종 패키징 앱에서 추가로 “제목만 변경하고 나머지를 유지”하는 Codex 후속 요청을 실행해 완료를 확인했다. 결과 JSON을 이전 버전과 비교해 objects/arrows/texts가 모두 동일하고 제목만 `폐와 폐포`로 바뀌었음을 확인했다. 패키징된 백엔드는 `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, `cwd=/`에서도 Codex 구독 연결·검색·프로젝트 목록·정상 종료·부모 종료 후 정리를 통과했다 (`build/desktop-runtime-verification.json`).
