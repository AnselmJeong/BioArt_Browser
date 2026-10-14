# BioArt Browser

NIH BioArt의 로컬 그림을 한국어·영어 개념으로 찾아 비교하고, 정확한 파일과 출처를 내보내는 Electrobun 기반 macOS 앱입니다.

## 실행

빌드된 앱: `dist/BioArt Browser.app`

```sh
./script/build_and_run.sh
```

Codex의 **Run**도 같은 스크립트를 사용합니다. macOS 14 이상, Apple Silicon용입니다. Electrobun 2.0.1, Bun, Python 런타임과 서버가 앱 안에 포함되어, 실행할 때 별도 런타임 설치가 필요하지 않습니다. 원본 1.3GB와 카탈로그는 작업 폴더에 보존하므로, 앱만 다른 컴퓨터로 복사하면 자료가 함께 이동하지 않습니다. 작업 폴더를 이동한 경우 앱이 새 작업 폴더를 선택하도록 안내합니다. 외장 볼륨에 있는 자료를 읽고 결과를 저장하려면 첫 실행에서 macOS의 볼륨 접근 허용이 필요합니다.

앱 또는 DMG만 빌드하려면 (Bun과 uv 필요):

```sh
bun run build       # Python 백엔드를 포함한 전체 앱 빌드
bun run build:dmg   # 전체 앱 빌드 후 DMG 생성·검증
```

결과는 `dist/BioArt Browser.app`과 `dist/BioArt Browser-<버전>-arm64.dmg`에 생성됩니다. DMG에는 앱과 Applications 바로가기가 포함됩니다. 앱은 ad-hoc 서명되며 Developer ID 서명·Apple 공증은 수행하지 않습니다.

데스크톱 개발 모드 (최초 번들 빌드 후):

```sh
bun install --frozen-lockfile
bun run dev
```

`파일 → 작업 폴더 선택…`으로 기존 카탈로그가 있는 폴더 또는 휴대용 프로젝트를 가져올 빈 폴더를 지정하고, `보기 → 실행 로그 보기`로 시작 오류를 확인할 수 있습니다. 앱 종료 시 로컬 서버도 종료합니다. [Electrobun 구조·빌드·검증](docs/DESKTOP.md).

웹 개발 모드:

```sh
uv sync --frozen --python 3.12
uv run bioart inventory
uv run bioart serve --port 8765
```

브라우저에서 <http://127.0.0.1:8765>를 엽니다. 실행 경로와 무관하게 `--workspace /absolute/project/path` 또는 `BIOART_WORKSPACE`로 작업 폴더를 지정할 수 있습니다.

## 대화로 그림 만들기

클립아트 1–8개를 트레이에 담고 **대화로 그림 만들기**를 누르세요. Codex의 ChatGPT 구독으로 원본을 배치하거나, 클립아트를 참고한 AI 이미지를 생성할 수 있습니다. 대화로 수정하고 캔버스에서 라벨·위치·크기·화살표를 편집한 뒤 출처와 함께 내보냅니다. 이전 결과와 대화는 프로젝트에 저장됩니다. [제작실 사용 안내](docs/STUDIO.md)를 참고하세요.

Codex CLI 설치와 ChatGPT 로그인이 필요합니다. 별도 이미지 API 과금으로 자동 전환하지 않습니다.

## 사용할 수 있는 기능

- 933개 작품, 9,524개 유효 파일의 지연 로딩 갤러리
- 분야 탐색, 제목·원본 키워드·한영 별칭 검색, 형식·라이선스 필터
- `폐` → 폐포의 부분 관계 확장과 출처 표시, 직접 일치 범위 선택
- 작품별 파일 비교, 정확한 PNG/SVG 선택, 확대와 밝은/어두운 배경
- 검색 상태와 선택 트레이 저장, 최대 24개 파일 비교판
- 원본·체크섬·출처·확인된 라이선스 정보가 포함된 내보내기
- 로컬 stdio MCP의 검색·상세·관련 그림·미리보기·파일 전달
- Codex 기반 원본 조합·AI 이미지 생성, 대화 수정, 캔버스 편집, 버전 선택과 SVG·PNG·출처 내보내기

`⌘K`: 검색, `Tab`/`Enter`: 이동·선택, `Esc`: 상세/대화상자 닫기.

