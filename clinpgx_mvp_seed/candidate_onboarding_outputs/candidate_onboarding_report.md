# MVP-2 Candidate Onboarding Raporu

## Güvenlik Notu

Bu rapor klinik karar, doz önerisi veya tedavi değişikliği önerisi değildir. Aday ilaçlar yalnızca MVP veri setinde değerlendirilebilir hale getirme amacıyla incelenmiştir.

Adayın ClinPGx chemical olarak çözülmesi, o adayın farmakogenetik açıdan düşük riskli olduğu anlamına gelmez. Yalnızca MVP veri setinde değerlendirilebilir hale getirme adımıdır.

## Aday İlaç Listesi

- nortriptyline
- pantoprazole
- prasugrel
- ticagrelor

## ClinPGx Chemical Çözüm Durumu

| Aday | Mevcut seed | Resolve durumu | Chemical ID | Not |
|---|---|---|---|---|
| nortriptyline | False | resolved_via_api | PA450657 |  |
| pantoprazole | False | resolved_via_api | PA450774 |  |
| prasugrel | False | resolved_via_api | PA154410481 |  |
| ticagrelor | False | resolved_via_api | PA165374673 |  |

## Gene-Drug Annotation Durumu

- GuidelineAnnotation satırı: 6
- VariantAnnotation satırı: 0
- Label satırı: 0

- **nortriptyline:** Bu aday ClinPGx chemical olarak çözüldü; ancak mevcut MVP seed kapsamında farmakogenetik phenotype rule bulunamadı.
- **pantoprazole:** Bu aday ClinPGx chemical olarak çözüldü; ancak mevcut MVP seed kapsamında farmakogenetik phenotype rule bulunamadı.
- **prasugrel:** Bu aday ClinPGx chemical olarak çözüldü; ancak mevcut MVP seed kapsamında farmakogenetik phenotype rule bulunamadı.
- **ticagrelor:** Bu aday ClinPGx chemical olarak çözüldü; ancak mevcut MVP seed kapsamında farmakogenetik phenotype rule bulunamadı.

## Seed Extension Özeti

- `candidate_supported_drugs_extension.csv`: 4 satır
- `candidate_drug_gene_guidelines_extension.csv`: 6 satır
- `candidate_phenotype_effect_rules_extension.csv`: 0 satır

## Merge Durumu

- clinpgx_mvp_seed/supported_drugs.csv: added=4, skipped_duplicates=0, backup=clinpgx_mvp_seed/supported_drugs.csv.bak
- clinpgx_mvp_seed/drug_gene_guidelines.csv: added=6, skipped_duplicates=0, backup=clinpgx_mvp_seed/drug_gene_guidelines.csv.bak
- clinpgx_mvp_seed/phenotype_effect_rules.csv: added=0, skipped_duplicates=0, backup=clinpgx_mvp_seed/phenotype_effect_rules.csv.bak

### Alternative Ranker Entegrasyon Kontrolü

- Komut dönüş kodu: 0
- prasugrel: insufficient_pgx_rule_data (score=59, risk_level=unknown)
- ticagrelor: insufficient_pgx_rule_data (score=59, risk_level=unknown)

## Veri Kısıtları

- Candidate onboarding otomatik klinik öneri üretmez.
- ClinPGx chemical çözümü PGx rule bulunduğu anlamına gelmez.
- Label kayıtları ayrı tutulur; risk rule tetikleyicisi yapılmaz.
- Normal metabolizer karşılaştırmaları risk tetikleyicisi yapılmaz.
- Otomatik oluşturulan effect rule extension satırları `usable_for_mvp=no` olarak tutulur ve manuel inceleme gerektirir.

## Sonraki Adım

Merge sonrası alternative ranker çıktısındaki aday statüleri kontrol edilmelidir. Usable rule olmayan adaylar `insufficient_pgx_rule_data` olarak kalmalıdır.
