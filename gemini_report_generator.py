#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gemini_report_generator.py

Risk motorunun ürettiği gemini_input.json dosyasını alır ve:
1) GEMINI_API_KEY varsa Google Gemini API ile Türkçe, klinik olmayan ön değerlendirme raporu üretir.
2) API key yoksa veya API çağrısı başarısız olursa fallback deterministic rapor üretir.

Girdi:
- gemini_input.json

Çıktı:
- gemini_report.md
- gemini_report_payload.json
- gemini_report_status.json

Kurulum:
pip install -U google-genai

Kullanım:
export GEMINI_API_KEY="AIza..."
python gemini_report_generator.py \
  --input gemini_input.json \
  --out-dir final_report \
  --model gemini-3.5-flash

API'siz fallback:
python gemini_report_generator.py \
  --input gemini_input.json \
  --out-dir final_report \
  --no-api

ÖNEMLİ:
Bu script klinik karar, doz önerisi veya tedavi önerisi üretmez.
Risk hesaplama burada yapılmaz; risk_engine.py çıktısı sadece rapor diline çevrilir.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_MODEL = "gemini-3.5-flash"

CLINICAL_WARNING_TR = (
    "Bu çıktı klinik karar, doz önerisi veya tedavi önerisi değildir. "
    "ClinPGx kaynaklı veriler ve sentetik CYP profilleri kullanılarak oluşturulmuş "
    "açıklanabilir farmakogenetik ön değerlendirme / MVP dikkat bayrağıdır."
)


# -----------------------------
# File helpers
# -----------------------------

def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON dosyası bulunamadı: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {path}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"[SAVED] {path}")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def compact(value: Any, max_len: int = 1200) -> str:
    text = norm_text(value)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# -----------------------------
# Input validation / compacting
# -----------------------------

