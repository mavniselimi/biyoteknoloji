# MVP-1 Teknik Durum Raporu

## 1. Kısa Özet

Bu MVP, kullanıcının sentetik CYP fenotip profilini seçili ilaçlarla eşleştirerek ClinPGx kaynaklı gen-ilaç ilişkileri üzerinden açıklanabilir farmakogenetik dikkat bayrakları üretir. Sistem klinik karar, doz veya tedavi önerisi üretmez; yalnızca temizlenmiş MVP kural tablosu ve kural tabanlı risk motoru çıktısını Türkçe ön değerlendirme raporuna dönüştürür. Mevcut prototipte Gemini karar vermez, risk hesaplamaz ve yeni klinik yorum üretmez; risk düzeyi, fenotip eşleşmesi, aynı gen ekseni uyarısı ve evidence bilgisi `risk_engine.py` tarafından hesaplanır.

## 2. Mevcut Pipeline

Mevcut MVP-1 zinciri aşağıdaki şekilde çalışır:

```txt
ClinPGx veri çekme / ham kaynak katmanı
-> clean_mvp_seed_dataset.py
-> MVP seed dosyaları
-> risk_engine.py
-> risk_findings.csv / risk_report.md / risk_result_full.json / gemini_input.json
-> gemini_report_generator.py
-> gemini_report.md
```

**ClinPGx veri çekme / ham kaynak katmanı**

Girdi, ClinPGx API'den alınan Gene, Chemical, GuidelineAnnotation, VariantAnnotation ve pair endpoint sonuçlarıdır. Bu katman `clinpgx_probe_v2.py` ve `clinpgx_outputs_v2/` altındaki ham/ara çıktılarla temsil edilir. Burada amaç klinik yorum üretmek değil, gen sembolü ve ilaç adı üzerinden ClinPGx ID'lerini çözmek ve ilgili annotation kayıtlarını toplamaktır.

**`clean_mvp_seed_dataset.py`**

Girdi olarak `resolved_genes.json`, `resolved_chemicals.json`, `pair_probe_raw.json`, `mvp_candidate_drug_gene_edges.csv/.json` ve `variant_annotation_filtered_raw.json` gibi ClinPGx keşif çıktılarını bekler. Script, ham kayıtları MVP'nin okuyabileceği küçük ve kontrollü seed formatına dönüştürür. Karar verici değildir; veriyi normalize eder, exact gene-drug eşleşmelerini seçer, tekrarları azaltır ve demo için okunabilir kural satırları üretir.

**MVP seed dosyaları**

`clinpgx_mvp_seed/` altında yer alan `supported_genes.csv`, `supported_drugs.csv`, `drug_gene_guidelines.csv`, `phenotype_effect_rules.csv`, `mvp_demo_profiles.json` ve `mvp_seed_summary.json` risk motorunun temel veri katmanıdır. Bu dosyalar ham ClinPGx çıktısının doğrudan kullanılması yerine kontrollü, jüriye anlatılabilir ve sınırlı bir MVP kapsamı sağlar.

**`risk_engine.py`**

Seed dosyalarını, sentetik profil fenotiplerini ve seçili ilaç listesini okur. Her ilaç için ilgili gene-drug kuralını bulur, kullanıcının sentetik fenotipiyle rule fenotipini eşleştirir ve eşleşme varsa farmakogenetik dikkat bayrağı üretir. Klinik karar vermez; doz veya tedavi değişikliği önermez.

**Risk çıktıları**

`clinpgx_mvp_seed/risk_outputs/` altında `risk_findings.csv`, `risk_report.md`, `risk_result_full.json` ve `gemini_input.json` üretilmiştir. CSV yapılandırılmış bulguları, Markdown okunabilir teknik raporu, full JSON ayrıntılı sonucu, Gemini input ise raporlama katmanına gönderilecek kompakt sonucu içerir.

**`gemini_report_generator.py`**

