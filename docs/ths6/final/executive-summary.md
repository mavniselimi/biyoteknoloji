# Yönetici özeti — THS 6 kanıt paketi (WP-25)

## Tek cümlelik sonuç

Yazılım tamamlandı; **THS 6 seviyesi kazanılmadı**, ve kazanılmamasının
nedeni yazılımda bir eksiklik değil, henüz yapılmamış bilimsel, insani ve
operasyonel işlerdir.

## Rakamlarla durum

| Alan | Değer |
|---|---|
| WP-25 yazılım durumu | UYGULANDI (IMPLEMENTED) |
| Kanıt paketi bütünlüğü | GEÇTİ (PASS) |
| Kapılar A–F | altısı da ENGELLİ (BLOCKED) |
| Toplam engelleyici sayısı | 45 |
| Engelleyicilerin sahibi olan rol sayısı | 12 |
| Tanım-tamamlandı maddeleri | 15 maddeden 1'i sağlandı |
| Temsili gösterim | çalıştırılmadı; ön kontrol DEMO-02'de duruyor |
| İnsan imzaları | 9 rolden 0'ı imzaladı |
| İddialar | 24 iddiadan 0'ı destekleniyor, 22'si çürütülüyor |
| `ths6_achieved` | **false** |
| `release_may_proceed` | **false** |

## İki ayrı sonuç, asla birbirine karıştırılmaz

**Kanıt paketi bütünlüğü GEÇTİ.** Bu, paketin kendi baytları hakkında bir
ifadedir: her üye dosya yerinde, her özet değeri (hash) tutuyor, bildirim
dosyası kendisi hariç her şeyi kapsıyor.

**THS 6 kazanılmadı.** Bu, programın kendisi hakkında bir ifadedir.

Sağlam bir paketin, engellenmiş bir programı dürüstçe kaydetmesi tam olarak
bugün beklenen sonuçtur. Paketin geçerli olması, standardın kazanıldığı
anlamına **gelmez** ve bu iki alan hiçbir yerde birbirinden türetilmez.

## Yapılan işin niteliği

Bu çalışma paketi yeni bir özellik eklemedi. WP-00'dan WP-24'e kadar
üretilmiş 145 belgeyi envanterledi, her birinin SHA-256 özetini aldı, kendi
şemasına göre doğruladı, ve altı kapıyı bu belgelerin kendi alanlarından
yeniden kurdu. Her kapı koşulu, hangi dosyanın hangi alanından okunduğunu
söyler; okuyucu dosyayı açıp itiraz edebilir.

## Neden hiçbir kapı geçmiyor

- **Kapı A (Bilimsel veri):** kayıtlı 20 kaynağın hiçbiri onaylanmadı;
  kanonik veri kümesi yayımlanmadı; ham anlık görüntü karantinada.
- **Kapı B (Kurallar):** küratörlük protokolü onaylanmadı; küratörlükten
  geçmiş yorum, onaylanmış kural ve çalıştırılabilir kural kümesi sayısı sıfır.
- **Kapı C (Temel güvenlik):** yönetişimli içerikten hesaplanmış tek bir
  değerlendirme yok; güvenlik kapısı kendi belgesinde ENGELLİ; iddia sınırı
  hâlâ taslak; aktif sürüm yok.
- **Kapı D (Doğrulama):** 50 vaka hedefine karşı sıfır doğrulama vakası;
  bağımsız ayrık küme yok; hesaplanmış tek bir metrik değeri yok; adı konmuş
  uzman hakem yok; tamamlanmış uzman incelemesi yok.
- **Kapı E (Operasyonel):** veritabanı, oturum deposu, denetim deposu ve
  konteyner çalışma zamanı yok; göç uygulanmadı; denetim zinciri
  doğrulanmadı; yedek geri yükleme hiç çalıştırılmadı; CI hiç çalışmadı.
- **Kapı F (THS 6):** A–E kapılarından herhangi biri geçmedikçe F geçemez.
  Bu kural iki kez uygulanır: F'nin kendi koşulu olarak ve toplu değerlendirme
  sırasında ayrıca.

## Bulunan gerçek kusurlar

1. **WP-17'nin kapı belgesi kendi şemasını sağlamıyor.**
   `data/web/wp17-real-gate-status.json` dosyası
   `screenshot_evidence_status: "CAPTURED"` kaydediyor; yayımlanmış şeması
   yalnızca `"NONE"` ve `"BROWSER_CAPTURED"` değerlerine izin veriyor. Üretici
   kod, testler ve şema hiç birbiriyle karşılaştırılmamış. WP-25 bunu
   onarmıyor — başka bir çalışma paketinin belgesini düzeltmek bu paketin işi
   değil — ama kaydediyor.

   > **WP-C00 (Yürütme Dalgası 1, bölüm A.6) ile giderildi.** Yukarıdaki
   > kayıt, WP-25 paketi üretildiği andaki durumu anlatır ve bu nedenle
   > değiştirilmeden bırakılmıştır. Üretici artık şemanın baştan beri
   > bildirdiği `"BROWSER_CAPTURED"` değerini yazıyor. Onarım tek bir
   > örneği değil sınıfı hedefliyor: sözcük dağarcığının tek bir yeri var,
   > `apps.web.gate_status.SCREENSHOT_EVIDENCE_STATUSES`; üretici, yayımlanan
   > şema ve testler aynı yerden okuyor. Ayrıca `tests/unit/web/test_snapshots.py`
   > her koşuda belgeyi kendi şemasına karşı doğruluyor — kimsenin yapmadığı
   > karşılaştırma buydu. `pgx-ths6 inventory` artık `0` ile çıkıyor ve
   > `THS6_EVIDENCE_INVALID` bulgusu kapatıldı.

2. **Tanım-tamamlandı madde sayısı uyuşmazlığı.** WP-25'in kendi metni 14
   madde olduğunu söylüyor; `architecture.md` §21 on beş madde sayıyor. Hiçbir
   madde birleştirilmedi, yeniden numaralandırılmadı veya atılmadı: on beşi de
   ayrı ayrı değerlendirildi ve uyuşmazlık sahibiyle birlikte kayda geçti.

3. **Dört kaynak belgesi çelişkisi.** İki yetkili belge aynı olgu hakkında
   farklı şey söylediğinde WP-25 çelişkiyi kaydeder ve **çözmez**. İki değerden
   birini seçip diğerini elemek, bir kanıt paketini savunuculuğa
   dönüştürür.

4. **WP-24'ün kapanış metni yanlıştı.** `docs/ths6/` dizininin var olmadığını
   söylüyordu; içinde üç ön belge zaten duruyordu. Üçü de korundu.

## Erişilemeyen iki kaynak belge

WP-25 tanımında adı geçen iki gereksinim belgesi, bu paketin üretildiği
ortamdan okunamadı: onları içeren klasör oturuma bağlı değil. Gereksinimler
bu nedenle depodaki `architecture.md` dosyasından alındı. Okunamayan
belgelerin içeriği hakkında hiçbir çıkarım yapılmadı, hiçbir yerde
alıntılanmadı veya özetlenmedi.

## Bundan sonra ne olur

Kalan işlerin tam listesi için [`what-remains.md`](what-remains.md) belgesine
bakınız. Kısaca: eksiklerin hiçbiri kod yazarak kapatılamaz. Onaylayacak bir
insan, küratörlükten geçirilecek bir bilimsel içerik, yazılacak doğrulama
vakaları, tamamlanacak bir uzman incelemesi ve kurulacak bir çalışma ortamı
gerekiyor.
