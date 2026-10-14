# 4단계 휴대용 프로젝트 검증

2026-10-14 · 설치 앱 `/Applications/BioArt Browser.app` · Apple Silicon macOS

## 구현과 사용

상단 **프로젝트 ZIP**에서 `bioart-project` v1 ZIP을 내보내고 새 사본으로 가져온다. 문서·필요한 SVG/PNG 원본·생성 이미지·출처·미리보기·출력 설정을 포함한다. 과학 객체 설정과 벡터 경로, 수식 원문, 표 셀, 확대 삽화 참조를 유지한다. [사용법·형식·제한](PORTABLE_PROJECTS.md).

기존 출판 ZIP은 출력물 배포용이다. 휴대용 ZIP과 혼동해 가져오면 안내 오류를 표시한다. 파일 ID는 가져오기마다 독립적인 ID로 치환하여 기존 카탈로그와 다른 사본을 덮어쓰지 않는다. 리소스를 임시 배치하고 검증한 뒤 문서를 마지막에 원자적으로 저장한다.

## 설치 앱에서 수행한 왕복

1. 기존 **검증 · 폐–폐포 가스 교환** r22와 **검증 3 · 실험과 결과** r4를 앱의 프로젝트 ZIP 버튼으로 내보냈다.
2. 파일 메뉴의 작업 폴더 선택으로 `state/portable-validation/native-workspace` 빈 폴더로 전환했다. 해당 폴더에는 원본 BioArt 라이브러리와 SQLite 카탈로그가 없으며 실제 앱은 0개 자료를 표시했다.
3. macOS 파일 선택 창으로 두 ZIP을 각각 가져왔다. 폐·폐포의 원본 SVG 2개가 프로젝트 내부에 보관되고 렌더링됐다. 패널·튜브·하이드로젤·표·수식도 정상 복원됐다.
4. 가져온 폐·폐포 도해의 제목을 바꾸고 그룹의 가로 위치를 700에서 710으로 수정했다. 연결선도 갱신됐고 새 문서 `doc-301e57acaed6` r3로 저장됐다. 과학 도해는 제목을 바꾸어 `doc-cd4e04659da4` r2로 저장했다.
5. ⌘Q로 앱을 완전 종료하고 앱/백엔드 프로세스가 종료된 것을 확인했다. 설치 앱을 다시 실행한 뒤 두 도해를 선택해 저장 내용과 그림 복원을 확인했다.
6. 가져온 폐·폐포 수정본에서 출판 프리플라이트·PDF/TIFF/PNG/SVG 출력을 실행했다. ZIP에 담았던 174 mm·600 DPI·윤곽선 설정이 유지됐다. 오류 0 / 경고 3: 원본 SVG 필터 부분 래스터화, 가는 선, 일부 문자 대체 글꼴.
7. 수정본을 휴대용 ZIP으로 다시 내보내고 모든 항목의 SHA-256, CRC, 포함한 SVG 원본 바이트 일치를 확인했다.
8. 원래 작업 폴더로 되돌려 기존 933개 작품·9,524개 파일 라이브러리를 확인했다. 원본 두 도해의 정규화된 문서는 검증 시작 전과 동일하다.

같은 Mac의 별도 폴더에서 라이브러리 독립성을 검증했다. 다른 OS/컴퓨터의 폰트 환경까지 검증한 것은 아니다.

## 파일 품질과 편집 데이터

- TIFF: 4110 × 2496, 600 DPI, RGB, sRGB ICC, LZW 무손실 압축. PNG와 디코딩한 픽셀이 완전히 동일하다.
- PDF: 1페이지, 493.22836 × 299.46008 pt (174 × 105.64 mm), 윤곽선 모드, 필터 부분만 이미지 2개. Poppler로 별도 렌더링한 PDF와 TIFF의 RGB 채널별 평균 절대 차이는 최대 0.08682/255다. 미리보기 시각 검사에서 한글·폐·폐포·연결선과 레이어가 유지됐다.
- 실험·결과 도해의 전체 nodes 배열은 가져오기 전과 동일하다. 제목·문서 ID·revision만 새 사본에 맞게 바뀌었다.
- 엔진을 통한 별도 빈 작업 폴더 왕복에서는 실험·결과, 세포 신호전달/확대 삽화, DNA, 자유 브러시/수식 도해 4개 모두 렌더링 SVG와 과학 생성기 설정이 동일했다.

## 자동 검사와 패키지

- Python **101 tests** 통과. 휴대용 프로젝트 테스트 11개: 원본/생성 이미지/출처 참조/표 왕복과 재출력, 반복 가져오기, ZIP 경로·중복·심볼릭 링크·해제 크기, 손상·누락 자료·미래 버전·잘못된 PNG, 재배포 조건, revision 충돌, 저장 실패 시 정리, 실제 바이너리 업로드 API의 토큰·Origin 검사.
- Bun **15 tests / 57 assertions** 통과. TypeScript 프로젝트 진단 0건; 기존 upstream SDK 진단 15건은 기존 검사 스크립트에서 제외한다.
- 앱 전체 빌드·설치 완료. 설치 앱과 dist 앱의 strict/deep 서명 검사 통과. 기존 앱 백업은 `dist/BioArt Browser.pre-portable.app`이다.
- 저장소는 작업 시작부터 untracked 상태였다. 관련 파일 whitespace 검사 완료. 커밋·푸시는 수행하지 않았다.

## 재현 자료

- 최초 원본 포함 ZIP: `exports/project-doc-8be34ac1ed70-r22-8b6e71.zip`
- 과학 객체 ZIP: `exports/project-doc-d79ccf768079-r4-de52c7.zip`
- [가져오기·수정 후 재내보낸 ZIP](/Volumes/Aquatope/_DEV_/BioArt_Browser/state/portable-validation/native-workspace/exports/project-doc-301e57acaed6-r3-ba9c52.zip)
- [가져온 도해의 출판 출력 폴더](/Volumes/Aquatope/_DEV_/BioArt_Browser/state/portable-validation/native-workspace/exports/doc-301e57acaed6-r3-92c056)
- 독립 검사: `state/portable-validation/verify_native.py`, `native-verification.json`, `science-roundtrip.json`, `pdfinfo.txt`, `pdffonts.txt`.
- 실제 앱 캡처: `native-empty-workspace.png`, `native-import.png`, `native-imported-edited.png`, `native-science-reopened.png`, `native-publication-result.png`, `native-reexport.png`.

![빈 작업 폴더에서 가져온 과학 도해를 앱 재시작 후 열기](/Volumes/Aquatope/_DEV_/BioArt_Browser/state/portable-validation/native-science-reopened.png)

## 남은 제한

글꼴 파일은 동봉하지 않는다. 다른 환경에서는 필요한 글꼴 설치와 프리플라이트 확인이 필요하다. 가져온 출처 정보는 ZIP 제공 정보를 보존한 것이며 온라인 재검증을 의미하지 않는다. 체크섬은 파일 손상을 확인하며 발신자를 인증하지 않는다. 재배포 조건을 확인할 수 없는 원본은 누락된 프로젝트를 내보내지 않고 오류로 중단한다. PDF/X·PDF/A·CMYK 인증과 mm/in/px 입력 단위 전환은 확장 범위로 남는다.