`gemini_input.json` dosyasını alır. Risk hesaplamaz, fenotip eşleştirme yapmaz, yeni ilaç/gen bilgisi eklemez. Gemini API key varsa Gemini ile, yoksa deterministic fallback ile Türkçe okunabilir ön değerlendirme raporu üretir. Gemini raporlama katmanıdır; risk motorunun yerine geçmez.

## 3. ClinPGx'ten Hangi Veri Tipleri Kullanıldı?

Repo incelemesinde ClinPGx API keşif katmanında aşağıdaki veri tipleri görülmektedir:

| Veri tipi | MVP-1 durumu |
|---|---|
| Gene | Aktif kullanıldı. Gen sembolleri ClinPGx Gene objelerine ve PA ID'lerine çözüldü. |
| Chemical / Drug | Aktif kullanıldı. İlaç adları ClinPGx Chemical objelerine ve PA ID'lerine çözüldü. |
| GuidelineAnnotation | Aktif kullanıldı. `drug_gene_guidelines.csv` içinde 30 guideline satırı ve 11 gene-drug guideline çifti yer alıyor. |
| VariantAnnotation | Aktif/sınırlı kullanıldı. `phenotype_effect_rules.csv` içinde fenotip-etki kuralı üretiminde kullanıldı; karmaşık/tekrarlı kayıtlar normalize edildi. |
| Label / DrugLabel | Keşif çıktılarında görüldü. `pair_annotation_rows.csv` içinde `label` ve `DrugLabel` result type satırları var; ancak MVP-1 ana risk motoruna tetikleyici olarak bağlanmadı. |
| Pathway | `clinpgx_probe_v2.py` pair result type denemelerinde var; mevcut CSV çıktılarında ana seed/risk motoru girdisi olarak doğrulanmadı. |
| SummaryAnnotation | `clinpgx_probe_v2.py` pair result type denemelerinde var; mevcut seed/risk motoru içinde aktif ana katman olarak kullanılmadı. |
| Pair report / gene-drug pair ilişkileri | Aktif kullanıldı. `/report/pair` endpointi guideline, variant ve label gibi ilişkileri keşfetmek için denendi; MVP-1'de guideline ve variant ilişkileri ana veri katmanına dönüştürüldü. |

MVP-1'de temel olarak gene objeleri, chemical objeleri ve gene-drug guideline/variant annotation ilişkileri kullanıldı. Label, pathway ve summary katmanları veri keşfi açısından görülmüş olsa da ana risk motoruna klinik tetikleyici olarak sokulmadı veya repo içinde bu kullanım doğrulanamadı.

## 4. Desteklenen Genler ve İlaçlar

`clinpgx_mvp_seed/supported_genes.csv` içinde 5 desteklenen gen vardır:

| Gen | ClinPGx ID | MVP önceliği | MVP rolü |
|---|---:|---|---|
| CYP1A2 | PA27093 | low | supporting |
| CYP2C19 | PA124 | high | core |
| CYP2C9 | PA126 | high | core |
| CYP2D6 | PA128 | high | core |
| CYP3A4 | PA130 | medium | supporting |

`clinpgx_mvp_seed/supported_drugs.csv` içinde 11 ilaç/chemical kaydı vardır:

| İlaç | ClinPGx ID | Tip | Davranış ipucu | MVP durumu |
|---|---:|---|---|---|
| amitriptyline | PA448385 | Drug | active_drug_or_general_drug | yes |
| citalopram | PA449015 | Drug | active_drug_or_general_drug | yes |
| clopidogrel | PA449053 | Prodrug | prodrug_activation | yes |
| codeine | PA449088 | Prodrug | prodrug_activation | yes |
| fluoxetine | PA449673 | Drug | active_drug_or_general_drug | candidate |
| omeprazole | PA450704 | Drug | active_drug_or_general_drug | candidate |
| paroxetine | PA450801 | Drug | active_drug_or_general_drug | candidate |
| sertraline | PA451333 | Drug | active_drug_or_general_drug | yes |
| tamoxifen | PA451581 | Drug | active_drug_or_general_drug | yes |
| voriconazole | PA10233 | Drug | active_drug_or_general_drug | yes |
| warfarin | PA451906 | Drug | active_drug_or_general_drug | yes |

