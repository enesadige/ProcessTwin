# SYN 2026 Alarm Kataloğu v2

Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## LOS Family ve Subtype Ayrımı

LOS family içinde feeder veya OLT LOS, ONU LOS, PON LOS ve kaynak seviyesi belirsiz generic Loss Of Signal ayrı canonical subtype olarak korunur. Aynı family adı, fiziksel kaynak seviyesinin körlemesine birleştirileceği anlamına gelmez.

## Dying Gasp ve Device Not Active

Dying Gasp ve Device Not Active erişim ucuna yakın symptom kanıtlarıdır. Yoğun Dying Gasp kaydı otomatik root cause değildir. Root adayında CausalEvent root resource, upstream konum, zaman sırası ve failure-domain kanıtı birlikte değerlendirilir.

## Producer ve Severity

`ACA Korelasyon` correlation producer bilgisidir; fiziksel cihaz tipi değildir. Raw severity mevcutsa korunur. Katalog default severity yalnız raw severity eksik veya geçersizse fallback olarak kullanılır.

`XREG_UPSTREAM_DOWN`, bölgeler arası deterministic korelasyon senaryolarında kullanılan sentetik upstream alarmıdır. Bu kod ancak zaman ve topoloji kanıtıyla birlikte ilişki desteği sağlar; tek başına ortak fiziksel kök neden oluşturmaz.
