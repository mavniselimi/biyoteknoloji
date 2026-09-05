# MVP-2 Alternatif Aday Ön Sıralama Raporu

## Güvenlik Notu

Bu bölümde listelenen alternatifler tedavi önerisi değildir. Aday ilaçlar yalnızca aynı terapötik bağlam veya ilaç sınıfı üzerinden farmakogenetik risk açısından ön sıralama yapmak amacıyla gösterilmiştir. Doz, ilaç değişimi veya tedavi kararı yalnızca hekim tarafından klinik tablo, endikasyon, laboratuvar değerleri ve güncel kılavuzlar dikkate alınarak verilmelidir.

## Girdi Özeti

- **Kaynak ilaç:** clopidogrel
- **Profil ID:** P2_cyp2c19_poor
- **Profil adı:** CYP2C19 poor metabolizer profili
- **Mevcut ilaç listesi:** clopidogrel, voriconazole, codeine, warfarin, amitriptyline
- **Aday sayısı:** 2

## Kaynak İlaç Risk Özeti

clopidogrel için seçili CYP2C19 poor profilde Yüksek dikkat farmakogenetik dikkat bayrağı oluşmuştur.
Aynı terapötik bağlamda değerlendirilebilecek adaylar seed veri setinden alınmıştır. Bu adaylar tedavi önerisi değildir. Mevcut MVP veri seti üzerinden adayların farmakogenetik dikkat durumu karşılaştırmalı olarak gösterilmiştir.

- **CYP2C19:** CYP2C19 aktivitesi düşük olduğunda clopidogrel aktif metabolite daha az dönüşebilir; bu durum antiplatelet yanıtın azalması açısından dikkat gerektirir. (`decreased_activation`, `reduced_response_attention`)

## Alternatif Aday Sıralaması

| Sıra | Aday | MVP veri durumu | MVP alternatif uygunluk ön skoru | Skor etiketi | Aday özel PGx değerlendirmesi | Senaryo dikkat düzeyi | Senaryo bayrak sayısı |
|---:|---|---|---:|---|---|---|---:|
| 1 | prasugrel | insufficient_pgx_rule_data | 59 | veri sınırlı / yorum dikkatli yapılmalı | Veri yetersiz | Yüksek dikkat | 2 |
| 2 | ticagrelor | insufficient_pgx_rule_data | 59 | veri sınırlı / yorum dikkatli yapılmalı | Veri yetersiz | Yüksek dikkat | 2 |

## Aday Bazlı Açıklamalar

### 1. prasugrel

- **Gerekçe:** same_therapeutic_context (manual_demo)
- **Graph bağlamı:** belongs_to_class: P2Y12_inhibitor; has_ingredient: prasugrel; used_for: antiplatelet_therapy
- **MVP veri durumu:** `insufficient_pgx_rule_data`
- **MVP alternatif uygunluk ön skoru:** 59
- **Skor etiketi:** veri sınırlı / yorum dikkatli yapılmalı

**Aday özel PGx değerlendirmesi:**

- Veri yetersiz
- Aday özel risk düzeyi kodu: `unknown`

**Aday kaynak ilacın yerine konulduğunda toplam senaryo:**

- Toplam aktif bayrak sayısı: 2
- Genel senaryo dikkat düzeyi: Yüksek dikkat
- **Skor ceza nedenleri:** aday için phenotype_effect_rules.csv içinde gene-drug veri yok
- **Veri notu:** Bu aday ClinPGx chemical olarak çözülmüş ve MVP seed içinde tanınır hale gelmiştir; ancak mevcut MVP kapsamında usable phenotype-effect rule bulunmadığı için adayın farmakogenetik açıdan düşük dikkatli olduğu sonucu çıkarılamaz.

### 2. ticagrelor

- **Gerekçe:** same_therapeutic_context (manual_demo)
- **Graph bağlamı:** belongs_to_class: P2Y12_inhibitor; has_ingredient: ticagrelor; used_for: antiplatelet_therapy
- **MVP veri durumu:** `insufficient_pgx_rule_data`
- **MVP alternatif uygunluk ön skoru:** 59
- **Skor etiketi:** veri sınırlı / yorum dikkatli yapılmalı

**Aday özel PGx değerlendirmesi:**

- Veri yetersiz
- Aday özel risk düzeyi kodu: `unknown`

**Aday kaynak ilacın yerine konulduğunda toplam senaryo:**

- Toplam aktif bayrak sayısı: 2
- Genel senaryo dikkat düzeyi: Yüksek dikkat
- **Skor ceza nedenleri:** aday için phenotype_effect_rules.csv içinde gene-drug veri yok
- **Veri notu:** Bu aday ClinPGx chemical olarak çözülmüş ve MVP seed içinde tanınır hale gelmiştir; ancak mevcut MVP kapsamında usable phenotype-effect rule bulunmadığı için adayın farmakogenetik açıdan düşük dikkatli olduğu sonucu çıkarılamaz.

## Veri Kısıtları

- Graph seed klinik eşdeğerlik iddiası taşımaz; yalnızca demo bağlamı sağlar.
- Adaylar desteklenen MVP seed kapsamıyla sınırlı olarak değerlendirilir.
- Aday seed içinde yoksa veya phenotype rule yoksa düşük riskli olduğu sonucuna varılamaz.
- Skor klinik güvenlik değerlendirmesi değildir; yalnızca MVP alternatif uygunluk ön skoru olarak yorumlanmalıdır.
- Gemini veya başka bir LLM bu sıralamada karar verici olarak kullanılmamıştır.

## Sonuç

Prasugrel ve Ticagrelor aynı skorla listelenmiştir. Her iki aday da ClinPGx chemical olarak çözülmüş ve MVP seed içinde tanınır hale gelmiştir; ancak usable phenotype-effect rule bulunmadığı için PGx açısından değerlendirilememiştir. Bu sonuç tedavi önerisi değildir; yalnızca mevcut MVP seed kapsamındaki veri durumunu ve graph tabanlı aday bağlamını gösterir.