`mvp_seed_summary.json` içinde desteklenen gen sayısı 5, desteklenen ilaç sayısı 11, guideline satır sayısı 30, phenotype effect rule satır sayısı 3084, guideline gene-drug pair sayısı 11 ve usable effect gene-drug pair sayısı 11 olarak kayıtlıdır.

## 5. Neden Gen ve İlaç Çiftlerini Manuel Vermek Zorunda Kaldık?

ClinPGx doğrudan "bana tüm CYP450-ilaç risklerini getir" şeklinde çalışan tek adımlı bir risk motoru değildir. Repo içindeki `clinpgx_probe_v2.py` akışı önce gen sembolünü Gene objesine, ilaç adını Chemical objesine çözer; sonra bu ID'ler üzerinden guideline annotation, pair report ve variant annotation ilişkilerini sorgular.

Bu nedenle MVP kapsamında desteklenecek gen ve ilaç kapsamı manuel veya yarı-manuel olarak belirlenmiştir:

1. Önce gen sembolü ClinPGx Gene ID'ye çözülür.
2. Önce ilaç adı ClinPGx Chemical ID'ye çözülür.
3. Sonra gene ID + chemical ID üzerinden guideline / annotation ilişkileri aranır.
4. Pair endpointinde farklı result type değerleri denenir.
5. Gelen kayıtlar exact gene-drug eşleşme, kanıt tipi, tekrar durumu ve MVP anlaşılabilirliği açısından filtrelenir.

Her ilişki aynı kanıt gücünde değildir. Bazı kayıtlar guideline destekli, bazıları variant annotation düzeyinde, bazıları label veya keşif düzeyindedir. Bu yüzden MVP-1 için kontrollü, küçük, kaynaklı ve jüriye anlatılabilir bir seed veri seti kurulmuştur. API veri sağlar; farmakogenetik dikkat bayrağı yorumunu bizim kural motorumuz yapar.

## 6. MVP Seed Nasıl Üretildi?

Seed üretimi `clean_mvp_seed_dataset.py` tarafından yapılır. Script klinik karar, doz veya tedavi önerisi üretmez; ClinPGx V2 probe çıktılarından temiz MVP veri katmanı oluşturur.

**`supported_genes.csv`**

Desteklenen genleri, ClinPGx ID'lerini, gen adlarını, CPIC/PharmVar alanlarını, VIP tier bilgisini, MVP önceliğini ve kısa notları içerir. `risk_engine.py` bu dosyayı gen metadata'sı ve desteklenen kapsam için kullanır.

Gerçek kolonlar:

```txt
gene, gene_id, name, cpicGene, pharmVarGene, alleleFile, alleleFunctionSource, alleleType, vipTier, mvp_priority, mvp_role, notes
```

**`supported_drugs.csv`**

Desteklenen ilaçları/chemical kayıtlarını, ClinPGx ID'lerini, tiplerini, prodrug/aktif ilaç davranış ipucunu ve MVP destek durumunu içerir. Risk motoru seçilen ilaç listesini bu dosyayla doğrular.

Gerçek kolonlar:

```txt
drug, drug_id, canonical_name, types, drug_behavior_hint, pediatric, mvp_supported, smiles
```

**`drug_gene_guidelines.csv`**

GuidelineAnnotation kaynaklı gene-drug ilişkilerini içerir. Bu dosya guideline kaynağı, annotation ID, summary, PMID/DOI ve usable_for_mvp gibi alanlarla risk bulgusunun kaynak bilgisini besler. Dosyada 30 guideline satırı ve 11 guideline gene-drug çifti vardır. Kaynaklar arasında CPIC, DPWG, RNPGx, AHA, AusNZ ve CPNDS bulunur.

Gerçek kolonlar:

```txt
pair_key, gene, gene_id, drug, drug_id, annotation_id, objCls, name, source, source_container, recommendation, dosingInformation, alternateDrugAvailable, hasTestingInfo, pediatric, otherPrescribingGuidance, summary, text_excerpt, literature_titles, pmids, dois, years, evidence_tier, usable_for_mvp
```

