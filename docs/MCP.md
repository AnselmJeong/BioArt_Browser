# Local MCP

UI와 동일한 카탈로그와 검색 코어를 사용하는 stdio 서버입니다. HTTP 서버나 앱을 켤 필요가 없습니다.

## 클라이언트 설정

빌드된 독립 실행 파일을 사용하는 JSON 설정 예시:

```json
{
  "mcpServers": {
    "bioart": {
      "command": "/Volumes/Aquatope/_DEV_/BioArt_Browser/dist/BioArt Browser.app/Contents/Resources/backend/bioart-backend",
      "args": ["mcp", "--workspace", "/Volumes/Aquatope/_DEV_/BioArt_Browser"]
    }
  }
}
```

또는 개발 실행:

```sh
/Users/anselm/.cargo/bin/uv --directory /Volumes/Aquatope/_DEV_/BioArt_Browser run bioart mcp
```

경로를 실제 설치 위치에 맞추세요. 이 작업에서 사용자의 전역 MCP 설정은 수정하지 않았습니다.

## 도구

| 도구 | 입력 | 결과 |
|---|---|---|
| search_assets | query, topic, format, license, scope, limit, cursor | 후보·일치 방식·관계 근거·카탈로그 버전 |
| get_asset | artwork_or_representation_id | 작품과 파일별 상세 정보, 미검토 상태 |
| get_related_assets | artwork_id | 전체/부분 갤러리와 방향·출처 |
| preview_assets | representation_ids, 최대 24개 | 실제 PNG 이미지 콘텐츠와 번호·ID 대응표 |
| export_assets | file_ids, 최대 100개 | exports/의 새 폴더·ZIP·출처 manifest |
| render_scene | file_ids, layout, title | 초기 장면 문서, scene ID, revision |
| update_scene | scene_id, revision, patches, title | 명시적인 객체 ID의 라벨·좌표·크기 변경 |
| export_figure | scene_id | SVG·PNG·scene.json·manifest·SOURCES.md |

`scope`는 `direct` 또는 `related`입니다. 관련 탐색은 근거를 둔 1단계 관계만 사용합니다. `rep-630893`처럼 representation ID와 정확한 file ID를 구분하세요. 출력 경로는 임의로 지정할 수 없으며 새로운 workspace exports 폴더만 생성합니다. 내보내기마다 원본 SHA-256을 다시 확인합니다.

반환 경로는 **동일 컴퓨터에서만** 의미가 있습니다. 원격 파일 URL이 아닙니다. 이미지가 필요한 클라이언트는 `preview_assets`의 MCP ImageContent를 사용하세요.

## 확인한 호환성

| 클라이언트 | 검색/상세 | PNG ImageContent 수신 | 정확한 파일 내보내기 | 도해 수정·내보내기 |
|---|---|---|---|---|
| 공식 MCP Python SDK ClientSession / stdio | 검증 | 검증 | 검증 | 검증 |
| Codex/Claude 등 실제 제품에 사용자 설정으로 등록 | 미검증 | 미검증 | 미검증 | 미검증 |

SDK 클라이언트 통합 검증은 제품별 UI가 모델에 이미지를 어떻게 전달하는지에 대한 보장이 아닙니다. `script/verify_mcp.py`와 `state/mcp-validation.json`에 실제 검증 절차와 선택한 파일 ID가 남습니다.
