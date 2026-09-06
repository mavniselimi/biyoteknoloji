"""Controlled UI text. Every string a page can display, written down once.

Two sources, and the split matters.

**Governed codes reuse WP-15's tables.** ``HIGH``, ``PARTIAL``,
``NOT_ASSESSED``, ``SOME_AXES_NOT_COVERED`` and the rest already have reviewed
Turkish and English labels in :mod:`pgx.reporting.templates`, written for the
report renderer. This module re-exports them rather than restating them. A
screen and a report describing the same assessment must not be able to
disagree about what ``NOT_ASSESSED`` means, and the cheapest way to guarantee
that is for there to be only one sentence.

**Chrome text is defined here.** Navigation, headings, table captions, button
text, empty states and accessibility strings belong to the interface and to
nothing else. They are a fixed table, not f-strings: every one of them is
scanned by the prohibited-claim scanner in the test suite, which is only
meaningful if the set of strings that can reach a page is finite and known.

No function in this module accepts caller text. :func:`ui` refuses an unknown
key rather than returning it, for the same reason
:func:`pgx.reporting.templates.label` refuses an unknown code: a page showing
``nav.validation`` where a word belongs looks like a layout bug rather than a
missing translation, and someone will ship it.
"""

from __future__ import annotations

from typing import Dict, Mapping, Tuple

from pgx.reporting.templates import (ATTENTION_LABELS, COVERAGE_LABELS,
                                     COVERAGE_REASON_LABELS, FIELD_LABELS,
                                     INPUT_KIND_LABELS, MODE_LABELS,
                                     OBSERVATION_STATE_LABELS, label,
                                     require_locale)

__all__ = [
    "ATTENTION_LABELS",
    "LabelNotDefinedError",
    "COVERAGE_LABELS",
    "COVERAGE_REASON_LABELS",
    "FIELD_LABELS",
    "INPUT_KIND_LABELS",
    "MODE_LABELS",
    "OBSERVATION_STATE_LABELS",
    "UI_TEXT",
    "attention_label",
    "coverage_label",
    "coverage_reason_label",
    "field_label",
    "observation_state_label",
    "ui",
    "ui_table",
]


class LabelNotDefinedError(KeyError):
    """A page asked for text nobody wrote."""