**`phenotype_effect_rules.csv`**

Ham ClinPGx cümlelerini veya guideline/variant annotation bilgilerini risk motorunun okuyabileceği normalize edilmiş forma dönüştürür. Bu dosya fenotip grubu, etki yönü, risk anlamı, MVP risk düzeyi, evidence gücü ve açıklama alanlarını taşır. Dosyada 3084 kural satırı vardır; 11 usable gene-drug effect çifti raporlanmıştır.

Gerçek kolonlar:

```txt
gene, gene_id, drug, drug_id, phenotype_or_genotype, normalized_phenotype_group, drug_behavior_hint, effect_direction, risk_meaning, demo_risk_level, effect_polarity, phenotype_category, significance, score, evidence_strength, source_container, annotation_id, objCls, evidence_sentence, plain_language_mvp, literature_titles, pmids, dois, years, usable_for_mvp
```

**`mvp_demo_profiles.json`**

Sentetik demo fenotip profillerini içerir. Mevcut profiller: `P1_normal`, `P2_cyp2c19_poor`, `P3_cyp2d6_poor`, `P4_cyp2d6_ultrarapid`, `P5_cyp2c9_decreased`, `P6_mixed_high_attention`. Gerçek hasta verisi değildir.

**`mvp_seed_summary.json`**

Seed üretiminin özetini, sayıları, guideline/effect pair listelerini, risk count ve evidence count dağılımlarını içerir. Bu dosya MVP kapsamının hızlı denetlenmesini sağlar.

## 7. Temizlik ve Filtreleme Kararları

MVP-1'de veri temizliği güvenlik ve açıklanabilirlik için bilinçli olarak dar tutulmuştur.

Exact gene-drug eşleşmeyen satırlar elendi; çünkü ClinPGx annotation kayıtları bazen birden fazla ilişkili gene veya chemical taşıyabilir. `clean_mvp_seed_dataset.py` içindeki exact pair kontrolü, ilgili annotation'ın hem hedef gene hem de hedef drug ile gerçekten ilişkili olduğunu doğrular. Böylece yanlış pozitif gene-drug dikkat bayrağı üretme riski azaltılır.

Duplicate annotation kayıtları temizlendi; çünkü aynı annotation hem `data/guidelineAnnotation` hem de `report/pair` gibi farklı kanallardan veya `variantAnnotation` / `VariantAnnotation` gibi farklı result type yazımlarıyla gelebilir. Seed üretici ve risk motoru aynı annotation ID, gene, drug, fenotip grubu, etki yönü ve risk anlamı üzerinden tekrarları azaltır.

`significance=no` gibi zayıf kayıtlar ana risk tetikleyici yapılmadı. Kodda `significance=no` olan ve guideline desteği olmayan kayıtlar effect rule'a alınmaz. Bu tercih, sadece keşifsel veya negatif kayıtlarla dikkat bayrağı üretmeyi engeller.

Normal metabolizer ifadeleri risk tetikleyici yapılmadı. `risk_engine.py` içinde `PROFILE_MATCH_GROUPS` tanımında normal profil için eşleşme kümesi boş bırakılmıştır. Bunun gerekçesi kod yorumunda açıkça yer alır: ClinPGx ham verisinde "normal metabolizer" çoğu zaman karşılaştırma grubu olarak geçebilir. Bu ifade normal fenotipin riskli olduğu anlamına gelmeyebilir. Bu yüzden MVP'de normal fenotip için otomatik risk bayrağı üretmekten kaçınıldı.

Pathway, label ve summaryAnnotation katmanları MVP-1 ana motoruna alınmadı. `clinpgx_probe_v2.py` bu result type değerlerini keşif amacıyla denemiştir; mevcut seed dosyalarında ana risk tetikleyici olarak guideline ve variant kaynaklı normalize effect rule'lar kullanılmaktadır. Label satırları ara keşif CSV'lerinde görünse de risk motorunun ana eşleştirme yapısına bağlanmamıştır. Pathway ve SummaryAnnotation için mevcut repo çıktılarında ana seed/risk motoru kullanımı doğrulanamadı.

