"""Measure baseline latency and transparent smoke queries, not semantic accuracy."""

import json
import platform
import statistics
import time
from pathlib import Path
from bioart.core import catalog

queries = [
    "Human Lungs",
    "폐",
    "lung",
    "폐포",
    "alveolus",
    "alveoli",
    "산소가 혈액으로 이동하는 과정",
    "gas exchange",
    "항체",
    "antibody",
    "antibodies",
    "대식세포",
    "macrophage",
    "T 세포",
    "B 세포",
    "뉴런",
    "neuron",
    "뇌",
    "brain",
    "심장",
    "heart",
    "신장",
    "kidney",
    "세균",
    "bacteria",
    "바이러스",
    "virus",
    "DNA",
    "RNA",
    "실험",
    "현미경",
    "microscope",
    "화살표",
    "mitochondria",
    "no-such-asset-zz123",
]
catalog.refresh()
samples = []
results = []
for q in queries:
    start = time.perf_counter()
    r = catalog.search(q)
    elapsed = (time.perf_counter() - start) * 1000
    samples.append(elapsed)
    results.append(
        dict(
            query=q,
            count=r["total"],
            top_ids=[i["id"] for i in r["items"][:5]],
            match_types=[i["match_type"] for i in r["items"][:5]],
            milliseconds=round(elapsed, 3),
        )
    )
lung = catalog.search("폐")
assert any(
    i["title"] == "Alveoli"
    and i["match_type"] == "relation"
    and i["relation"]["predicate"] == "part_of"
    for i in lung["items"]
)
assert catalog.search("no-such-asset-zz123")["total"] == 0
report = dict(
    machine=platform.platform(),
    catalog_version=catalog.version,
    query_count=len(queries),
    p95_ms=round(sorted(samples)[int(len(samples) * 0.95)], 3),
    mean_ms=round(statistics.mean(samples), 3),
    precision_at_10=None,
    recall_at_20=None,
    accuracy_note="No human-reviewed relevance set yet; this measures baseline behavior and latency only.",
    results=results,
)
Path("docs/search-evaluation.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
print(
    json.dumps(
        {k: v for k, v in report.items() if k != "results"},
        ensure_ascii=False,
        indent=2,
    )
)
