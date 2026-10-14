# 4단계 출판 출력 검증

2026-10-14 · 설치 앱 `/Applications/BioArt Browser.app` · Apple Silicon macOS

이 문서는 출판 출력 구현 시점의 검증 기록이다. 이후 휴대용 프로젝트 ZIP 내보내기·가져오기를 추가하고 빈 작업 폴더에서 검증했다. 현재 휴대성 지원 범위와 결과는 [PORTABLE_VALIDATION.md](PORTABLE_VALIDATION.md)를 참고한다.

## 구현

- 벡터 PDF 1.7, LZW TIFF, PNG, 물리 크기 SVG. 너비 mm와 DPI 직접 입력 및 85/174/180 mm 빠른 선택.
- PDF 글꼴 부분 포함 / PDF·SVG 윤곽선. 사용 글꼴·대체·누락 문자·포함 제한 검사.
- 실제 출력 크기에 따른 글자/선 굵기, 원본 래스터 유효 DPI, 누락/변경 자료, 출력 경계, 투명도, 출처·라이선스 검사.
- 불변 revision 스냅샷을 한 작업씩 출력. 최대 세 작업 대기, 진행률·취소, 도해별 설정 저장. 5,000만 픽셀/20,000픽셀 및 SVG 필터 메모리 한도.
- PNG/TIFF 픽셀 수·DPI·sRGB ICC 및 PDF 페이지 크기·폰트 검증. ZIP CRC와 출력별 SHA-256 포함.
- 기존 SVG 정리 코드에서 검증된 내장 PNG/JPEG를 보존하도록 수정. 외부 URL·파일·중첩 SVG 데이터는 계속 차단.

## 실제 앱 검증

소스 실행 서버가 아닌 설치된 Electrobun 앱에서 기존 도해를 선택하고 프리플라이트 및 내보내기를 실행했다. 앱을 완전 종료한 뒤 재시작해 실험·결과 도해의 저장본 4와 174 mm/600 DPI/글꼴 포함 설정 복원을 확인하고 재출력했다. 원본 도해 JSON은 출력 전후 동일하다.

| 기존 도해 | 출력 | 픽셀 | PDF | 경고 |
|---|---|---|---|---|
| 검증 3 · 실험과 결과 · r4 | 174 mm / 600 DPI | 4110 × 2496 | embed · 폰트 3 / 래스터 0 | 2 |
| 검증 3 · 세포 신호전달 · r4 | 85 mm / 1200 DPI | 4016 × 2438 | outline · 폰트 0 / 래스터 0 | 126 |
| 검증 · 폐–폐포 가스 교환 · r22 | 174 mm / 600 DPI | 4110 × 2496 | outline · 폰트 0 / 래스터 2 | 3 |

85 mm 축소 도해의 경고는 작은 글씨·가는 선이 대부분이다. 높은 DPI가 물리 글자 크기를 키우지 않는다는 것을 확인했다. 폐·폐포 SVG의 필터 부분만 PDF 이미지가 되며 전체 페이지를 래스터화하지 않는다. 도해별 폰트 대체와 가는 선 경고는 preflight.txt/json에 보존된다.

앱에서 1,000 mm / 2,400 DPI를 입력하면 출력 한도 오류가 표시되고 내보내기가 비활성화된다. 설정을 다시 174 mm / 600 DPI로 바꿔 검사하면 출력 가능 상태로 돌아온다.

## 파일 품질

- 모든 TIFF: RGB, LZW, 정확한 DPI 값, sRGB ICC. PNG와 디코딩한 픽셀이 완전히 동일하다.
- 174 mm PDF: 493.22836 × 299.46008 pt, 1페이지. 85 mm PDF: 240.94488 × 146.28796 pt.
- 글꼴 포함 PDF: HelveticaNeue, HelveticaNeue-Bold, ArialUnicodeMS의 부분 포함과 ToUnicode 확인. 한글 검색/텍스트 추출 정상.
- 윤곽선 PDF: 글꼴 리소스 없음. 과학 생성기 도해의 PDF 래스터 리소스 없음.
- Poppler `pdfinfo`, `pdffonts`, `pdftoppm`으로 독립 검사. PDF를 TIFF와 동일 픽셀 크기로 렌더링하고 시각 검사했다. 한글·표·분수 수식·원형 확대 삽화·세포막·BioArt 레이어 순서가 유지된다.
- PDF와 TIFF의 채널별 평균 절대 차이는 최대 0.3591/255. 서로 다른 렌더러의 안티앨리어싱 차이가 있으므로 픽셀 완전 일치를 주장하지 않는다.

## 재현 자료

- [검증 3 · 실험과 결과 출력 폴더](/Volumes/Aquatope/_DEV_/BioArt_Browser/exports/doc-d79ccf768079-r4-366212) — job `pub-3fcc6c4e936944f6`
- [검증 3 · 세포 신호전달 출력 폴더](/Volumes/Aquatope/_DEV_/BioArt_Browser/exports/doc-31cce85e8efc-r4-e23968) — job `pub-f328e7cf1fc74e72`
- [검증 · 폐–폐포 가스 교환 출력 폴더](/Volumes/Aquatope/_DEV_/BioArt_Browser/exports/doc-8be34ac1ed70-r22-ad3e01) — job `pub-e56ee9fe24634e35`

- 상세 수치와 파일 해시: `state/phase4-validation/verified-outputs.json`
- 재검증 스크립트: `state/phase4-validation/verify_outputs.py`
- 실제 UI: `native-preflight.png`, `native-limit.png`, `native-source-preflight.png`, `native-final-result.png`
- PDF/TIFF 미리보기 및 Poppler 로그: `state/phase4-validation/doc-*-pdf-preview.png`, `doc-*-tiff-preview.png`, `doc-*-pdfinfo.txt`, `doc-*-pdffonts.txt`

## 자동 검사

- Python 90 tests 통과. 신규 출판 테스트 9개: 실제 변환/폰트/치수/ICC/무손실 픽셀, 유효 DPI, 누락 자료, 취소/불변 스냅샷/설정, 투명 배경, 누락 문자, 내장 이미지 보안, 변환된 필터 해상도·메모리 한도.
- Bun 15 tests / 57 assertions 통과. TypeScript 프로젝트 진단 0건; 기존 upstream SDK 진단 15건은 기존 검사 스크립트에서 제외한다.
- `git diff --check` 및 변경한 untracked 구현 파일 10개 별도 whitespace 검사 통과. 저장소는 작업 시작 시부터 전부 untracked 상태였으며 커밋/푸시하지 않았다.
- 패키지 빌드, 설치 앱과 dist 앱의 `codesign --verify --deep --strict` 통과. 앱은 Python/Cargo 개발 환경 없이 포함된 출력 엔진으로 실행한다.

## 범위와 한계

이번 구현은 사용자가 요청한 출판 출력 범위다. PDF/X·PDF/A·CMYK 인증, 특정 저널 제출 적합성 보증, 실제 인쇄/교정쇄 검증, 휴대용 프로젝트 가져오기, mm/in/px 입력 단위 전환은 포함하지 않는다. 현재 ZIP은 출력 묶음이다. 효과는 필요 시 부분 래스터화하며 원본 래스터 해상도 부족은 경고한다. 클리핑된 일반 객체의 경계 검사는 클리핑 전 경계에 따른 보수적 경고일 수 있다. 앱을 종료하면 진행 중인 출력은 중단되므로 완료까지 열어 둔다.