Gerçek allele/diplotype -> fenotip dönüşümü bu MVP'de yapılmadı. Risk motoru sentetik fenotip profili alır; VCF, star allele, diplotype veya laboratuvar sonucu parse etmez. Diplotype/haplotype düzeyindeki ham literatür satırları otomatik profil eşleştirme için ana tetikleyici yapılmaz; evidence olarak kalır.

Bu kararların ortak güvenlik mantığı şudur: MVP-1, klinik sonuç üretmeye değil, kaynaklı ve açıklanabilir farmakogenetik dikkat noktalarını kontrollü şekilde göstermeye odaklanır.

## 8. Risk Motoru Nasıl Çalışıyor?

`risk_engine.py`, ClinPGx MVP seed dosyalarını kullanarak sentetik CYP profili ve seçilen ilaçlar için farmakogenetik dikkat bayrağı üretir.

Çalışma akışı:

1. `supported_genes.csv`, `supported_drugs.csv`, `drug_gene_guidelines.csv`, `phenotype_effect_rules.csv` ve `mvp_demo_profiles.json` dosyalarını yükler.
2. Demo/sentetik profili `profile-id` veya özel JSON üzerinden okur.
3. Seçilen ilaç listesini komut satırı argümanından okur.
4. Her ilaç için `phenotype_effect_rules.csv` içinde ilgili gene-drug kurallarını bulur.
5. Kullanıcının sentetik fenotipi ile rule içindeki `normalized_phenotype_group` alanını eşleştirir.
6. Eşleşme varsa `risk_flag` statülü farmakogenetik dikkat bayrağı üretir.
7. Guideline/evidence bilgisini `drug_gene_guidelines.csv` ve rule evidence alanlarından ekler.
8. Aynı gen ekseninde birden fazla seçili ilaç varsa `same_gene_attention` notu üretir.
9. CSV, Markdown, JSON ve Gemini input çıktıları üretir.

Risk düzeyleri klinik tanı değil, MVP dikkat düzeyi olarak ele alınmalıdır:

| Kod | Türkçe etiket |
|---|---|
| none | Düşük / uyarı yok |
| low | Düşük dikkat |
| medium | Orta dikkat |
| high | Yüksek dikkat |

`same_gene_attention`, doğrudan ilaç-ilaç etkileşimi iddiası değildir. Aynı CYP farmakogenetik ekseni üzerinden birden fazla seçili ilaç bulunduğunu görünür hale getirir.

## 9. Örnek Çalışma Sonuçları

Mevcut örnek çıktı dosyaları `clinpgx_mvp_seed/risk_outputs/` altında bulunmuştur.

**Kullanılan profil**

Profil adı: `CYP2C19 poor metabolizer profili`

Fenotipler:

| Gen | Fenotip |
|---|---|
| CYP2C19 | poor |
| CYP2D6 | normal |
| CYP2C9 | normal |
| CYP3A4 | normal |
| CYP1A2 | normal |

**Seçilen ilaçlar**

```txt
clopidogrel, voriconazole, codeine, warfarin, amitriptyline
```

**Genel sonuç**

Genel dikkat düzeyi `high / Yüksek dikkat` olarak üretilmiştir. Aktif risk/dikkat bayrağı sayısı 3'tür.

**Dikkat bayrağı oluşan ilaçlar**

| İlaç | İlgili gen | Fenotip | Dikkat düzeyi | Etki yönü | Risk anlamı |
|---|---|---|---|---|---|
| clopidogrel | CYP2C19 | poor | high / Yüksek dikkat | decreased_activation | reduced_response_attention |
| voriconazole | CYP2C19 | poor | high / Yüksek dikkat | decreased_clearance | increased_exposure_attention |
| amitriptyline | CYP2C19 | poor | medium / Orta dikkat | altered_metabolism | exposure_change_attention |

Clopidogrel için MVP açıklaması, CYP2C19 aktivitesi düşük olduğunda aktif metabolite dönüşümün azalabileceği ve bunun antiplatelet yanıt açısından dikkat gerektirebileceği şeklindedir. Bu bir tedavi önerisi değildir; kural motorunun ürettiği farmakogenetik dikkat bayrağıdır.

