"""Web error codes and the page that stands in for a failed request.

The API's envelope is machine-facing and is reused verbatim as the *source* of
truth: a failure arrives from the client carrying WP-16's stable code, its
status and its request id, and none of those are rewritten here. What this
module adds is the human-facing half - a controlled Turkish/English
explanation per code, and the rule that a page is never partly rendered.

Two things are deliberately absent.

**No exception text ever reaches a page.** The explanation comes from the
table below, keyed by the code. A message built from an exception is how a
connection string, a path or a fragment of SQL ends up on screen, and the
person who sees it is not the person who can act on it.

**No failure becomes an empty success.** A page that rendered with a missing
section would look like an assessment with nothing in it, which reads as
reassurance. Every failure produces the error page instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from apps.api.errors import ERROR_CATALOGUE, status_for_code

__all__ = [
    "WEB_ERROR_GUIDANCE",
    "WebError",
    "guidance_for",
]


class WebError(Exception):
    """A page could not be produced. Carries the API's code, not a new one.

    Reusing WP-16's code rather than minting a web one keeps a screenshot, a
    log line and an API response describing the same failure with the same
    word. A second vocabulary would mean a support conversation that starts by
    translating.
    """

    def __init__(self, code: str, *, request_id: str = "",
                 details: Optional[Mapping[str, Any]] = None) -> None:
        self.code = code if code in ERROR_CATALOGUE else "INTERNAL_ERROR"
        self.request_id = request_id
        self.details = dict(details or {})
        super().__init__(self.code)

    @property
    def status(self) -> int:
        return status_for_code(self.code)


#: What a reader can do about each failure, in controlled text.
#:
#: Keyed by API code. A code with no entry falls back to the generic guidance
#: rather than to the API's own message: the API message is written for a
#: machine's operator and can name a component a page reader has never heard
#: of.
WEB_ERROR_GUIDANCE: Mapping[str, Mapping[str, str]] = {
    "UNAUTHENTICATED": {
        "tr": "Bu sayfa kimliği doğrulanmış erişim gerektirir.",
        "en": "This page requires authenticated access."},
    "FORBIDDEN_ROLE": {
        "tr": "Bu sayfa için gereken rol hesabınızda tanımlı değil.",
        "en": "Your account does not hold the role this page requires."},
    "AUTHENTICATION_NOT_CONFIGURED": {
        "tr": "Bu dağıtımda kimlik doğrulama sağlayıcısı yapılandırılmamıştır. "
              "Bu bir istek hatası değil, tamamlanmamış bir kurulumdur.",
        "en": "No authentication provider is configured in this deployment. "
              "This is not a problem with the request; the installation is "
              "incomplete."},
    "ASSESSMENT_NOT_FOUND": {
        "tr": "Bu kimlikle kayıtlı bir değerlendirme bulunmuyor.",
        "en": "No assessment is stored under that identity."},
    "EVIDENCE_NOT_FOUND": {
        "tr": "Bu kimlikle kayıtlı bir kanıt kaydı bulunmuyor.",
        "en": "No evidence record is stored under that identity."},
    "RESOURCE_NOT_FOUND": {
        "tr": "İstenen sayfa bulunamadı.",
        "en": "The requested page was not found."},
    "STORED_RESULT_INCONSISTENT": {
        "tr": "Kayıtlı değerlendirme kendi özet değerleriyle uyuşmuyor. Kısmi "
              "bir sonuç gösterilmez; kayıt incelenmelidir.",
        "en": "The stored assessment does not agree with its own hashes. No "
              "partial result is shown; the record needs investigation."},
    "ARTIFACT_INCONSISTENT": {
        "tr": "Sürüm yapıtları birbiriyle uyuşmuyor. Bu durumda hiçbir sonuç "
              "üretilmez.",
        "en": "The release artifacts disagree with each other. No result is "
              "produced in that state."},
    "CLAIM_BOUNDARY_NOT_APPROVED": {
        "tr": "İddia sınırı henüz adı belirtilmiş insan ve bilimsel "
              "inceleyiciler tarafından onaylanmamıştır. Bu bir yönetişim "
              "kapısıdır; istekle ilgili bir sorun değildir.",
        "en": "The claim boundary has not been approved by the named human "
              "and scientific reviewers. This is a governance gate, not a "
              "problem with the request."},
    "ACTIVE_RELEASE_UNAVAILABLE": {
        "tr": "Etkin bir sürüm bulunmadığı için değerlendirme yapılamaz.",
        "en": "No release is active, so no assessment can be made."},
    "DATABASE_UNAVAILABLE": {
        "tr": "Veri tabanına ulaşılamıyor, bu nedenle kayıtlı sonuçlar "
              "okunamaz.",
        "en": "The database cannot be reached, so stored results cannot be "
              "read."},
    "EVIDENCE_BUILD_UNAVAILABLE": {
        "tr": "Kanıt derlemesi bu dağıtımda yapılandırılmamıştır.",
        "en": "No evidence build is configured in this deployment."},
    "CATALOGUE_UNAVAILABLE": {
        "tr": "Kanonik katalog okunamıyor.",
        "en": "The canonical catalogue cannot be read."},
    "SERVICE_NOT_READY": {
        "tr": "Gerekli bir bileşen hazır değil. Sistem bilgisi sayfası hangi "
              "bileşenin eksik olduğunu bileşen bazında gösterir.",
        "en": "A required component is not ready. The system information page "
              "shows which one, component by component."},
    "REQUEST_CONTRACT_VIOLATION": {
        "tr": "İstek, kabul edilen alan ve sınırlara uymuyor.",
        "en": "The request does not satisfy the accepted fields and bounds."},
    "PROHIBITED_INPUT_FIELD": {
        "tr": "İstek, bu ürünün kabul etmediği bir alan taşıyor. Değer "
              "kaydedilmedi ve burada gösterilmez.",
        "en": "The request carries a field this product does not accept. The "
              "value was not recorded and is not shown here."},
    "UNSUPPORTED_PHENOTYPE": {
        "tr": "Verilen fenotip değeri bu giriş sözleşmesinde tanımlı değil.",
        "en": "The supplied phenotype value is not defined under this input "
              "contract."},
    # WP-22 replaced EXPERT_REVIEW_NOT_IMPLEMENTED, which said the workflow
    # did not exist. It exists now, so the honest refusals are these two: the
    # service is not wired up, or this reviewer holds no assignment. The
    # second is deliberately identical whether or not the case exists,
    # because a distinguishable answer would enumerate the holdout set.
    "EXPERT_REVIEW_NOT_AVAILABLE": {
        "tr": "Uzman inceleme hizmeti bu dağıtımda yapılandırılmamıştır.",
        "en": "The expert review service is not configured in this "
              "deployment."},
    "EXPERT_REVIEW_NOT_ASSIGNED": {
        "tr": "Bu vaka için size atanmış etkin bir inceleme yok. Bu ileti, "
              "vakanın var olup olmadığına bakılmaksızın aynıdır.",
        "en": "You hold no active review assignment for this case. This "
              "message is identical whether or not the case exists."},
    "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED": {
        "tr": "Kör inceleme protokolü onaylanmamıştır; hiçbir inceleme "
              "işlemi yürütülmez.",
        "en": "The blind review protocol is not approved, so no review "
              "operation executes."},
    "PERSISTENCE_REFUSED": {
        "tr": "Sonuç kaydedilemedi, bu nedenle hiçbir sonuç gösterilmez. "
              "Kaydedilmemiş bir hesaplama sonuç değildir.",
        "en": "The result could not be stored, so no result is shown. An "
              "unstored calculation is not a result."},
    "INTERNAL_ERROR": {
        "tr": "Beklenmeyen bir hata oluştu. Ayrıntılar sunucu tarafında "
              "kalır; bu sayfa istek kimliğini gösterir.",
        "en": "An unexpected error occurred. The details stay on the server; "
              "this page shows the request identifier."},
}

_GENERIC_GUIDANCE: Mapping[str, str] = {
    "tr": "İstek tamamlanamadı. Ayrıntılar sunucu tarafında kalır.",
    "en": "The request could not be completed. The details stay on the "
          "server.",
}


def guidance_for(code: str, locale: str = "tr") -> str:
    """The controlled explanation for one API error code."""
    from pgx.reporting.templates import require_locale

    key = require_locale(locale)
    entry = WEB_ERROR_GUIDANCE.get(code)
    if entry is None or key not in entry:
        return _GENERIC_GUIDANCE[key]
    return entry[key]