#: Every interface string, in both locales.
#:
#: Deliberately flat and deliberately verbose. A nested structure would invite
#: building keys at runtime, and a key built at runtime is a key the
#: prohibited-claim test cannot enumerate.
UI_TEXT: Mapping[str, Mapping[str, str]] = {
    # -- application chrome ----------------------------------------------
    "app.title": {"tr": "PGx Platform V2", "en": "PGx Platform V2"},
    "app.subtitle": {
        "tr": "Araştırma/prototip gösterim arayüzü",
        "en": "Research/prototype demonstration interface"},
    "app.skip_to_content": {"tr": "İçeriğe geç",
                            "en": "Skip to content"},
    "app.main_navigation": {"tr": "Ana gezinme", "en": "Main navigation"},
    "app.current_page": {"tr": "Bulunduğunuz sayfa",
                         "en": "Current page"},
    "app.footer_note": {
        "tr": "Bu arayüz sentetik ve geliştirme amaçlı girdiler üzerinde "
              "çalışır. Gerçek hasta verisi kabul etmez.",
        "en": "This interface operates on synthetic and development-only "
              "inputs. It accepts no real patient data."},
    "app.warning_heading": {
        "tr": "Araştırma/prototip kullanım uyarısı",
        "en": "Research/prototype use notice"},
    "app.environment": {"tr": "Ortam", "en": "Environment"},
    "app.mode": {"tr": "Çalışma kipi", "en": "Operating mode"},
    "app.request_id": {"tr": "İstek kimliği", "en": "Request identifier"},
    "app.request_id_note": {
        "tr": "Destek ve denetim için kullanılır. Değerlendirme verisinin "
              "parçası değildir ve hiçbir özete karışmaz.",
        "en": "Used for support and audit. It is not part of the assessment "
              "data and enters no hash."},
    "app.unknown": {"tr": "Bilinmiyor", "en": "Unknown"},
    "app.none_recorded": {"tr": "Kayıt yok", "en": "None recorded"},
    "app.language": {"tr": "Dil", "en": "Language"},

    # -- navigation -------------------------------------------------------
    "nav.home": {"tr": "Başlangıç", "en": "Home"},
    "nav.cases": {"tr": "Geliştirme vakaları", "en": "Development cases"},
    "nav.validation": {"tr": "Doğrulama panosu", "en": "Validation board"},
    "nav.expert_review": {"tr": "Uzman incelemesi", "en": "Expert review"},
    "nav.system": {"tr": "Sistem bilgisi", "en": "System information"},
    "nav.login": {"tr": "Oturum", "en": "Session"},

    # -- dependency and readiness banner ----------------------------------
    "status.dependency_unavailable": {
        "tr": "Bu ortamda bazı bileşenler kullanılamıyor. Etkilenen sayfalar "
              "eksik veriyi gizlemek yerine açıkça bildirir.",
        "en": "Some components are unavailable in this environment. Affected "
              "pages state the gap rather than hiding it."},
    "status.not_ready": {"tr": "Hazır değil", "en": "Not ready"},
    "status.ready": {"tr": "Hazır", "en": "Ready"},
    "status.blocking": {"tr": "Engelleyici", "en": "Blocking"},
    "status.advisory": {"tr": "Bilgilendirici", "en": "Advisory"},
    "status.unavailable": {"tr": "Kullanılamıyor", "en": "Unavailable"},
    "status.not_implemented": {"tr": "Uygulanmadı", "en": "Not implemented"},

    # -- home --------------------------------------------------------------
    "home.heading": {
        "tr": "PGx Platform V2 gösterim arayüzü",
        "en": "PGx Platform V2 demonstration interface"},
    "home.intro": {
        "tr": "Bu arayüz, sürümlenmiş bir kural kümesine karşı hesaplanmış "
              "yapısal bulguları gösterir. Hesaplamayı kendisi yapmaz; "
              "yalnızca uygulama katmanının döndürdüğü yönetilen olguları "
              "aktarır.",
        "en": "This interface displays structured findings calculated against "
              "a versioned ruleset. It performs no calculation itself; it "
              "relays the governed facts the application layer returned."},
    "home.sections": {"tr": "Bölümler", "en": "Sections"},

    # -- login -------------------------------------------------------------
    "login.heading": {"tr": "Oturum açma", "en": "Sign in"},
    "login.required": {
        "tr": "Bu arayüzün sayfaları kimliği doğrulanmış erişim gerektirir.",
        "en": "The pages of this interface require authenticated access."},
    "login.not_configured": {
        "tr": "Bu dağıtımda kimlik doğrulama sağlayıcısı yapılandırılmamıştır. "
              "Oturum açma işlemi burada tamamlanamaz ve tamamlanmış gibi "
              "gösterilmez.",
        "en": "No authentication provider is configured in this deployment. "
              "Signing in cannot complete here, and is not presented as "
              "though it had."},
    "login.owner": {
        "tr": "Kimlik doğrulama, oturum yönetimi ve CSRF koruması "
              "gerçekleştirilmiştir. Bu dağıtımda etkin olup olmadıkları "
              "ayrı bir bilgidir ve yukarıda belirtilir.",
        "en": "Authentication, session management and CSRF protection are "
              "implemented. Whether they are configured in this deployment "
              "is a separate fact, stated above."},
    # -- WP-23 ------------------------------------------------------------
    "login.username": {"tr": "Kullanıcı adı", "en": "Username"},
    "login.password": {"tr": "Parola", "en": "Password"},
    "login.submit": {"tr": "Oturum aç", "en": "Sign in"},
    "login.failed": {
        "tr": "Oturum açılamadı. Kullanıcı adı veya parola hatalı. Bu ileti, "
              "kullanıcının var olup olmadığına bakılmaksızın aynıdır.",
        "en": "Sign-in failed. The username or password is incorrect. This "
              "message is identical whether or not the account exists."},
    "login.rate_limited": {
        "tr": "Çok fazla deneme yapıldı. Bir süre sonra yeniden deneyin.",
        "en": "Too many attempts. Try again later."},
    "login.signed_in_as": {"tr": "Oturum sahibi", "en": "Signed in as"},
    "login.role": {"tr": "Rol", "en": "Role"},
    "login.no_personal_data": {
        "tr": "Bu sistem ad, e-posta, telefon veya kişisel bilgi saklamaz. "
              "Yukarıdaki kullanıcı adı ve rol, saklanan tek kimlik "
              "bilgisidir.",
        "en": "This system stores no name, email address, telephone number "
              "or personal detail. The username and role above are the only "
              "identity it holds."},
    "login.logout_available": {
        "tr": "Oturumu kapatmak sunucudaki oturumu iptal eder; çerez ancak "
              "bundan sonra silinir.",
        "en": "Signing out revokes the server-side session first; the cookie "
              "is cleared only afterwards."},
    "login.https_required": {
        "tr": "Oturum çerezi yalnızca HTTPS üzerinden gönderilir. Düz HTTP "
              "üzerinde oturum açma tamamlanamaz ve çerez politikası bunun "
              "için gevşetilmez.",
        "en": "The session cookie is sent over HTTPS only. Signing in cannot "
              "complete over plain HTTP, and the cookie policy is not "
              "relaxed to allow it."},
    "login.no_signup": {
        "tr": "Bu arayüzde kayıt olma, parola sıfırlama veya kimlik bilgisi "
              "üretme akışı bulunmaz.",
        "en": "This interface has no signup, password-reset or credential-"
              "issuing flow."},
    "login.logout": {"tr": "Oturumu kapat", "en": "Sign out"},
    "login.logout_unavailable": {
        "tr": "Kapatılacak bir oturum yok: bu dağıtımda oturum yönetimi "
              "yapılandırılmamıştır.",
        "en": "There is no session to end: session management is not "
              "configured in this deployment."},

    # -- case catalogue ----------------------------------------------------
    "cases.heading": {"tr": "Geliştirme vakaları",
                      "en": "Development cases"},
    "cases.caption": {
        "tr": "Geliştirme ve gösterim amaçlı sentetik vaka kataloğu",
        "en": "Synthetic case catalogue for development and demonstration"},
    "cases.development_only": {
        "tr": "Buradaki vakaların tamamı sentetiktir ve yalnızca geliştirme "
              "amaçlıdır. Hiçbiri doğrulama kanıtı, holdout verisi veya klinik "
              "bir örnek değildir.",
        "en": "Every case here is synthetic and development-only. None is "
              "validation evidence, holdout data, or a clinical example."},
    "cases.case_id": {"tr": "Vaka kimliği", "en": "Case identifier"},
    "cases.case_role": {"tr": "Vaka rolü", "en": "Case role"},
    "cases.legacy_key": {"tr": "Kaynak profil anahtarı",
                         "en": "Source profile key"},
    "cases.observation_count": {"tr": "Gözlem sayısı",
                                "en": "Observation count"},
    "cases.open": {"tr": "Vakayı aç", "en": "Open case"},
    "cases.empty": {
        "tr": "Bu dağıtımda geliştirme vakası kataloğu yüklenmemiştir.",
        "en": "No development case catalogue is loaded in this deployment."},

    # -- case detail and submission ---------------------------------------
    "case.heading": {"tr": "Vaka", "en": "Case"},
    "case.phenotypes": {"tr": "Kanonik fenotip gözlemleri",
                        "en": "Canonical phenotype observations"},
    "case.phenotypes_caption": {
        "tr": "Bu vakanın sabitlenmiş fenotip gözlemleri",
        "en": "The pinned phenotype observations for this case"},
    "case.medications": {"tr": "İlaç seçimi", "en": "Medication selection"},
    "case.medications_legend": {
        "tr": "Değerlendirilecek ilaçları seçin",
        "en": "Choose the medications to assess"},
    "case.medications_note": {
        "tr": "Bu liste, sabitlenmiş sürümün kanonik ilaç kataloğudur ve "
              "kanonik anahtara göre sıralanmıştır. Seçim yalnızca sentetik "
              "bir test isteği tanımlar; tedavi seçimi değildir ve hiçbir "
              "sıralama, öneri veya uygunluk ifade etmez.",
        "en": "This list is the pinned release's canonical medication "
              "catalogue, ordered by canonical key. A selection defines a "
              "synthetic test request only; it is not a treatment choice and "
              "expresses no ranking, recommendation or suitability."},
    "case.medications_unavailable": {
        "tr": "Kanonik ilaç kataloğu bu dağıtımda okunamıyor, bu nedenle "
              "seçim yapılamaz.",
        "en": "The canonical medication catalogue cannot be read in this "
              "deployment, so no selection can be made."},
    "case.submission_preview": {
        "tr": "Gönderilecek alanlar", "en": "Fields that will be submitted"},
    "case.submission_preview_note": {
        "tr": "Aşağıdaki alanlar dışında hiçbir veri gönderilmez. Aktör, rol, "
              "özet değerleri ve sürüm bilgisi istemci tarafından "
              "gönderilemez; bunları sunucu belirler.",
        "en": "No data beyond these fields is submitted. Actor, role, hashes "
              "and release provenance cannot be sent by the client; the "
              "server determines them."},
    "case.submit": {"tr": "Sentetik değerlendirmeyi çalıştır",
                    "en": "Run synthetic assessment"},
    "case.submit_unavailable": {
        "tr": "Değerlendirme çalıştırma bu dağıtımda kullanılamıyor. Gerekli "
              "bağımlılıklar hazır olmadan istek gönderilmez.",
        "en": "Running an assessment is unavailable in this deployment. No "
              "request is sent while the required dependencies are not "
              "ready."},
    "case.no_free_text": {
        "tr": "Bu formda hasta adı, kimlik, doğum tarihi, dosya numarası, "
              "genotip, varyant dosyası, tanı, endikasyon, doz veya serbest "
              "metin alanı bulunmaz.",
        "en": "This form has no field for a patient name, identifier, date of "
              "birth, record number, genotype, variant file, diagnosis, "
              "indication, dose or free text."},

    # -- assessment --------------------------------------------------------
    # -- Wave 4B: the candidate track's own screens ----------------------
    "candidate.heading": {"tr": "Aday değerlendirme",
                          "en": "Candidate assessment"},
    "candidate.demo_notice": {
        "tr": "Bu ekran yalnızca sentetik veya yayından türetilmiş gösterim "
              "girdileriyle çalışır. Gerçek hasta verisi, VCF dosyası veya "
              "hasta kayıt sistemi bağlantısı desteklenmez.",
        "en": "This screen runs only on synthetic or literature-derived "
              "demonstration input. Real patient data, VCF files and health "
              "record connections are not supported."},
    "candidate.refusal_notice": {
        "tr": "Reddedilen eksenler dikkat düzeyinden ayrı listelenir. Bir "
              "reddin dikkat bulgusu yokluğu olarak gösterilmesi yanıltıcı "
              "olurdu.",
        "en": "Refused axes are listed separately from the attention level. "
              "Showing a refusal as an absence of attention would be "
              "misleading."},
    "candidate.authority": {"tr": "Yetki durumu", "en": "Authority state"},
    "candidate.release": {"tr": "Aday sürüm", "en": "Candidate release"},
    "candidate.refusals": {"tr": "Reddedilen eksenler",
                           "en": "Refused axes"},
    "candidate.lineage": {"tr": "Kanıt zinciri", "en": "Evidence lineage"},
    "candidate.no_refusals": {"tr": "Reddedilen eksen yok.",
                              "en": "No axis was refused."},
    "candidate.joint": {"tr": "Ortak iki gen kuralı",
                        "en": "Joint two-gene rule"},
    "candidate.single": {"tr": "Tek gen kuralı", "en": "Single-gene rule"},
    "candidate.care_setting": {"tr": "Klinik bağlam", "en": "Care setting"},
    "candidate.care_setting_help": {
        "tr": "Klopidogrel için ACS/PCI bağlamı zorunludur. Bağlam "
              "bildirilmezse eksen reddedilir.",
        "en": "Clopidogrel requires an ACS/PCI context. Without a declared "
              "context the axis is refused."},
    "candidate.care_setting_none": {"tr": "Bildirilmedi",
                                    "en": "Not declared"},
    "assessment.heading": {"tr": "Değerlendirme", "en": "Assessment"},
    "assessment.overall": {"tr": "Genel durum", "en": "Overall status"},
    "assessment.status_pair_note": {
        "tr": "Dikkat düzeyi ve kapsam birlikte okunur. Biri diğerinin yerine "
              "geçmez ve tek başına gösterilmez.",
        "en": "Attention and coverage are read together. Neither substitutes "
              "for the other and neither is shown alone."},
    "assessment.medications": {"tr": "İlaç bazında sonuçlar",
                               "en": "Per-medication results"},
    "assessment.medication_caption": {
        "tr": "Bu ilaç için değerlendirilen ve değerlendirilemeyen eksenler",
        "en": "Evaluated and unevaluated axes for this medication"},
    "assessment.axes": {"tr": "Eksenler", "en": "Axes"},
    "assessment.axes_caption": {
        "tr": "Gen-ilaç eksenleri ve kapsam durumları",
        "en": "Gene-medication axes and their coverage status"},
    "assessment.findings": {"tr": "Bulgular", "en": "Findings"},
    "assessment.findings_caption": {
        "tr": "Yönetilen kurallardan üretilen bulgular ve kanıt izleri",
        "en": "Findings produced by governed rules, with their evidence "
              "trace"},
    "assessment.no_findings": {
        "tr": "Bu ilaç için yönetilen kurallardan bulgu üretilmedi. Bu, "
              "güvenli olduğu anlamına gelmez; yalnızca değerlendirilebilen "
              "eksenlerde kural eşleşmediğini gösterir.",
        "en": "No finding was produced from the governed rules for this "
              "medication. That does not mean it is safe; it means no rule "
              "matched on the axes that could be evaluated."},
    "assessment.observations": {"tr": "Gözlemler", "en": "Observations"},
    "assessment.observations_caption": {
        "tr": "Değerlendirmeye giren kanonik fenotip gözlemleri",
        "en": "The canonical phenotype observations this assessment used"},
    "assessment.provenance": {"tr": "Sürüm ve köken bilgisi",
                              "en": "Release and provenance"},
    "assessment.provenance_caption": {
        "tr": "Bu değerlendirmenin sabitlendiği tam sürüm kimlikleri",
        "en": "The complete pinned version identities for this assessment"},
    "assessment.hashes": {"tr": "Özet değerleri", "en": "Hashes"},
    "assessment.pinned_note": {
        "tr": "Bu değerlendirme, çalıştırıldığı anda sabitlenen sürüme aittir. "
              "Daha sonra başka bir sürüm etkinleştirilse bile bu sayfa aynı "
              "sabitlenmiş sürümü göstermeye devam eder.",
        "en": "This assessment belongs to the release pinned when it ran. If "
              "another release is activated later, this page continues to "
              "show the same pinned release."},
    "assessment.conflicts": {"tr": "Çelişki referansları",
                             "en": "Conflict references"},
    "assessment.evidence_references": {"tr": "Kanıt referansları",
                                       "en": "Evidence references"},
    "assessment.unevaluated": {"tr": "Değerlendirilemeyen eksenler",
                               "en": "Unevaluated axes"},

    # -- evidence ----------------------------------------------------------
    "evidence.heading": {"tr": "Kanıt kaydı", "en": "Evidence record"},
    "evidence.identity": {"tr": "Kayıt kimliği", "en": "Record identity"},
    "evidence.source": {"tr": "Kaynak kimliği", "en": "Source identity"},
    "evidence.provenance": {"tr": "Köken zinciri", "en": "Provenance chain"},
    "evidence.entities": {"tr": "Kanonik varlık bağlantıları",
                          "en": "Canonical entity links"},
    "evidence.entities_caption": {
        "tr": "Bu kaydın bağlandığı kanonik gen ve ilaçlar",
        "en": "The canonical genes and medications this record links to"},
    "evidence.publications": {"tr": "Yayın tanımlayıcıları",
                              "en": "Publication identifiers"},
    "evidence.publications_caption": {
        "tr": "Kaynağın belirttiği yayın tanımlayıcıları",
        "en": "The publication identifiers the source stated"},
    "evidence.locators": {"tr": "Konum kayıtları", "en": "Locators"},
    "evidence.locators_caption": {
        "tr": "Kaydın ham anlık görüntü içindeki değişmez konumu",
        "en": "The record's immutable position inside the raw snapshot"},
    "evidence.mapping": {"tr": "Kayıt türü eşlemesi",
                         "en": "Record type mapping"},
    "evidence.text_fragments": {"tr": "Kaynak metin parçası sayısı",
                                "en": "Source text fragment count"},
    "evidence.no_prose_note": {
        "tr": "Kaynak metinleri burada gösterilmez. Bu sayfa kimlik, köken ve "
              "özet değerlerini gösterir; kaynak ifadelerini yeniden yazmaz ve "
              "özetlemez.",
        "en": "Source text is not shown here. This page shows identity, "
              "provenance and hashes; it does not restate or summarise what a "
              "source said."},
    "evidence.immutable_note": {
        "tr": "Kanıt kaydına değişmez kimliğiyle ulaşılır. Etkin sürüm "
              "değişse bile bir değerlendirmenin atıf yaptığı kayıt aynı "
              "kalır.",
        "en": "An evidence record is reached by its immutable identity. The "
              "record an assessment cited stays the same even if the active "
              "release changes."},

    # -- validation --------------------------------------------------------
    "validation.heading": {"tr": "Doğrulama panosu",
                           "en": "Validation board"},
    "validation.no_run": {
        "tr": "Bu depoda hiçbir doğrulama çalıştırması yapılmamıştır.",
        "en": "No validation run has been performed in this repository."},
    "validation.architecture_missing": {
        "tr": "Doğrulama veri kümesi mimarisi ve holdout ayrımı henüz "
              "uygulanmamıştır. Bu sayfa yalnızca boş durumu gösterir.",
        "en": "The validation dataset architecture and the holdout separation "
              "are not implemented yet. This page shows the empty state only."},
    "validation.metrics_unavailable": {
        "tr": "Uyum, doğruluk, geçme oranı ve benzeri ölçütler "
              "hesaplanamamıştır. Payda sıfır olduğu için bu değerler yüzde "
              "sıfır veya yüzde yüz olarak gösterilmez; kullanılamıyor olarak "
              "gösterilir.",
        "en": "Concordance, accuracy, pass rate and similar metrics have not "
              "been computed. Because the denominator is zero these values "
              "are not shown as zero or one hundred per cent; they are shown "
              "as unavailable."},
    "validation.development_cases": {"tr": "Geliştirme vakası sayısı",
                                     "en": "Development case count"},
    "validation.holdout_cases": {"tr": "İç holdout vakası sayısı",
                                 "en": "Internal holdout case count"},
    "validation.expert_cases": {"tr": "Uzman holdout vakası sayısı",
                                "en": "Expert holdout case count"},
    "validation.validation_runs": {"tr": "Doğrulama çalıştırması sayısı",
                                   "en": "Validation run count"},
    "validation.separation_note": {
        "tr": "Geliştirme vakaları ile holdout vakaları hiçbir sayımda "
              "birleştirilmez. Geliştirme vakaları doğrulama kanıtı değildir.",
        "en": "Development cases and holdout cases are never combined in any "
              "count. Development cases are not validation evidence."},
    "validation.no_conclusion": {
        "tr": "Bu sayfadaki hiçbir bilgi klinik geçerlilik hakkında sonuç "
              "çıkarmak için kullanılamaz.",
        "en": "Nothing on this page may be used to draw a conclusion about "
              "clinical validity."},
    # -- WP-21 metric table ------------------------------------------------
    "validation.metrics_heading": {"tr": "Doğrulama ölçütleri",
                                   "en": "Validation metrics"},
    "validation.metric_id": {"tr": "Ölçüt", "en": "Metric"},
    "validation.metric_label": {"tr": "Açıklama", "en": "Description"},
    "validation.numerator": {"tr": "Pay", "en": "Numerator"},
    "validation.denominator": {"tr": "Payda", "en": "Denominator"},
    "validation.metric_value": {"tr": "Değer", "en": "Value"},
    "validation.metric_status": {"tr": "Durum", "en": "Status"},
    "validation.metric_reason": {"tr": "Neden", "en": "Reason"},
    "validation.section_development": {
        "tr": "GELİŞTİRME REGRESYONU - doğrulama kanıtı değildir",
        "en": "DEVELOPMENT REGRESSION - not validation evidence"},
    "validation.section_internal": {"tr": "İç holdout",
                                    "en": "Internal holdout"},
    "validation.section_expert": {"tr": "Uzman holdout",
                                  "en": "Expert holdout"},
    "validation.development_warning": {
        "tr": "Bu bölümdeki vakalar yazılımı şekillendirmiştir. Buradaki "
              "hiçbir sayı doğrulama kanıtı değildir ve hiçbir doğrulama "
              "paydasına giremez.",
        "en": "The cases in this section shaped the software. No number here "
              "is validation evidence and none may enter a validation "
              "denominator."},
    "validation.holdout_evidence_note": {
        "tr": "Bu bölüm ancak bağımsız vakalar ve bir referans yargısı "
              "varsa doğrulama kanıtı olur.",
        "en": "This section is validation evidence only if independent cases "
              "and a reference judgment exist."},
    "validation.no_combined": {
        "tr": "Geliştirme ve holdout sonuçlarını birleştiren tek bir genel "
              "değer yoktur; bölümleri ayrı ayrı okuyun.",
        "en": "There is no single combined figure over development and "
              "holdout; read the sections separately."},
    "validation.not_benchmarked": {
        "tr": "Hiçbir sürüm için karşılaştırma çalıştırması yapılmamıştır. "
              "Her ölçüt \u00e7alıştırılmadı olarak gösterilir; sıfır "
              "olarak değil.",
        "en": "No benchmark has been run against any release. Every metric "
              "is shown as not executed, never as zero."},
    "validation.release": {"tr": "Sürüm", "en": "Release"},
    "validation.metric_registry": {"tr": "Ölçüt kaydı sürümü",
                                   "en": "Metric registry version"},
    "validation.case_count": {"tr": "Vaka sayısı", "en": "Case count"},
    "status.not_executed": {"tr": "Çalıştırılmadı", "en": "Not executed"},
    "status.blocked": {"tr": "Engellendi", "en": "Blocked"},
    "validation.blockers": {"tr": "Dış engeller", "en": "External blockers"},
    "validation.blockers_caption": {
        "tr": "Bu iş paketinin kapatamayacağı engeller",
        "en": "Blockers this work package cannot clear"},

    # -- expert review -----------------------------------------------------
    "expert.heading": {"tr": "Uzman incelemesi", "en": "Expert review"},
    # -- WP-22 blind review workflow ---------------------------------------
    "expert.unavailable": {
        "tr": "Bu vaka için size atanmış etkin bir inceleme yok veya inceleme "
              "hizmeti kullanılamıyor. Bu ileti, vakanın var olup olmadığına "
              "bakılmaksızın aynıdır.",
        "en": "You hold no active review assignment for this case, or the "
              "review service is unavailable. This message is identical "
              "whether or not the case exists."},
    "expert.blinded": {
        "tr": "Beklenen yanıtınız kilitlenene kadar sistemin sonucu size "
              "gösterilmez. Bu sayfada sistem sonucunu taşıyacak hiçbir alan "
              "yoktur; gizli bir alanda da bulunmaz.",
        "en": "The system result is not shown until your expected response is "
              "locked. This page has no field that could carry one, including "
              "a hidden one."},
    "expert.protocol_draft": {
        "tr": "Kör inceleme protokolü TASLAK durumundadır ve insan ile "
              "bilimsel onay beklemektedir. Onaylanana kadar hiçbir işlem "
              "yürütülmez.",
        "en": "The blind review protocol is a DRAFT awaiting human and "
              "scientific review. No operation executes until it is "
              "approved."},
    "expert.forms_disabled": {
        "tr": "Formlar devre dışıdır: kimlik doğrulama ve CSRF koruması "
              "WP-23'e aittir ve henüz mevcut değildir. Gönderilemeyecek bir "
              "form göstermek, doldurulup kaydedildiği sanılacağı için daha "
              "kötüdür.",
        "en": "Forms are disabled: authentication and CSRF protection belong "
              "to WP-23 and do not exist yet. Showing a control that cannot "
              "submit is worse than showing none, because it would be filled "
              "in and believed."},
    "expert.phase_done": {"tr": "Tamamlandı", "en": "Done"},
    "expert.phase_pending": {"tr": "Bekliyor", "en": "Pending"},
    "expert.expected_heading": {"tr": "Beklenen yanıtınız",
                                "en": "Your expected response"},
    "expert.expected_form": {"tr": "Beklenen yanıtı kaydet",
                             "en": "Record the expected response"},
    "expert.expected_locked": {
        "tr": "Beklenen yanıtınız kilitlendi. Değiştirilemez; değişiklik "
              "ancak eklenen bir düzeltmedir.",
        "en": "Your expected response is locked. It cannot be replaced; a "
              "change is an appended correction."},
    "expert.attention": {"tr": "Beklenen dikkat düzeyi",
                         "en": "Expected attention level"},
    "expert.coverage": {"tr": "Beklenen kapsam durumu",
                        "en": "Expected coverage status"},
    "expert.coverage_reason": {"tr": "Beklenen kapsam gerekçesi",
                               "en": "Expected coverage reason"},
    "expert.rule_id": {"tr": "Beklenen kural kimliği",
                       "en": "Expected rule identifier"},
    "expert.evidence_required": {"tr": "İzlenebilir kanıt bekleniyor",
                                 "en": "Traceable evidence expected"},
    "expert.rationale": {"tr": "Gerekçe kodları", "en": "Rationale codes"},
    "expert.note": {"tr": "Not", "en": "Note"},
    "expert.note_limit": {
        "tr": "Sınırlı not. Tedavi önerisi, doz veya klinik talimat "
              "içeremez.",
        "en": "A bounded note. It may not contain a treatment "
              "recommendation, a dose or a clinical directive."},
    "expert.recorded_at": {"tr": "Sunucu zaman damgası",
                           "en": "Server timestamp"},
    "expert.revision_hash": {"tr": "Revizyon özeti", "en": "Revision hash"},
    "expert.reveal_action": {"tr": "Sistem sonucunu göster",
                             "en": "Reveal the system result"},
    "expert.reveal_warning": {
        "tr": "Bu işlem geri alınamaz. Gösterimden sonra eklenen hiçbir "
              "düzeltme, ölçütlerin kullandığı kilitli beklentiyi "
              "değiştiremez.",
        "en": "This is irreversible. No correction appended after the reveal "
              "can change the locked expectation the metrics consume."},
    "expert.result_heading": {"tr": "Sistem sonucu", "en": "System result"},
    # The result table must not borrow the expectation's row labels. A row
    # reading "expected attention level" above the system's own value is a
    # mislabelled comparison, and the comparison is the whole point of the
    # screen: both columns of the reviewer's judgement are on it at once.
    "expert.result_attention": {"tr": "Sistem dikkat düzeyi",
                                "en": "System attention level"},
    "expert.result_coverage": {"tr": "Sistem kapsam durumu",
                               "en": "System coverage status"},
    "expert.result_coverage_reason": {"tr": "Sistem kapsam gerekçesi",
                                      "en": "System coverage reason"},
    "expert.result_rule_id": {"tr": "Sistemin çalıştırdığı kural",
                              "en": "Firing rule identifier"},
    "expert.finding_count": {"tr": "Dikkat bulgusu sayısı",
                            "en": "Attention finding count"},
    "expert.traceable_finding_count": {"tr": "İzlenebilir bulgu sayısı",
                                       "en": "Traceable finding count"},
    "expert.pinned_expectation": {"tr": "Sabitlenen beklenti özeti",
                                  "en": "Pinned expectation hash"},
    "expert.decision_heading": {"tr": "Karşılaştırma kararınız",
                                "en": "Your comparison decision"},
    "expert.decision_note": {
        "tr": "KISMEN, KATILIYORUM ile KATILMIYORUM arasında bir orta nokta "
              "değildir; üçüncü bir yanıttır. Bu değerler sıralanmaz ve "
              "ortalaması alınmaz.",
        "en": "PARTIAL is not a midpoint between AGREE and DISAGREE; it is a "
              "third answer. These values are never ordered or averaged."},
    "expert.ratings_heading": {"tr": "İsteğe bağlı değerlendirmeler",
                               "en": "Optional ratings"},
    "expert.ratings_note": {
        "tr": "İsteğe bağlıdır. Değerlendirmemek düşük puan olarak sayılmaz: "
              "payda tamamlanan değerlendirmeleri sayar, incelemeleri değil.",
        "en": "Optional. Declining to rate is not counted as a low score: the "
              "denominator counts completed ratings, not completed reviews."},
    "expert.completed_heading": {"tr": "Tamamlanan inceleme",
                                 "en": "Completed review"},
    "expert.completed_note": {
        "tr": "Bu kayıt değiştirilemez. Sonraki değişiklikler yalnızca "
              "eklenen düzeltmelerdir.",
        "en": "This record is immutable. Later changes are appended "
              "corrections only."},
    "expert.corrections_heading": {"tr": "Düzeltme geçmişi",
                                   "en": "Correction history"},
    "expert.correction_after_reveal": {
        "tr": "gösterimden sonra - yalnızca açıklama",
        "en": "after reveal - annotation only"},
    "expert.correction_before_reveal": {"tr": "gösterimden önce",
                                        "en": "before reveal"},
    "expert.release": {"tr": "Sabitlenen sürüm", "en": "Pinned release"},
    "expert.protocol": {"tr": "Protokol sürümü", "en": "Protocol version"},
    "expert.not_an_opinion": {
        "tr": "Bu sayfadaki hiçbir kayıt klinik geçerlilik kanıtı değildir. "
              "Yazılımın bir incelemeyi doğru kaydetmesi, bir uzmanın bir "
              "şeye baktığı anlamına gelmez.",
        "en": "No record on this page is evidence of clinical validity. That "
              "the software recorded a review correctly does not mean a "
              "clinician looked at anything."},
    "expert.order": {
        "tr": "Akışın sırası korunur: önce beklenen yanıt kaydedilir, sonra "
              "sonuç açılır, en son inceleme kapatılır. Bu sıra bozulursa "
              "körleme geçersiz olur.",
        "en": "The order of the workflow is preserved: the expected answer is "
              "recorded first, then the result is revealed, and the review is "
              "closed last. Breaking that order invalidates the blinding."},
    "expert.phase_expected": {"tr": "1. Beklenen yanıtın kaydı",
                              "en": "1. Record the expected answer"},
    "expert.phase_reveal": {"tr": "2. Sonucun açılması",
                            "en": "2. Reveal the result"},
    "expert.phase_complete": {"tr": "3. İncelemenin kapatılması",
                              "en": "3. Close the review"},
    "expert.no_case_disclosure": {
        "tr": "Bu sayfa bir vakanın var olup olmadığını bildirmez.",
        "en": "This page does not report whether a case exists."},
    "expert.no_receipt": {
        "tr": "Hiçbir kayıt tutulmaz ve hiçbir alındı belgesi üretilmez.",
        "en": "Nothing is recorded and no receipt is issued."},

    # -- system ------------------------------------------------------------
    "system.heading": {"tr": "Sistem bilgisi", "en": "System information"},
    "system.versions": {"tr": "Sürüm kimlikleri", "en": "Version identities"},
    "system.versions_caption": {
        "tr": "Etkin sürümün sabitlediği kimlikler ve özet değerleri",
        "en": "The identities and hashes the active release pins"},
    "system.readiness": {"tr": "Hazırlık durumu", "en": "Readiness"},
    "system.readiness_caption": {
        "tr": "Bileşen bazında hazırlık durumu",
        "en": "Component-by-component readiness"},
    "system.component": {"tr": "Bileşen", "en": "Component"},
    "system.detail": {"tr": "Açıklama", "en": "Detail"},
    "system.overall_readiness": {"tr": "Genel hazırlık",
                                 "en": "Overall readiness"},
    "system.claim_boundary": {"tr": "İddia sınırı durumu",
                              "en": "Claim boundary status"},
    "system.version_unavailable": {
        "tr": "Etkin sürüm okunamıyor, bu nedenle sürüm kimlikleri "
              "gösterilemiyor. Eksik değerler tahmin edilmez.",
        "en": "The active release cannot be read, so version identities "
              "cannot be shown. Missing values are not guessed."},

    # -- errors ------------------------------------------------------------
    "error.heading": {"tr": "İstek tamamlanamadı",
                      "en": "The request could not be completed"},
    "error.code": {"tr": "Hata kodu", "en": "Error code"},
    "error.summary": {"tr": "Hata özeti", "en": "Error summary"},
    "error.what_now": {"tr": "Ne yapılabilir?", "en": "What can be done?"},
    "error.no_partial": {
        "tr": "Eksik veya tutarsız bir sonuç kısmen gösterilmez. Bu sayfa, "
              "yarım bir değerlendirmenin yerine geçer.",
        "en": "An incomplete or inconsistent result is never partly "
              "displayed. This page stands in place of a half assessment."},
    "error.back_home": {"tr": "Başlangıç sayfasına dön",
                        "en": "Return to the home page"},
}