Voriconazole için MVP açıklaması, CYP2C19 aktivitesi düşük olduğunda metabolizmanın azalabileceği ve maruziyet artışı açısından dikkat gerekebileceği şeklindedir. Bu bir doz önerisi değildir.

Amitriptyline için MVP açıklaması, CYP2C19 fenotipinin metabolizma/maruziyet değişimiyle ilişkili olabileceği ve bu nedenle orta düzey farmakogenetik dikkat bayrağı üretildiği şeklindedir.

**Aktif uyarı oluşmayan veya profil eşleşmesi olmayan ilaçlar**

Codeine için CYP2D6 ilişkisi veri setinde vardır; ancak seçili örnek profilde CYP2D6 fenotipi `normal` olduğu için aktif MVP uyarısı üretilmemiştir.

Warfarin için CYP2C9 ilişkisi veri setinde vardır; ancak seçili örnek profilde CYP2C9 fenotipi `normal` olduğu için aktif MVP uyarısı üretilmemiştir.

Voriconazole için CYP3A4 ilişkisi veri setinde vardır; ancak seçili örnek profilde CYP3A4 fenotipi `normal` olduğu için aktif MVP uyarısı üretilmemiştir.

Amitriptyline için CYP1A2 ve CYP2D6 ilişkileri veri setinde görünür; ancak seçili örnek profilde ilgili fenotipler aktif MVP uyarısı üretmemiştir.

**Aynı gen ekseni dikkat notları**

Mevcut örnekte CYP2C19 ekseninde clopidogrel, voriconazole ve amitriptyline birlikte görünür. CYP2D6 ekseninde codeine ve amitriptyline birlikte görünür. Bu notlar doğrudan ilaç-ilaç etkileşimi iddiası değildir; aynı farmakogenetik eksende birden fazla seçili ilaç bulunduğunu gösterir.

## 10. Gemini Raporlayıcı Ne Yapıyor?

`gemini_report_generator.py`, `risk_engine.py` tarafından üretilen `gemini_input.json` dosyasını alır ve Türkçe, klinik olmayan bir ön değerlendirme raporu üretir.

Raporlayıcının rolü:

1. Girdi olarak `gemini_input.json` alır.
2. Risk hesaplamaz.
3. Fenotip-rule eşleştirmesi yapmaz.
4. Risk motoru çıktısını kompakt hale getirir.
5. Gemini API key varsa Gemini API ile rapor üretir.
6. API key yoksa veya API çağrısı başarısız olursa deterministic fallback rapor üretir.
7. Güvenlik uyarısını rapora ekler.
8. Prompt guardrail ile yeni tıbbi bilgi, yeni ilaç, yeni gen, yeni doz veya tedavi önerisi eklenmesini engellemeye çalışır.

Gemini raporlama katmanıdır; risk motorunun yerine geçmez.

Mevcut `final_report/gemini_report_status.json` dosyasına göre son rapor üretiminde `gemini-2.5-flash` modeli kullanılmış, `used_api=true` ve `fallback_used=false` olarak kaydedilmiştir. Bu bilgi mevcut dosya durumuna aittir.

## 11. Güvenlik ve Sınırlar

Bu MVP-1 prototipi gerçek hasta verisi kullanmaz. Mevcut örnekler sentetik CYP fenotip profilleriyle çalışır. Gerçek genetik test sonucu yorumlama, allele parsing, diplotype parsing, VCF yorumlama veya laboratuvar raporu değerlendirmesi yapılmaz.

Bu sistem klinik karar vermez, doz önermez, "bu ilacı kullan", "bu ilacı bırak" veya "bu ilacı değiştir" şeklinde yönlendirici çıktı üretmemelidir. Çıktılar, hekim değerlendirmesine destek olabilecek açıklanabilir farmakogenetik ön değerlendirme niteliğindedir.

