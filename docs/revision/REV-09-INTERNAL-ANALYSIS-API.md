# REV-09 — Internal Causal Analysis API

`GET /api/internal/v1/operations/causal-events/<event_code>/analysis/` authenticated
internal callers için CausalEvent, root-cause, impact aggregate, evidence ve
compensation placeholder özetini read-only döndürür. Endpoint mevcut
REV-06/REV-07 servislerini çağırır; yeni hesap yazmaz. Bilinmeyen kod 404,
eksik analysis ise boş/null bölümler döndürür. Public response PK, PII, raw
alarm/session payload veya credential içermez. Legacy incident/outage yüzeyleri
değişmez; REV-10 MCP uyarlamasına bırakılmıştır.
