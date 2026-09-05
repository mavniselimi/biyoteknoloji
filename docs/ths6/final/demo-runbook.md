# Gösterim el kitabı — temsili iş akışı (WP-25)

Bu belge, temsili gösterimin nasıl yürütüleceğini ve bugün nerede durduğunu
anlatır. **Bugün gösterim çalıştırılamaz**; ön kontrol ikinci adımda durur.
Bu el kitabı hem gösterimin yapılabildiği günü hem de bugünü kapsar.

## Önce ön kontrol, her seferinde

```
pgx-ths6 demo-preflight
```

Çıkış kodu:

- `0` — bütün ön koşullar sağlandı, gösterim dürüstçe yapılabilir
- `2` — engelli; ön kontrol ilk sağlanmayan koşulda durur ve **koruduğu adımı
  çalıştırmaz**

Bugünkü sonuç: `2`, DEMO-02'de duruyor.

Ön kontrolü atlamanın bir yolu yoktur. `--force`, `--assume`, `--fixture`
veya `--ignore-blocker` diye bir seçenek yoktur ve hiçbir kod yolu bunları
başka bir yazımla kabul etmez.

## Ortam koşulları — gösterimin gereği, engeli değil

| Kod | Koşul | Bugünkü durum |
|---|---|---|
| DEMO-ENV-01 | Ağ erişimi yok | sağlanıyor |
| DEMO-ENV-02 | Dil modeli kapalı | sağlanıyor |
| DEMO-ENV-03 | Bütün P1 özellikleri kapalı | sağlanıyor |

DEMO-ENV-03 bir bayrak okunarak değil, **o özelliği gerçekleştirecek
modüllerin diskte var olup olmadığına bakılarak** ölçülür. Özelliği içeren bir
yapıda varsayılanı kapalı olan bir bayrak, birinin açabileceği bir bayraktır.

## On adım

| Adım | Ne yapılır | Görülmesi gereken |
|---|---|---|
| DEMO-01 | Arayüzü ağsız sun | vaka seçim sayfası yerel şablonlardan render edilir |
| DEMO-02 | Yönetişimli katalogdan vaka seç | onaylı içerikten gelen bir vaka listelenir |
| DEMO-03 | Aktif sürüm paketini çöz | yazılım, veri kümesi ve kural kümesi sürümleri adlandırılır |
| DEMO-04 | Fenotip profili gönder | profil kabul edilir, normalize edilir, yorumu geri gösterilir |
| DEMO-05 | Kapsamı hesapla ve ayrı eksen olarak göster | kapsanmayan, düşük risk değil, kapsanmamış olarak görünür |
| DEMO-06 | Değerlendirmeyi deterministik hesapla | aynı girdi tekrar hesaplandığında bayt bayt aynı olgular |
| DEMO-07 | Raporu kanıt bağlantılarıyla üret | her bulgu, geldiği yönetişimli kanıt kaydına bağlanır |
| DEMO-08 | Yönetişimli denetim olayını yaz | aktör, zaman, girdi özeti, sürüm paketi, çıktı özeti; zincir doğrulanır |
| DEMO-09 | Doğrulama panosunu göster | sürüme atfedilmiş metrik değerleri; boş durum değil |
| DEMO-10 | Bütün akışı dağıtılmış ortamdan sun | sağlık kontrollerine yanıt veren bir ortam |

## Bugün nerede duruyor

- **DEMO-01: ön koşulları sağlanıyor.** Arayüz gerçekten render ediliyor,
  şablonlar izin listesiyle eşleşiyor, ağ gerekmiyor, model kapalı.
- **DEMO-02: ENGELLİ.** Onaylanmış bilimsel kaynak sayısı sıfır. Sahibi:
  bilimsel kaynak onaylayıcısı.
- **DEMO-03 … DEMO-10: DENENMEDİ.** Ön kontrol ilk durduğu yerden sonrasını
  değerlendirmez. Bu bir eksiklik değil, kasıtlı bir tasarımdır: sonraki
  adımların da başarısız olacağını listelemek, gösterimin yedek yolunu
  sistemin kendisi gibi sunma ihtimalini doğurur.

## Gösterim sırasında bir şey ters giderse

Ondört senaryonun tamamı ve her birinin **neyi kanıtlamadığı** için
[`contingency-plan.md`](contingency-plan.md) belgesine bakınız. En sık
gerekecek üçü:

- **Ağ yoksa:** devam edin. Gösterim zaten çevrimdışı çalışacak şekilde
  tanımlanmıştır.
- **Veritabanı yanıt vermiyorsa:** durun. Daha önce hesaplanmış bir sonucu,
  şimdi hesaplanmış gibi göstermeyin.
- **Klinik doğrulama sorulursa:** hiçbir klinik doğrulama yapılmadığını
  söyleyin, yumuşatmadan, ve eksik olanı sayın: sıfır doğrulama vakası, ayrık
  küme yok, hesaplanmış metrik yok, tamamlanmış uzman incelemesi yok.

## Yerel prova asla "staging" değildir

Bu depoda yerel bir prova çalıştırılırsa sonucu `LOCAL_STAGING_REHEARSAL`
etiketiyle taşınır. Bu etiket zorunludur ve şema düzeyinde uygulanır. Yerel
bir süreç, dağıtılmış bir ortam olarak sunulamaz.