def validate_gemini_input(data: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []

    required = ["profile", "selected_drugs", "overall_risk_level", "drug_results"]
    for key in required:
        if key not in data:
            warnings.append(f"Eksik alan: {key}")

    if not data.get("drug_results"):
        warnings.append("drug_results boş görünüyor.")

    if data.get("risk_flag_count", 0) == 0:
        warnings.append("Risk bayrağı sayısı 0; rapor normal/uyarı yok formatında üretilecek.")

    return warnings


def compact_for_prompt(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gemini'ye dev evidence listelerini değil, rapor için gerekli compact bilgiyi gönderir.
    Risk hesaplama zaten risk_engine.py'de yapılmıştır.
    """
    profile = data.get("profile", {}) or {}

    compact_drugs = []
    for drug in data.get("drug_results", []) or []:
        compact_findings = []

        for finding in drug.get("findings", []) or []:
            # gemini_input.json genelde sadece risk_flag findings içeriyor;
            # risk_result_full.json gelirse normal/no-match bulguları filtreleyelim.
            if finding.get("status") and finding.get("status") != "risk_flag":
                continue

            guideline_summary = ""
            guideline_sources = []

            if "guideline_summary" in finding:
                guideline_summary = finding.get("guideline_summary") or ""
            if "guideline_sources" in finding:
                guideline_sources = finding.get("guideline_sources") or []

            guideline = finding.get("guideline", {}) or {}
            if guideline:
                guideline_sources = guideline.get("sources", guideline_sources)
                summaries = guideline.get("guideline_summaries", []) or []
                if summaries:
                    guideline_summary = summaries[0]

            compact_findings.append({
                "gene": finding.get("gene", ""),
                "user_phenotype": finding.get("user_phenotype", ""),
                "risk_level": finding.get("risk_level", ""),
                "risk_label_tr": finding.get("risk_label_tr", ""),
                "effect_direction": finding.get("effect_direction", ""),
                "risk_meaning": finding.get("risk_meaning", ""),
                "plain_language": compact(finding.get("plain_language", ""), 700),
                "guideline_sources": guideline_sources,
                "guideline_summary": compact(guideline_summary, 700),
                "evidence_strength": finding.get("evidence_strength", ""),
            })

        compact_drugs.append({
            "drug": drug.get("drug", ""),
            "drug_behavior_hint": drug.get("drug_behavior_hint", ""),
            "overall_risk_level": drug.get("overall_risk_level", ""),
            "overall_risk_label_tr": drug.get("overall_risk_label_tr", ""),
            "findings": compact_findings,
        })

    return {
        "profile": {
            "profile_name": profile.get("profile_name", ""),
            "phenotypes": profile.get("phenotypes", {}),
        },
        "selected_drugs": data.get("selected_drugs", []),
        "overall_risk_level": data.get("overall_risk_level", ""),
        "overall_risk_label_tr": data.get("overall_risk_label_tr", ""),
        "risk_flag_count": data.get("risk_flag_count", 0),
        "drug_results": compact_drugs,
        "same_gene_attention": data.get("same_gene_attention", []),
        "must_include_warning": data.get("must_include_warning") or data.get("clinical_warning") or CLINICAL_WARNING_TR,
    }


# -----------------------------
# Prompt
# -----------------------------

SYSTEM_INSTRUCTION = """
Sen bir klinik karar verici değilsin. Bir farmakogenetik MVP prototipinin risk motoru çıktısını
Türkçe, anlaşılır, kısa ve klinik olmayan bir ön değerlendirme raporuna dönüştürüyorsun.

Kesin kurallar:
- Yeni tıbbi bilgi, yeni ilaç, yeni gen, yeni doz, yeni tedavi önerisi ekleme.
- Risk hesaplama yapma; verilen risk seviyelerini aynen kullan.
- "Şunu kullanmalı", "şunu bırakmalı", "doz şöyle olmalı" gibi öneri/emir cümleleri kurma.
- Guideline özetlerinde doz veya alternatif ilaç geçerse bunu doğrudan öneri gibi değil,
  "kaynak özetinde ... ifadesi yer alır" veya "bu nedenle klinik değerlendirme gerektirebilir" şeklinde nötr anlat.
- Her raporda açıkça şu uyarı yer almalı:
  "Bu çıktı klinik karar, doz önerisi veya tedavi önerisi değildir."
- Rapor Türkçe olmalı.
- Gereksiz uzun yazma; hackathon/MVP demosuna uygun netlikte yaz.
"""

USER_PROMPT_TEMPLATE = """
Aşağıdaki JSON, risk_engine.py tarafından hesaplanmış farmakogenetik MVP çıktısıdır.
Sen sadece bunu okunabilir rapora çevir.

İstenen çıktı formatı Markdown olsun:

# Farmakogenetik Ön Değerlendirme Raporu

## 1. Güvenlik Notu
Kısa uyarı.

## 2. Kullanılan Sentetik Profil
Profil adı ve gen-fenotip tablosu.

## 3. Genel Sonuç
Genel risk düzeyi ve risk bayrağı sayısı.

## 4. İlaç Bazlı Bulgular
Her ilaç için:
- Risk düzeyi
- İlgili gen/fenotip
- Etki yönünün sade açıklaması
- Kaynak/guideline var mı?
- Klinik karar olmadığını bozmadan dikkat notu

## 5. Aynı Gen Ekseninde Birden Fazla İlaç
Varsa kısaca açıkla. Doğrudan ilaç-ilaç etkileşimi iddiası kurma.

## 6. MVP Yorumu
Bu prototipin ne yaptığını 3-5 cümlede özetle:
genetik fenotip + ilaç listesi + ClinPGx kaynaklı edge/rule + açıklanabilir risk bayrağı.

## 7. Sınırlar
Klinik kullanım, gerçek genetik test, doz/tedavi önerisi, gerçek hasta verisi, eksik gen/ilaç kapsamı gibi sınırları kısaca belirt.

JSON:
```json
{payload_json}
```
"""


def build_prompt(payload: Dict[str, Any]) -> str:
    return USER_PROMPT_TEMPLATE.format(
        payload_json=json.dumps(payload, ensure_ascii=False, indent=2)
    )


# -----------------------------
# Gemini API
# -----------------------------

def call_gemini_api(
    prompt: str,
    model: str,
    api_key: Optional[str] = None,
    temperature: float = 0.2,
) -> Tuple[str, Dict[str, Any]]:
    """
    Google GenAI SDK ile generateContent çağrısı.
    google-genai kurulu değilse veya API patlarsa exception fırlatır.
    """
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:
        raise RuntimeError(
            "google-genai paketi import edilemedi. Kurulum: pip install -U google-genai"
        ) from exc

    client_kwargs = {}
    if api_key:
        client_kwargs["api_key"] = api_key

    client = genai.Client(**client_kwargs)

    # Yeni SDK'da config desteklenir. Farklı sürümde patlarsa fallback için dışarı exception atar.
    config = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=SYSTEM_INSTRUCTION,
    )

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=config,
    )

    text = getattr(response, "text", None)
    if not text:
        # Bazı response objelerinde text boş olabilir; yine de stringify edelim.
        text = str(response)

    metadata = {
        "provider": "google_gemini",
        "model": model,
        "temperature": temperature,
        "used_api": True,
    }

    return text.strip(), metadata


# -----------------------------
# Fallback report
# -----------------------------

def render_phenotype_table(profile: Dict[str, Any]) -> str:
    phenotypes = profile.get("phenotypes", {}) or {}
    lines = [
        "| Gen | Fenotip |",
        "|---|---|",
    ]
    for gene, pheno in phenotypes.items():
        lines.append(f"| {gene} | {pheno} |")
    return "\n".join(lines)


def render_fallback_report(payload: Dict[str, Any]) -> str:
    """
    Gemini API yoksa aynı formatta deterministik rapor üretir.
    """
    profile = payload.get("profile", {}) or {}
    warning = payload.get("must_include_warning") or CLINICAL_WARNING_TR

    lines: List[str] = []
    lines.append("# Farmakogenetik Ön Değerlendirme Raporu")
    lines.append("")
    lines.append("## 1. Güvenlik Notu")
    lines.append("")
    lines.append(warning)
    lines.append("")
    lines.append("Bu rapor, risk motoru çıktısını sadeleştiren MVP raporlama katmanıdır; klinik karar yerine geçmez.")
    lines.append("")
    lines.append("## 2. Kullanılan Sentetik Profil")
    lines.append("")
    lines.append(f"**Profil adı:** {profile.get('profile_name', 'Bilinmeyen profil')}")
    lines.append("")
    lines.append(render_phenotype_table(profile))
    lines.append("")
    lines.append("## 3. Genel Sonuç")
    lines.append("")
    lines.append(f"**Genel risk düzeyi:** {payload.get('overall_risk_label_tr', payload.get('overall_risk_level', ''))}")
    lines.append(f"**Risk bayrağı sayısı:** {payload.get('risk_flag_count', 0)}")
    lines.append("")
    lines.append(
        "Bu sonuç, seçilen ilaçların sentetik CYP fenotipiyle eşleştirilmesi sonucunda "
        "farmakogenetik açıdan dikkat gerektiren noktaları görünür hale getirir."
    )
    lines.append("")
    lines.append("## 4. İlaç Bazlı Bulgular")
    lines.append("")

    for drug in payload.get("drug_results", []) or []:
        drug_name = drug.get("drug", "")
        risk_label = drug.get("overall_risk_label_tr") or drug.get("overall_risk_level", "")
        findings = drug.get("findings", []) or []

        lines.append(f"### {drug_name}")
        lines.append("")
        lines.append(f"**Risk düzeyi:** {risk_label}")
        lines.append("")

        if not findings:
            lines.append("Bu ilaç için verilen profil altında aktif farmakogenetik risk bayrağı üretilmedi.")
            lines.append("")
            continue

        for finding in findings:
            gene = finding.get("gene", "")
            phenotype = finding.get("user_phenotype", "")
            effect = finding.get("effect_direction", "")
            meaning = finding.get("risk_meaning", "")
            plain = finding.get("plain_language", "")
            sources = finding.get("guideline_sources", []) or []
            summary = finding.get("guideline_summary", "")
            evidence = finding.get("evidence_strength", "")

            lines.append(f"#### {gene} / {phenotype}")
            lines.append("")
            lines.append(f"- **Bulgu düzeyi:** {finding.get('risk_label_tr', finding.get('risk_level', ''))}")
            if effect:
                lines.append(f"- **Etki yönü:** `{effect}`")
            if meaning:
                lines.append(f"- **Risk anlamı:** `{meaning}`")
            if plain:
                lines.append(f"- **Açıklama:** {plain}")
            if sources:
                lines.append(f"- **Kaynak tipi:** {', '.join(sources)}")
            if summary:
                lines.append(
                    "- **Guideline özeti:** "
                    + compact(summary, 550)
                    + " Bu ifade kaynak bilgisidir; bu rapor tedavi veya doz önerisi üretmez."
                )
            if evidence:
                lines.append(f"- **Kanıt etiketi:** `{evidence}`")
            lines.append("")

    same_gene = payload.get("same_gene_attention", []) or []
    lines.append("## 5. Aynı Gen Ekseninde Birden Fazla İlaç")
    lines.append("")
    if same_gene:
        for item in same_gene:
            lines.append(f"- **{item.get('gene', '')}:** {item.get('message', '')}")
    else:
        lines.append("Seçilen ilaçlar arasında aynı gen ekseni üzerinden ek bir dikkat notu üretilmedi.")
    lines.append("")
    lines.append("## 6. MVP Yorumu")
    lines.append("")
    lines.append(
        "Bu prototip, kullanıcının seçtiği sentetik CYP fenotip profilini seçilen ilaç listesiyle eşleştirir. "
        "ClinPGx kaynaklı gen–ilaç ilişkileri ve temizlenmiş MVP kural tablosu üzerinden açıklanabilir dikkat bayrakları üretir. "
        "Risk hesaplama Gemini tarafından değil, kural tabanlı risk motoru tarafından yapılır. "
        "Gemini veya fallback raporlayıcı yalnızca bu sonucu daha okunabilir Türkçe rapora çevirir."
    )
    lines.append("")
    lines.append("## 7. Sınırlar")
    lines.append("")
    lines.append(
        "- Bu çıktı gerçek hasta verisiyle doğrulanmış klinik karar sistemi değildir.\n"
        "- Doz, tedavi değişikliği veya ilaç alternatifi önermez.\n"
        "- Gerçek genetik test sonucu yerine sentetik CYP fenotip profili kullanır.\n"
        "- Kapsam, seed veri setindeki genler ve ilaçlarla sınırlıdır.\n"
        "- İlaç–ilaç etkileşimi iddiası kurmaz; yalnızca aynı gen eksenindeki dikkat noktalarını gösterir."
    )
    lines.append("")

    return "\n".join(lines)


# -----------------------------
# Main
# -----------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gemini report generator for ClinPGx MVP risk engine")
    parser.add_argument("--input", default="gemini_input.json", help="risk_engine.py çıktısı gemini_input.json")
    parser.add_argument("--out-dir", default="final_report", help="Rapor çıktı klasörü")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model adı. Varsayılan: {DEFAULT_MODEL}")
    parser.add_argument("--api-key", default=None, help="Gemini API key. Verilmezse GEMINI_API_KEY env kullanılır.")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--no-api", action="store_true", help="API çağrısı yapmadan fallback rapor üret.")
    parser.add_argument("--save-prompt", action="store_true", help="Gemini prompt'unu dosyaya kaydet.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_data = read_json(input_path)
    if not isinstance(raw_data, dict):
        raise ValueError("Input JSON kök objesi dict/object olmalı.")

    validation_warnings = validate_gemini_input(raw_data)
    payload = compact_for_prompt(raw_data)
    prompt = build_prompt(payload)

    write_json(out_dir / "gemini_report_payload.json", payload)

    if args.save_prompt:
        write_text(out_dir / "gemini_prompt.txt", prompt)

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    used_api = False
    report_text = ""
    error_message = ""

    if args.no_api:
        report_text = render_fallback_report(payload)
        metadata = {
            "used_api": False,
            "mode": "fallback_forced",
            "model": None,
        }
    else:
        if not api_key:
            error_message = "GEMINI_API_KEY bulunamadı; fallback rapor üretildi."
            report_text = render_fallback_report(payload)
            metadata = {
                "used_api": False,
                "mode": "fallback_no_api_key",
                "model": None,
                "error": error_message,
            }
        else:
            try:
                report_text, metadata = call_gemini_api(
                    prompt=prompt,
                    model=args.model,
                    api_key=api_key,
                    temperature=args.temperature,
                )
                used_api = True
            except Exception as exc:
                error_message = str(exc)
                report_text = render_fallback_report(payload)
                metadata = {
                    "used_api": False,
                    "mode": "fallback_api_error",
                    "model": args.model,
                    "error": error_message,
                }

    # Güvenlik uyarısı yoksa başa ekle.
    if "klinik karar" not in report_text.lower() or "doz önerisi" not in report_text.lower():
        report_text = (
            "# Farmakogenetik Ön Değerlendirme Raporu\n\n"
            "## Güvenlik Notu\n\n"
            f"{CLINICAL_WARNING_TR}\n\n"
            + report_text
        )

    write_text(out_dir / "gemini_report.md", report_text)

    status = {
        "created_at": now_iso(),
        "input_file": str(input_path),
        "output_file": str(out_dir / "gemini_report.md"),
        "validation_warnings": validation_warnings,
        "metadata": metadata,
        "used_api": used_api,
        "fallback_used": not used_api,
    }
    write_json(out_dir / "gemini_report_status.json", status)

    print("\n=== GEMINI REPORT DONE ===")
    if used_api:
        print(f"Gemini API kullanıldı. Model: {args.model}")
    else:
        print("Fallback rapor üretildi.")
        if error_message:
            print(f"Neden: {error_message}")

    if validation_warnings:
        print("\nUyarılar:")
        for w in validation_warnings:
            print(f"- {w}")

    print("\nÇıktılar:")
    print(f"- {out_dir / 'gemini_report.md'}")
    print(f"- {out_dir / 'gemini_report_payload.json'}")
    print(f"- {out_dir / 'gemini_report_status.json'}")


if __name__ == "__main__":
    main()