**미구현·미검증 범위:** 전체 이미지 시각 주석, 64개 파일럿의 사람 검토, embedding 기반 의미 검색, 정교한 온톨로지 탐색, 종·시점 필터, 이미지 내용 검토 편집기. 제목 기반 분야·개념은 후보이며 검증된 시각 주석이 아닙니다. 설명형 검색은 사전 정의한 기체 교환 활용 문구만 확장합니다. SVG 내부 경로 편집과 자동 재료 선택은 지원하지 않습니다. AI 이미지 생성은 참고 그림을 다시 그리므로 과학적 내용과 원본 보존을 보장하지 않습니다.

## 데이터와 재처리

원본 `BioArt_PNG_SVG/`에는 쓰지 않습니다. 인벤토리는 모든 파일의 SHA-256을 다시 읽고, PNG를 완전히 디코딩하며 SVG를 안전한 파생본으로 렌더링합니다. 변경되지 않은 썸네일은 재사용합니다. 카탈로그는 같은 볼륨에서 검증 후 교체하고 이전 DB를 남깁니다.

```sh
uv run bioart inventory       # 전체 검증, 카탈로그/내용 카드/64개 파일럿 준비
uv run bioart metadata        # 공개 페이지 수집, 캐시/재시도/ID와 제목 대조
uv run bioart reparse         # 보존한 응답을 현재 파서로 재처리, 네트워크 사용 없음
```

- `data/catalog/inventory-report.json`: manifest 항목별 상태
- `data/catalog/metadata-report.json`: 원본 정보 수집 상태
- `data/source_snapshots/`: 원문 HTML과 정규화 정보
- `data/annotations/content-cards.jsonl`: 파일별 명시적인 시각 검토 대기 상태
- `data/annotations/pilot.json`, `pilot-contact-sheet.jpg`: 64개 표본과 비교판
- `data/annotations/review-queue.jsonl`: 이미지 검토 대기열
- `state/`: 진행 상황·설정·선택 트레이·실행 로그
- `projects/`: revision을 갖는 편집 가능한 장면
- `exports/`: 파일/도해와 출처, ZIP

파일별 임시 representation을 부여했습니다. 같은 작품의 PNG와 SVG라도 출처상 대응이 확인되기 전에는 같은 표현이라고 자동 병합하지 않습니다. 라이선스 URL·credit이 없으면 미확인 상태를 유지합니다.

MRI file `782376`은 서버가 0바이트로 응답하여 미완료 상태입니다. 원본은 보존했고 검색·내보내기에서 제외합니다. 원본 ID `202`, `690`은 수집 응답에서 `601 / Domestic Cat`을 반환하여 메타데이터를 격리했습니다. 해당 작품 자체의 로컬 파일은 원래 manifest 제목으로 탐색 가능합니다.

## MCP

[설정과 호환성](docs/MCP.md)을 참고하세요. 앱이 꺼져 있어도 독립 실행할 수 있습니다.

## 검증

```sh
bun run typecheck
bun test tests/desktop
uv run pytest -q
uv run python script/verify_desktop_runtime.py
uv run python script/verify_mcp.py
uv run python script/evaluate_search.py
./script/build_and_run.sh --verify
```

[구현 상태·검증 보고서](docs/VALIDATION.md), [설계 선택](docs/IMPLEMENTATION_NOTES.md).

앱은 로컬 실행용 ad-hoc 서명입니다. Developer ID 서명·Apple 공증은 수행하지 않았습니다.

### 논문 출판용 출력

자유 도해 편집기의 **내보내기**에서 mm·DPI, PDF 글꼴 포함/윤곽선, PDF·TIFF·PNG·SVG를 선택하고 프리플라이트를 실행합니다. [사용법](docs/EDITOR.md)과 [실제 앱·파일 품질 검증](docs/PHASE4_VALIDATION.md)을 참고하세요. 소스 빌드에는 Cargo/Rust가 추가로 필요하며 출력 엔진은 앱에 포함됩니다.

### 휴대용 프로젝트 ZIP

편집기 상단 **프로젝트 ZIP**에서 편집 문서·참조 원본·생성 이미지·출처·미리보기·출력 설정을 내보내고, 다른 작업 폴더에 새 사본으로 가져옵니다. 원본 라이브러리가 없는 빈 작업 폴더에서도 재편집·출판 출력할 수 있습니다. 글꼴 파일은 동봉하지 않습니다. [사용법·제한](docs/PORTABLE_PROJECTS.md), [설치 앱 왕복 검증](docs/PORTABLE_VALIDATION.md).
