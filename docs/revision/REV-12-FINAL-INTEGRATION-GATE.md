# REV-12 Final Entegrasyon ve Regresyon Kapısı

Final full suite `.venv/bin/pytest -q` ile çalıştırıldı: **667 passed**.
`ruff check backend mcp_servers` ve `python backend/manage.py check` temizdir.
CausalEvent → correlation → session impact → verified-impact compensation and
DecisionEvidence → internal API → dört MCP zinciri; legacy, pending/not_found
ve privacy contract testleriyle birlikte geçti. MCP tool sayıları 9 / 7 / 8 / 6
olarak kaldı.

Native reset'siz multi-city validation mevcut snapshotta beklenen REV-05
verisinin bulunmadığını gösterdi: `alarm_types expected=31 actual=30`,
`causal_events minimum=1 actual=0`, `causal_alarm_links expected=0 actual=2100`
ve `incident_alarm_causal_mismatches actual=420`. Native RAG seed de aynı
snapshot precondition'ında, eksik `DISTRIBUTION_CABLE_DOWN` nedeniyle
`alarm coverage mismatch` ile kayıt yazmadan durdu. Bu çalışma yeni canlı
source/chunk/embedding sayısı iddia etmez.

RAG manifest 13 descriptor ve benchmark 25 vakadır. Qwen
`qwen3-embedding:4b` ile Gemini `gemini-embedding-2` ayrı 768 boyutlu setler;
Qwen query prompt `qwen3-telecom-query-v1`dir. CSV corpus/runtime bağımlılığı
değildir. `SourceDocument.data_snapshot=PROTECT` reset blocker'ı değiştirilmedi;
destructive reset veya cleanup uygulanmadı.

REV-00–REV-12 kod, test ve sözleşme kapıları tamamlandı. Native snapshot
yenileme/PROTECT konusu açık teknik takip maddesidir. Sıradaki görev 052 —
QueryRun ve orchestration'dır.
