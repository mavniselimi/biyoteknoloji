# CYP450 Farmakogenetik MVP Risk Ön Değerlendirme Raporu

**Genel sonuç:** Yüksek dikkat  
**Risk bayrağı sayısı:** 3

> Bu çıktı klinik karar, doz önerisi veya tedavi önerisi değildir. ClinPGx kaynaklı veriler ve sentetik CYP profilleri kullanılarak oluşturulmuş açıklanabilir farmakogenetik ön değerlendirme / MVP dikkat bayrağıdır.

## Profil

**Profil adı:** CYP2C19 poor metabolizer profili

| Gen | Fenotip |
|---|---|
| CYP2C19 | poor |
| CYP2D6 | normal |
| CYP2C9 | normal |
| CYP3A4 | normal |
| CYP1A2 | normal |

## İlaç Bazlı Bulgular

### clopidogrel

**Genel ilaç riski:** Yüksek dikkat

#### CYP2C19 bulgusu

- **Kullanıcı fenotipi:** poor
- **Risk düzeyi:** Yüksek dikkat
- **Etki yönü:** `decreased_activation`
- **Risk anlamı:** `reduced_response_attention`
- **Açıklama:** CYP2C19 aktivitesi düşük olduğunda clopidogrel aktif metabolite daha az dönüşebilir; bu durum antiplatelet yanıtın azalması açısından dikkat gerektirir.
- **Guideline kaynağı:** AHA, CPIC, DPWG
- **Guideline özeti:** The CPIC Dosing Guideline for clopidogrel recommends an alternative antiplatelet therapy for CYP2C19 poor or intermediate metabolizers (cardiovascular indications: prasugrel or ticagrelor if no contraindication; neurovascular indications: alternative P2Y12 inhibitor if clinically indicated and no contraindication.)
- **Kanıt tipi:** `high_guideline_supported`


### voriconazole

**Genel ilaç riski:** Yüksek dikkat

#### CYP2C19 bulgusu

- **Kullanıcı fenotipi:** poor
- **Risk düzeyi:** Yüksek dikkat
- **Etki yönü:** `decreased_clearance`
- **Risk anlamı:** `increased_exposure_attention`
- **Açıklama:** CYP2C19 aktivitesi düşük olduğunda voriconazole metabolizması azalabilir; maruziyet artışı açısından dikkat gerekir.
- **Guideline kaynağı:** AusNZ, CPIC, DPWG
- **Guideline özeti:** The CPIC dosing guideline for voriconazole recommends selecting an alternative agent that is not dependent on CYP2C19 metabolism in adults who are CYP2C19 ultrarapid metabolizers, rapid metabolizers or poor metabolizers. In pediatric patients, an alternative agent should be used in patients who are ultrarapid metabolizers or poor metabolizers. In pediatric rapid metabolizers, therapy should be initiated at recommended standard case dosing, then therapeutic dosing monitoring should be used to tit...
- **Kanıt tipi:** `high_guideline_supported`

- **CYP3A4:** Veri setinde gen–ilaç ilişkisi var, ancak bu profil fenotipi için aktif MVP uyarısı yok.

### codeine

**Genel ilaç riski:** Düşük / uyarı yok

- **CYP2D6:** Veri setinde gen–ilaç ilişkisi var, ancak bu profil fenotipi için aktif MVP uyarısı yok.

### warfarin

**Genel ilaç riski:** Düşük / uyarı yok

- **CYP2C9:** Veri setinde gen–ilaç ilişkisi var, ancak bu profil fenotipi için aktif MVP uyarısı yok.

### amitriptyline

**Genel ilaç riski:** Orta dikkat

- **CYP1A2:** Veri setinde gen–ilaç ilişkisi var, ancak bu profil fenotipi için aktif MVP uyarısı yok.
#### CYP2C19 bulgusu

- **Kullanıcı fenotipi:** poor
- **Risk düzeyi:** Orta dikkat
- **Etki yönü:** `altered_metabolism`
- **Risk anlamı:** `exposure_change_attention`
- **Açıklama:** CYP2C19 fenotipi amitriptyline metabolizmasını etkileyebilir; maruziyet değişimi açısından farmakogenetik dikkat bayrağı üretilebilir.
- **Guideline kaynağı:** CPIC, DPWG
- **Guideline özeti:** The CPIC Dosing Guideline update for amitriptyline recommends an alternative drug for CYP2D6 ultrarapid or poor metabolizers and CYP2C19 ultrarapid, rapid or poor metabolizers. If amitriptyline is warranted, consider a 50% dose reduction in CYP2D6 or CYP2C19 poor metabolizers. For CYP2D6 intermediate metabolizers, a 25% dose reduction should be considered. CPIC has updated the CYP2D6 genotype-phenotype translation in all supplemental files since the guideline was published.
- **Kanıt tipi:** `high_guideline_supported`

- **CYP2D6:** Veri setinde gen–ilaç ilişkisi var, ancak bu profil fenotipi için aktif MVP uyarısı yok.

## Aynı Gen Ekseninde Birden Fazla İlaç

- **CYP2C19:** Seçilen ilaçlardan clopidogrel, voriconazole, amitriptyline aynı CYP2C19 farmakogenetik ekseniyle ilişkilidir. Bu bulgu doğrudan ilaç-ilaç etkileşimi iddiası değildir; MVP içinde aynı gen üzerinden birden fazla dikkat noktasını görünür kılar.
- **CYP2D6:** Seçilen ilaçlardan codeine, amitriptyline aynı CYP2D6 farmakogenetik ekseniyle ilişkilidir. Bu bulgu doğrudan ilaç-ilaç etkileşimi iddiası değildir; MVP içinde aynı gen üzerinden birden fazla dikkat noktasını görünür kılar.

## Gemini'ye Gönderilecek Özet

Bu rapordaki yapılandırılmış JSON çıktısı `gemini_input.json` içinde kaydedildi.
Gemini sadece raporlama/sadeleştirme katmanı olarak kullanılmalı; risk hesaplama bu kural motorunda yapılmalıdır.
