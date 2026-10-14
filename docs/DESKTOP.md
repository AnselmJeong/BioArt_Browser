# Electrobun desktop · 0.2.0

## 실행과 빌드

`dist/BioArt Browser.app`을 Finder에서 실행한다. macOS 14+, Apple Silicon용이며 Python·Bun을 포함한다. 원본 1.3GB 라이브러리와 카탈로그는 기존 작업 폴더에 있다. 앱만 복사해도 자료가 함께 이동하는 구성은 아니다.

```sh
bun run build                         # 전체 앱 빌드; uv + Bun 필요
bun run build:dmg                     # 전체 앱 빌드 후 DMG 생성·검증
./script/build_and_run.sh              # 빌드 후 Finder 방식으로 실행
bun run dev                           # 최초 빌드 후 개발 실행
```

앱은 127.0.0.1의 임의 포트에서 내장 Python 서버를 실행한다. `BIOART_WORKSPACE` → 개발 `BIOART_PROJECT_ROOT` → 저장된 선택 → 번들에 기록된 기본 작업 폴더 순서로 찾는다. 폴더에 `data/catalog/catalog.sqlite`가 있어야 하며, 이동 후 `파일 → 작업 폴더 선택…`에서 재연결할 수 있다. 새 빈 카탈로그를 조용히 만들거나 원본을 옮기지 않는다.

- `src/bun/index.ts`: 창, 메뉴, 작업 폴더 선택, 좁은 네이티브 이벤트 처리, 종료
- `src/bun/backend.ts`: 내장 실행 파일 감독, 준비 신호와 health check, 경로 검증
- `web/desktop.js`: Electrobun에서만 Finder/외부 링크 연결; 일반 브라우저 호환
- `src/bioart/__main__.py`: stdout 준비 신호, 부모 프로세스 소실 감시
- `electrobun.config.ts`: Bun main process, 리소스 복사, macOS native renderer
- `native/BioArtBrowser.swift`: 이전 셸의 보존본. 현재 빌드에는 포함하지 않음

## 실행과 보안 경계

UI는 sandbox 모드이며 일반 RPC·임의 명령 실행을 노출하지 않는다. 자료 통신은 기존 HTTP API를 쓴다. Native event는 알려진 action만 파싱하고, Finder 요청은 존재하는 exports 하위 파일로 제한하며 심볼릭 링크 이탈도 거부한다. 외부 HTTP(S) 링크는 기본 브라우저로 연다. Webview의 탐색 허용 목록은 실제 로컬 서버 origin 하나다.

앱 종료는 서버 종료를 기다린다. 3초 후에도 서버가 남으면 강제 종료한다. 앱 프로세스가 강제 종료되면 Python watchdog이 부모 소실을 감지해 종료한다. 웹/MCP 단독 실행에는 부모 감시가 적용되지 않는다.

작업 선택 설정: `~/Library/Application Support/local.bioart.browser/stable/workspace.json`

로그: `~/Library/Logs/local.bioart.browser/stable/desktop.log` (`보기 → 실행 로그 보기`)

안정 버전 빌드의 기본 산출물은 자동 압축 해제 설치기다. 외장 볼륨에서 해당 설치기의 설치 단계가 실패하여, 배포 스크립트가 빌드 중 payload를 풀고 실제 앱 번들에 ad-hoc 서명한다. 이전 앱은 `dist/BioArt Browser.previous.<시각>.app`으로 남는다. 로컬 무결성 서명이며 Developer ID 서명·Apple 공증은 수행하지 않았다.

`script/build_dmg.sh`는 전체 빌드 결과를 Applications 바로가기와 함께 압축 DMG로 만든다. 이미지 무결성, 읽기 전용 마운트 안의 앱 서명과 바로가기를 검증한 뒤 `dist/BioArt Browser-<버전>-arm64.dmg`에 저장한다. 자료·카탈로그는 DMG에 포함하지 않는다.

## 검증 · 2026-09-24

- Python 52개, Bun 4개 테스트 통과. Bun 검사는 네이티브 입력 검증, 경로 이탈, 서버 준비/종료 및 조기 실패를 포함한다.
- `bun run typecheck`: 프로젝트 진단 0개. Electrobun 2는 SDK 소스를 직접 제공하므로, 엄격한 옵션과 맞지 않는 SDK 내부 진단 15개만 별도 제외한다. 프로젝트 코드와 SDK 호출은 검사한다. 처리 방식은 `script/typecheck.ts`에 명시했다.
- Python `ruff --isolated --select E9,F`, JavaScript 구문 검사 통과.
- 내장 launcher를 `PATH=/usr/bin:/bin:/usr/sbin:/sbin`로 실행: 데스크톱 로그의 DOM ready, 백엔드 health, 933개 작품·9,524개 유효 파일 확인. SIGTERM 종료 시 native 종료 처리와 서버 종료 확인.
- `uv run python script/verify_desktop_runtime.py`: 패키지 실행 파일을 `/`에서 제한된 PATH로 시작해 검색·카탈로그·정상 종료·부모 강제 종료 후 서버 소멸을 확인. 결과는 `build/desktop-runtime-verification.json`.
- `codesign --verify --deep --strict` 통과.
- Finder 실행 경로에서는 macOS TCC의 `SystemPolicyRemovableVolumes` 권한 응답 대기가 확인됨. OS 허용 전 실제 네이티브 창의 클릭·Finder 열기·외부 링크 UI 흐름은 미검증. 앞서 웹 버전에서 검색·트레이·도해·내보내기 흐름은 검증했으나 이를 Electrobun UI 검증으로 간주하지 않는다.

외장 볼륨 권한은 우회하지 않는다. OS 요청에서 사용자가 허용한 뒤 Finder 실행을 다시 확인해야 한다.

## 0.3.0 · 제작실과 아이콘

ChatGPT 구독으로 연결하는 Codex App Server, 대화형 제작실, 원본 조합/AI 생성, 편집 가능한 텍스트·화살표, 프로젝트 버전과 내보내기를 추가했다. Codex CLI는 사용자 설치를 발견해서 실행하며 앱에 포함하지 않는다. API 키 과금으로 자동 전환하지 않는다. 자세한 동작과 제한은 [STUDIO.md](STUDIO.md)를 참고한다.

BioArt Healthy neuron을 참고해 만든 앱 아이콘을 `assets/BioArt.iconset`으로 연결했다. 원본 PNG, ICNS, 출처와 생성 설명을 assets에 보존한다.