Kapsam seed veri setindeki gen ve ilaçlarla sınırlıdır. MVP-1 gerçek klinik doğrulama iddiası taşımaz. Etik kurul, KVKK ve klinik validasyon süreçleri olmadan gerçek hasta verisi işlenmemelidir.

Bu sistemin çıktıları klinik karar, doz önerisi veya tedavi değişikliği önerisi değildir. Çıktılar yalnızca ClinPGx kaynaklı veriler ve sentetik CYP profilleri üzerinden oluşturulmuş açıklanabilir farmakogenetik ön değerlendirme / MVP dikkat bayrağı niteliğindedir.

## 12. MVP-1'in Başardığı Şey

MVP-1, aşağıdaki teknik noktaları çalışır hale getirmiştir:

1. ClinPGx'ten kaynaklı gen ve ilaç objeleri çekilebildi.
2. Gen sembolü -> ClinPGx Gene ID ve ilaç adı -> ClinPGx Chemical ID çözümü yapılabildi.
3. Gen-ilaç ilişkileri guideline/annotation düzeyinde alınabildi.
4. Ham veri MVP formatına temizlenebildi.
5. Fenotip-ilaç-gen eşleşmesiyle farmakogenetik dikkat bayrağı üretilebildi.
6. Prodrug gibi özel durumlar için etki yönü ayrımı yapılabildi.
7. Aynı gen eksenindeki çoklu ilaç dikkat noktaları görünür hale getirilebildi.
8. Gemini raporu karar verici değil, açıklayıcı katman olarak bağlandı.
9. CSV/JSON/Markdown çıktı zinciri kuruldu.

## 13. MVP-1'in Eksikleri

MVP-1 kapsamı bilinçli olarak sınırlıdır:

1. Veri kapsamı sınırlıdır.
2. Gene/drug çiftleri manuel veya yarı-manuel seçilmiştir.
3. Gerçek VCF/allel/diplotype -> phenotype dönüşümü yoktur.
4. Label, pathway, target protein, indication ve therapeutic class graph yapısı henüz ana sisteme bağlı değildir.
5. Alternatif ilaç aday sıralaması henüz yoktur.
6. Doz önerisi yoktur ve MVP kapsamında olmamalıdır; kaynakta doz/alternatif bilgisi varsa yalnızca kaynak metni olarak nötr biçimde gösterilebilir.
7. Klinik doğrulama yoktur.
8. Gerçek hasta verisi yoktur.
9. Etik kurul/KVKK süreçleri olmadan gerçek veri işlenmemelidir.

## 14. MVP-2'ye Geçiş: Graph Tabanlı Alternatif Aday Mantığı

MVP-2'nin amacı ilaç alternatifi reçete etmek değildir. Amaç, riskli ilaçtan aynı terapötik bağlam veya ilaç sınıfı içindeki adayları bulup farmakogenetik açıdan daha düşük dikkat bayrağı taşıyanları ön sıralamaktır.

MVP-2 için önerilen graph node tipleri:

```txt
Drug/Product
ActiveIngredient
TherapeuticClass
Indication/UseCase
Gene
Enzyme
Phenotype
PGxGuideline
RiskFinding
AdverseEffect/Warning
```

MVP-2 için önerilen edge tipleri:

```txt
Drug --has_ingredient--> ActiveIngredient
Drug --belongs_to_class--> TherapeuticClass
Drug --used_for--> Indication
ActiveIngredient --substrate_of--> Enzyme
ActiveIngredient --inhibits--> Enzyme
ActiveIngredient --induces--> Enzyme
Gene --encodes/related_to--> Enzyme
Phenotype --affects--> Enzyme
PGxGuideline --supports--> Gene-Drug rule
Drug --has_warning/adverse_reaction--> Label section
```

MVP-2 için önerilen dosyalar:

```txt
drug_graph_edges.csv
candidate_alternatives.csv
alternative_ranker.py
alternative_report.md
```

Alternatif aday çıktısında şu dil kullanılmalıdır:

```txt
Bu adaylar tedavi önerisi değildir. Aynı terapötik bağlam veya ilaç sınıfı üzerinden farmakogenetik risk açısından ön sıralama amacıyla gösterilmiştir.
```

