# SYN Causal Analysis 2026

Bu doküman ProcessTwin geliştirme ve test ortamı için hazırlanmış tamamen sentetik bir kaynaktır. Gerçek bir kurum, operatör veya yürürlükteki ticari politika belgesi değildir.

## Alarm ve CausalEvent Sınırı

Bir alarm tek başına outage, doğrulanmış müşteri etkisi veya telafi kanıtı değildir. `CausalEvent`, uyumlu alarm, topoloji ve zaman kanıtlarını aynı nedensel sınırda tutar; farklı CausalEvent kayıtları yalnız yakın zaman nedeniyle birleştirilmez.

## Roller ve Gecikmeli Yayılım

Root, fiziksel temel arıza adayını; child, üst olaydan yayılan alt kaynak alarmını; symptom, erişim ucundaki belirtiyi; supporting ise zinciri destekleyen fakat tek başına outage kanıtlamayan alarmı anlatır. Upstream root alarmı downstream child veya symptom alarmından önce başlayabilir; gecikmeli propagation bu nedenle değerlendirilir.

## Producer ve Physical Root Resource

Alarmı üreten producer system ile normalized physical root resource ayrı tutulur. `ACA Korelasyon` bir fiziksel NetworkDevice değildir ve physical root yerine geçmez. Açıklamalar public code, aggregate ve reason code kullanır; raw payload veya hassas kaynak kimliği içermez.

## Impact ve Session Evidence

Topology scope yalnız potential impact üretir. Verified impact için connection seviyesinde olay öncesi etkinlik ile etki penceresindeki STOP ve uygun START veya CONTINUE recovery kanıtı değerlendirilir. Verified no-impact, hizmetin sürdüğünü veya failover-protected backup yolun aktif kaldığını gösterebilir. Eksik, geç, çelişkili veya eşleşmeyen SessionEvent kayıtları insufficient evidence sonucuna gider.

## Privacy-safe Açıklanabilirlik

Session doğrulaması START, CONTINUE ve STOP lifecycle'ını deterministik değerlendirir. Public açıklama customer kimliği, IP, MAC, serial, username, credential veya raw session/alarm payload taşımaz.
