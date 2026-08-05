# REV-07 — Session Doğrulama ve Customer Impact Assessment

`CustomerImpactAssessmentService`, CausalEvent root/failure-domain kapsamındaki
aktif subscription connection'ları önce `potential_impact` olarak ele alır;
yalnız bu kapsamda SessionEvent kanıtıyla kalıcı assessment yazar. Connection
dışındaki kayıt verified impact olamaz.

Olay öncesi START/CONTINUE, pencerede STOP ve sonrasında START/CONTINUE;
`verified_impact` üretir. Olay boyunca CONTINUE ve STOP olmaması
`verified_no_impact`; yalnız STOP, çelişkili aynı-zaman kayıtları, geç kayıtlar
ve eksik lifecycle ise `insufficient_evidence` üretir. Hiç session yoksa
assessment `potential_impact` olarak bekler. Pencereler yalnız merkezi
synthetic calibration'dır; ticari veya operasyonel eşik değildir.

Primary connection etkilenirken aktif backup CONTINUE ile hizmeti koruyorsa
primary assessment `verified_no_impact` ve `failover_protected` olur. Birden
fazla connection ayrı değerlendirilir; full outage veya compensation sonucu
üretilmez.

DB unique constraint event+connection tek assessment'i korur; servis
`update_or_create` ile idempotent çalışır. Model DB invariant'ları potential
alt-kümesini ve verified-no-impact reason zorunluluğunu korur; session pattern
ve failover yorumları uygulama katmanındadır. Metadata ve public sonuçlar raw
payload, IP, MAC veya subscriber identifier taşımaz.

Aggregate özet potential, verified impact, verified no-impact, insufficient,
pending ve reason-code sayılarını connection-level assessment'lerden üretir.
REV-08 outage verification, eligibility, compensation ve DecisionEvidence
bağlantısını ele alacaktır. Açık konular gerçek session gecikme toleransı,
identity mapping ve degradation policy'sidir.