Bu yapı, mevcut `risk_engine.py` çıktısını yeniden kullanabilir: aday ilaçlar aynı sentetik profil ile tekrar taranır, oluşan dikkat bayrakları karşılaştırılır ve sonuçlar "düşük/orta/yüksek dikkat" gibi açıklanabilir sınıflarla raporlanır.

## 15. Önerilen Sonraki Teknik Adımlar

1. `drug_graph_edges.csv` seed dosyasını oluştur.
2. `candidate_alternatives.csv` manuel demo alternatiflerini ekle.
3. `alternative_ranker.py` yaz.
4. Adayları mevcut `risk_engine.py` ile yeniden tarat.
5. Adayları "düşük/orta/yüksek dikkat" olarak sırala.
6. Gemini'ye sadece hesaplanmış aday karşılaştırma sonucunu raporlat.
7. Doz önerisini yasaklı tut; kaynakta varsa yalnızca kaynak metni olarak göster.

## 16. Sonuç

MVP-1, projenin temel iddiasını çalışır hale getirmiştir: genetik metabolizma profili ile ilaç-gen ilişkileri birleştirilerek açıklanabilir farmakogenetik dikkat bayrakları üretilebilmektedir. Bundan sonraki mantıklı genişleme, graph tabanlı alternatif aday bulma ve adayları PGx/CYP dikkat durumuna göre ön sıralamadır. Ancak sistem klinik karar veya doz önerisi üretmemeye devam etmelidir.

## İncelenen Dosyalar

Kod dosyaları:

- `clean_mvp_seed_dataset.py`
- `risk_engine.py`
- `gemini_report_generator.py`
- `clinpgx_probe_v2.py`

MVP seed dosyaları:

- `clinpgx_mvp_seed/supported_genes.csv`
- `clinpgx_mvp_seed/supported_drugs.csv`
- `clinpgx_mvp_seed/drug_gene_guidelines.csv`
- `clinpgx_mvp_seed/phenotype_effect_rules.csv`
- `clinpgx_mvp_seed/mvp_demo_profiles.json`
- `clinpgx_mvp_seed/mvp_seed_summary.json`

Risk motoru çıktıları:

- `clinpgx_mvp_seed/risk_outputs/risk_findings.csv`
- `clinpgx_mvp_seed/risk_outputs/risk_report.md`
- `clinpgx_mvp_seed/risk_outputs/risk_result_full.json`
- `clinpgx_mvp_seed/risk_outputs/gemini_input.json`

Gemini rapor çıktıları:

- `final_report/gemini_report.md`
- `final_report/gemini_report_payload.json`
- `final_report/gemini_report_status.json`
- `final_report/gemini_prompt.txt`

ClinPGx keşif/ara çıktıları:

- `clinpgx_outputs_v2/resolved_genes.csv`
- `clinpgx_outputs_v2/resolved_genes.json`
- `clinpgx_outputs_v2/resolved_chemicals.csv`
- `clinpgx_outputs_v2/resolved_chemicals.json`
- `clinpgx_outputs_v2/guideline_annotation_rows.csv`
- `clinpgx_outputs_v2/variant_annotation_filtered_rows.csv`
- `clinpgx_outputs_v2/variant_annotation_filtered_raw.json`
- `clinpgx_outputs_v2/pair_annotation_rows.csv`
- `clinpgx_outputs_v2/pair_probe_raw.json`
- `clinpgx_outputs_v2/mvp_candidate_drug_gene_edges.csv`
- `clinpgx_outputs_v2/mvp_candidate_drug_gene_edges.json`
- `clinpgx_outputs_v2/openapi_snapshot.json`

## Bulunamayan Beklenen Dosyalar

Kullanıcının özellikle aradığı beklenen dosyaların tamamı repo içinde bulundu. Bazıları proje kökünde değil, aşağıdaki alt klasörlerde yer almaktadır:

- `clinpgx_mvp_seed/`
- `clinpgx_mvp_seed/risk_outputs/`
- `final_report/`