def ui(key: str, locale: str = "tr") -> str:
    """One controlled interface string, or a refusal.

    Raises:
        LabelNotDefinedError: no text is defined for this key in this locale.
            Refused rather than falling back to the key or to the other
            locale: a page showing a key looks like a layout bug, and a page
            silently switching language hands a reader words they did not ask
            for.
    """
    key_locale = require_locale(locale)
    entry = UI_TEXT.get(key)
    if entry is None or key_locale not in entry:
        raise LabelNotDefinedError(
            "no controlled interface text for %r in locale %r"
            % (key, key_locale))
    return entry[key_locale]


def ui_table(locale: str = "tr") -> Dict[str, str]:
    """Every interface string in one locale, for one template render."""
    key_locale = require_locale(locale)
    return {key: value[key_locale] for key, value in UI_TEXT.items()
            if key_locale in value}


def attention_label(code: str, locale: str = "tr") -> str:
    """The governed attention label. Never the code, never invented."""
    return label(ATTENTION_LABELS, code, locale, table_name="attention_label")


def coverage_label(code: str, locale: str = "tr") -> str:
    return label(COVERAGE_LABELS, code, locale, table_name="coverage_label")


def coverage_reason_label(code: str, locale: str = "tr") -> str:
    return label(COVERAGE_REASON_LABELS, code, locale,
                 table_name="coverage_reason_label")


def observation_state_label(code: str, locale: str = "tr") -> str:
    return label(OBSERVATION_STATE_LABELS, code, locale,
                 table_name="observation_state_label")


def field_label(code: str, locale: str = "tr") -> str:
    return label(FIELD_LABELS, code, locale, table_name="field_label")
