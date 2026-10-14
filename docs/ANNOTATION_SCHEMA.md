# Annotation gate · schema 0.1

현재 `content-cards.jsonl`의 모든 유효 representation은 `pending_visual_review`입니다. 파일 제목, 픽셀 크기, alpha/bounding box 측정값은 관찰 주석이나 생물학적 정체성 검증을 의미하지 않습니다.

필수 식별자: `schema_version`, `representation_id`, `input_file_ids`, `input_fingerprint`, `annotation_status`.

시각 주석을 도입할 때 각 assertion은 `field`, `value`, `evidence_type`, `evidence_ref`, `review_status`를 포함해야 합니다. 원본 설명과 실제 관찰은 다른 assertion으로 기록합니다. `accepted`에는 검토자/검토 규칙과 시각이 필요합니다. 현재 자동 accepted 처리는 없습니다.

파일럿: 64개 작품에서 서로 다른 파일 64개를 선택했습니다. 호흡/면역/장비/분자/생물/단순 도형을 우선 포함하고 나머지는 파일 ID의 안정적인 해시 순서로 선택했습니다. 원본 representation mapping 미확정이므로 표본 단위는 provisional file representation입니다. 모델 선택·호출·비용 측정·사람 전수 검토는 미실시이며 비용/정확도는 `null`입니다.

PNG/SVG pairing은 현재 모든 파일에서 provisional 상태입니다. 가까운 file ID나 이름만으로 확정하지 않습니다. 파일별 SHA-256이 파생 미리보기 캐시와 내용 카드의 입력 fingerprint입니다.

후속 모델 어댑터를 도입하기 전에 파일럿의 주 대상·관찰·추론 분리·한영 검색어·배치 재처리 키를 사람이 검토해야 합니다. 기존 원본 스냅샷, 수동 검토 이벤트, 모델 실행 결과를 별도 저장하고, 새 배치가 수동 수정을 덮어쓰지 않도록 이력 병합 계약을 먼저 구현해야 합니다.
