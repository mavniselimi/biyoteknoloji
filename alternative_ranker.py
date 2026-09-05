#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
alternative_ranker.py

MVP-2 graph tabanli alternatif aday on siralama prototipi.

Bu script klinik karar, doz onerisi veya tedavi degisikligi onerisi uretmez.
Adaylari sadece ayni terapotik baglam veya ilac sinifi icinde, mevcut MVP
risk_engine.py dikkat bayragi mantigi ile karsilastirmali olarak siralar.

Ornek:
python alternative_ranker.py \
  --seed-dir clinpgx_mvp_seed \
  --source-drug clopidogrel \
  --profile-id P2_cyp2c19_poor \
  --current-drugs clopidogrel,voriconazole,codeine,warfarin,amitriptyline \
  --out-dir clinpgx_mvp_seed/alternative_outputs
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from risk_engine import (
    RISK_LABEL_TR,
    RISK_SCORE,
    analyze_profile_and_drugs,
    build_profile_from_args,
    load_seed_data,
    norm_key,
    split_drugs,
)


SAFETY_NOTICE = (
    "Bu bölümde listelenen alternatifler tedavi önerisi değildir. "
    "Aday ilaçlar yalnızca aynı terapötik bağlam veya ilaç sınıfı üzerinden "
    "farmakogenetik risk açısından ön sıralama yapmak amacıyla gösterilmiştir. "
    "Doz, ilaç değişimi veya tedavi kararı yalnızca hekim tarafından klinik tablo, "
    "endikasyon, laboratuvar değerleri ve güncel kılavuzlar dikkate alınarak verilmelidir."
)

DATA_LIMIT_NOTICE = (
    "Bu aday için mevcut MVP seed veri setinde yeterli gene-drug phenotype rule bulunmamaktadır. "
    "Bu nedenle düşük riskli olduğu sonucuna varılamaz; yalnızca mevcut seed kapsamında aktif bayrak "
    "saptanmadığı belirtilir."
)

INSUFFICIENT_PGX_RULE_NOTICE = (
    "Bu aday ClinPGx chemical olarak çözülmüş ve MVP seed içinde tanınır hale gelmiştir; ancak mevcut "
    "MVP kapsamında usable phenotype-effect rule bulunmadığı için adayın farmakogenetik açıdan düşük "
    "dikkatli olduğu sonucu çıkarılamaz."
)

UNSUPPORTED_CANDIDATE_NOTICE = (
    "Bu aday mevcut MVP seed veri setinde desteklenmediği için farmakogenetik açıdan düşük dikkatli "
    "olduğu sonucu çıkarılamaz. Skor yalnızca graph bağlamında aday bulunduğunu ve mevcut senaryoda "
    "kaynak ilacın çıkarılmasıyla kalan bayrak sayısını gösterir."
)

SCORE_NAME = "MVP alternatif uygunluk ön skoru"


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV bulunamadı: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def resolve_input_file(path_like: str, seed_dir: Path) -> Path:
    path = Path(path_like)
    candidates = [
        path,
        Path.cwd() / path_like,
        seed_dir / path_like,
        Path.cwd() / seed_dir / path_like,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = "\n".join(str(p) for p in candidates)
    raise FileNotFoundError(f"{path_like} bulunamadı. Denenen yollar:\n{tried}")


def find_candidates(candidate_rows: List[Dict[str, str]], source_drug: str) -> List[Dict[str, str]]:
    source_key = norm_key(source_drug)
    return [row for row in candidate_rows if norm_key(row.get("source_drug")) == source_key]


def replace_source_drug(current_drugs: List[str], source_drug: str, candidate_drug: str) -> List[str]:
    source_key = norm_key(source_drug)
    replaced = False
    out: List[str] = []
    for drug in current_drugs:
        if norm_key(drug) == source_key and not replaced:
            out.append(candidate_drug)
            replaced = True
        else:
            out.append(drug)
    if not replaced:
        out.insert(0, candidate_drug)
    return out


def risk_flags(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []
    for drug_result in result.get("drug_results", []) or []:
        for finding in drug_result.get("findings", []) or []:
            if finding.get("status") == "risk_flag":
                flags.append(finding)
    return flags


def find_drug_result(result: Dict[str, Any], drug: str) -> Optional[Dict[str, Any]]:
    drug_key = norm_key(drug)
    for drug_result in result.get("drug_results", []) or []:
        if norm_key(drug_result.get("drug")) == drug_key:
            return drug_result
    return None


def drug_specific_flags(drug_result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not drug_result:
        return []
    return [
        finding
        for finding in drug_result.get("findings", []) or []
        if finding.get("status") == "risk_flag"
    ]


def max_risk_level_from_flags(flags: Iterable[Dict[str, Any]]) -> str:
    max_score = 0
    for finding in flags:
        max_score = max(max_score, int(finding.get("risk_score") or RISK_SCORE.get(norm_key(finding.get("risk_level")), 0)))
    if max_score >= 3:
        return "high"
    if max_score == 2:
        return "medium"
    if max_score == 1:
        return "low"
    return "none"


def score_label(score: int) -> str:
    if score >= 80:
        return "düşük MVP dikkat / öncelikli incelenebilir aday"
    if score >= 60:
        return "orta MVP dikkat / ek değerlendirme gerekir"
    if score >= 50:
        return "veri sınırlı / yorum dikkatli yapılmalı"
    return "yüksek MVP dikkat veya veri kısıtı / düşük öncelikli aday"


def clamp_score(score: int) -> int:
    return max(0, min(100, score))


def candidate_data_status(seed: Any, candidate_drug: str) -> Tuple[str, bool, bool]:
    drug_info = seed.drug_by_key.get(norm_key(candidate_drug))
    if not drug_info:
        return "unsupported_candidate", False, False

    canonical = drug_info.get("drug") or drug_info.get("canonical_name") or candidate_drug
    has_rules = bool(seed.rules_by_drug.get(norm_key(canonical)))
    if not has_rules:
        return "insufficient_pgx_rule_data", True, False
    return "evaluated", True, True


def graph_edges_for(graph_rows: List[Dict[str, str]], drug: str) -> List[Dict[str, str]]:
    drug_key = norm_key(drug)
    return [row for row in graph_rows if norm_key(row.get("source")) == drug_key]


def graph_context(graph_rows: List[Dict[str, str]], drug: str) -> Dict[str, List[str]]:
    context: Dict[str, List[str]] = {}
    for row in graph_edges_for(graph_rows, drug):
        context.setdefault(row.get("edge_type", ""), [])
        target = row.get("target", "")
        if target:
            context[row.get("edge_type", "")].append(target)
    return context


def same_gene_attention_for_candidate(result: Dict[str, Any], candidate_drug: str) -> List[Dict[str, Any]]:
    candidate_key = norm_key(candidate_drug)
    notes = []
    for item in result.get("same_gene_attention", []) or []:
        drugs = item.get("drugs", []) or []
        if any(norm_key(drug) == candidate_key for drug in drugs):
            notes.append(item)
    return notes


def summarize_source_result(result: Dict[str, Any], source_drug: str) -> Dict[str, Any]:
    source_drug_result = find_drug_result(result, source_drug)
    source_flags = drug_specific_flags(source_drug_result)
    source_level = max_risk_level_from_flags(source_flags)
    return {
        "source_drug": source_drug,
        "overall_risk_level": result.get("overall_risk_level"),
        "overall_risk_label_tr": result.get("overall_risk_label_tr"),
        "risk_flag_count": result.get("risk_flag_count"),
        "source_specific_risk_level": source_level,
        "source_specific_risk_label_tr": RISK_LABEL_TR.get(source_level, source_level),
        "source_specific_risk_flag_count": len(source_flags),
        "source_findings": [
            {
                "gene": f.get("gene"),
                "user_phenotype": f.get("user_phenotype"),
                "risk_level": f.get("risk_level"),
                "effect_direction": f.get("effect_direction"),
                "risk_meaning": f.get("risk_meaning"),
                "plain_language": f.get("plain_language"),
            }
            for f in source_flags
        ],
    }


def evaluate_candidate(
    seed: Any,
    profile: Dict[str, Any],
    graph_rows: List[Dict[str, str]],
    source_drug: str,
    current_drugs: List[str],
    candidate_row: Dict[str, str],
    source_summary: Dict[str, Any],
) -> Dict[str, Any]:
    candidate = candidate_row.get("candidate_drug", "").strip()
    candidate_drugs = replace_source_drug(current_drugs, source_drug, candidate)
    candidate_result = analyze_profile_and_drugs(seed, profile, candidate_drugs)
    candidate_drug_result = find_drug_result(candidate_result, candidate)
    candidate_flags = drug_specific_flags(candidate_drug_result)
    candidate_specific_level = max_risk_level_from_flags(candidate_flags)
    same_gene_notes = same_gene_attention_for_candidate(candidate_result, candidate)

    data_status, is_supported, has_rules = candidate_data_status(seed, candidate)
    max_score_cap = 100
    if data_status == "unsupported_candidate":
        candidate_specific_level = "not_evaluable"
        candidate_specific_label = "Veri yetersiz / değerlendirilemedi"
        max_score_cap = 49
    elif data_status == "insufficient_pgx_rule_data":
        candidate_specific_level = "unknown"
        candidate_specific_label = "Veri yetersiz"
        max_score_cap = 59
    else:
        candidate_specific_label = RISK_LABEL_TR.get(candidate_specific_level, candidate_specific_level)

    score = 100
    penalties: List[str] = []
    source_specific_level = source_summary.get("source_specific_risk_level", "none")

    if source_specific_level == "high" and candidate_specific_level == "high":
        score -= 30
        penalties.append("source drug ile aynı yüksek dikkat riskini taşıyor")

    if candidate_specific_level == "high":
        score -= 30
        penalties.append("adayın kendisi için high risk_flag var")
    elif candidate_specific_level == "medium":
        score -= 15
        penalties.append("adayın kendisi için medium risk_flag var")
    elif candidate_specific_level == "low":
        score -= 5
        penalties.append("adayın kendisi için low risk_flag var")

    if not is_supported:
        score -= 20
        penalties.append("aday supported_drugs.csv içinde yok")

    if not has_rules:
        score -= 15
        penalties.append("aday için phenotype_effect_rules.csv içinde gene-drug veri yok")

    if same_gene_notes:
        score -= 10
        penalties.append("aynı gen ekseninde current_drugs ile çakışma görünüyor")

    score = min(clamp_score(score), max_score_cap)
    context = graph_context(graph_rows, candidate)

    return {
        "source_drug": source_drug,
        "candidate_drug": candidate,
        "reason": candidate_row.get("reason", ""),
        "evidence_level": candidate_row.get("evidence_level", ""),
        "notes": candidate_row.get("notes", ""),
        "candidate_drugs": candidate_drugs,
        "mvp_data_status": data_status,
        "is_supported_in_seed": is_supported,
        "has_phenotype_rules": has_rules,
        "max_score_cap": max_score_cap,
        "score": score,
        "score_name": SCORE_NAME,
        "score_label": score_label(score),
        "candidate_overall_risk_level": candidate_result.get("overall_risk_level", "none"),
        "candidate_overall_risk_label_tr": candidate_result.get("overall_risk_label_tr", ""),
        "candidate_risk_flag_count": candidate_result.get("risk_flag_count", 0),
        "candidate_specific_risk_level": candidate_specific_level,
        "candidate_specific_risk_label_tr": candidate_specific_label,
        "candidate_specific_risk_flag_count": len(candidate_flags),
        "same_gene_attention_count": len(same_gene_notes),
        "same_gene_attention": same_gene_notes,
        "penalties": penalties,
        "graph_context": context,
        "candidate_specific_findings": [
            {
                "gene": f.get("gene"),
                "risk_level": f.get("risk_level"),
                "risk_label_tr": f.get("risk_label_tr"),
                "effect_direction": f.get("effect_direction"),
                "risk_meaning": f.get("risk_meaning"),
                "plain_language": f.get("plain_language"),
                "evidence_strength": f.get("evidence_strength"),
            }
            for f in candidate_flags
        ],
    }


def rank_candidates(candidate_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(candidate_results, key=lambda r: (-int(r.get("score", 0)), norm_key(r.get("candidate_drug"))))


def rows_for_candidate_csv(ranked: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for index, item in enumerate(ranked, start=1):
        rows.append({
            "rank": index,
            "source_drug": item.get("source_drug", ""),
            "candidate_drug": item.get("candidate_drug", ""),
            "reason": item.get("reason", ""),
            "evidence_level": item.get("evidence_level", ""),
            "mvp_data_status": item.get("mvp_data_status", ""),
            "score": item.get("score", 0),
            "score_label": item.get("score_label", ""),
            "candidate_overall_risk_level": item.get("candidate_overall_risk_level", ""),
            "candidate_risk_flag_count": item.get("candidate_risk_flag_count", 0),
            "candidate_specific_risk_level": item.get("candidate_specific_risk_level", ""),
            "same_gene_attention_count": item.get("same_gene_attention_count", 0),
            "notes": item.get("notes", ""),
        })
    return rows


def render_context_line(context: Dict[str, List[str]]) -> str:
    if not context:
        return "Graph seed içinde bu aday için ek bağlam bulunamadı."
    parts = []
    for edge_type in sorted(context):
        targets = ", ".join(context[edge_type])
        parts.append(f"{edge_type}: {targets}")
    return "; ".join(parts)


def display_drug_name(value: str) -> str:
    return str(value or "").strip().capitalize()


def join_names_tr(names: List[str]) -> str:
    display_names = [display_drug_name(name) for name in names if name]
    if not display_names:
        return ""
    if len(display_names) == 1:
        return display_names[0]
    return ", ".join(display_names[:-1]) + " ve " + display_names[-1]


def render_markdown_report(payload: Dict[str, Any]) -> str:
    source = payload.get("source_drug", "")
    profile = payload.get("profile", {}) or {}
    source_summary = payload.get("source_result_summary", {}) or {}
    candidates = payload.get("candidate_results", []) or []

    lines: List[str] = []
    lines.append("# MVP-2 Alternatif Aday Ön Sıralama Raporu")
    lines.append("")
    lines.append("## Güvenlik Notu")
    lines.append("")
    lines.append(SAFETY_NOTICE)
    lines.append("")
    lines.append("## Girdi Özeti")
    lines.append("")
    lines.append(f"- **Kaynak ilaç:** {source}")
    lines.append(f"- **Profil ID:** {payload.get('profile_id', '')}")
    lines.append(f"- **Profil adı:** {profile.get('profile_name', '')}")
    lines.append(f"- **Mevcut ilaç listesi:** {', '.join(payload.get('current_drugs', []) or [])}")
    lines.append(f"- **Aday sayısı:** {len(candidates)}")
    lines.append("")
    lines.append("## Kaynak İlaç Risk Özeti")
    lines.append("")
    first_source_finding = (source_summary.get("source_findings", []) or [{}])[0]
    source_profile_text = "seçili profil"
    if first_source_finding.get("gene") and first_source_finding.get("user_phenotype"):
        source_profile_text = f"seçili {first_source_finding.get('gene')} {first_source_finding.get('user_phenotype')} profilde"
    lines.append(
        f"{source} için {source_profile_text} "
        f"{source_summary.get('source_specific_risk_label_tr', '')} farmakogenetik dikkat bayrağı oluşmuştur."
    )
    lines.append(
        "Aynı terapötik bağlamda değerlendirilebilecek adaylar seed veri setinden alınmıştır. "
        "Bu adaylar tedavi önerisi değildir. Mevcut MVP veri seti üzerinden adayların farmakogenetik "
        "dikkat durumu karşılaştırmalı olarak gösterilmiştir."
    )
    if source_summary.get("source_findings"):
        lines.append("")
        for finding in source_summary.get("source_findings", []):
            lines.append(
                f"- **{finding.get('gene', '')}:** {finding.get('plain_language', '')} "
                f"(`{finding.get('effect_direction', '')}`, `{finding.get('risk_meaning', '')}`)"
            )
    lines.append("")
    lines.append("## Alternatif Aday Sıralaması")
    lines.append("")
    lines.append("| Sıra | Aday | MVP veri durumu | MVP alternatif uygunluk ön skoru | Skor etiketi | Aday özel PGx değerlendirmesi | Senaryo dikkat düzeyi | Senaryo bayrak sayısı |")
    lines.append("|---:|---|---|---:|---|---|---|---:|")
    for index, item in enumerate(candidates, start=1):
        lines.append(
            f"| {index} | {item.get('candidate_drug', '')} | {item.get('mvp_data_status', '')} | "
            f"{item.get('score', 0)} | {item.get('score_label', '')} | "
            f"{item.get('candidate_specific_risk_label_tr', '')} | "
            f"{item.get('candidate_overall_risk_label_tr', '')} | {item.get('candidate_risk_flag_count', 0)} |"
        )
    lines.append("")
    lines.append("## Aday Bazlı Açıklamalar")
    lines.append("")
    for index, item in enumerate(candidates, start=1):
        lines.append(f"### {index}. {item.get('candidate_drug', '')}")
        lines.append("")
        lines.append(f"- **Gerekçe:** {item.get('reason', '')} ({item.get('evidence_level', '')})")
        lines.append(f"- **Graph bağlamı:** {render_context_line(item.get('graph_context', {}) or {})}")
        lines.append(f"- **MVP veri durumu:** `{item.get('mvp_data_status', '')}`")
        lines.append(f"- **{SCORE_NAME}:** {item.get('score', 0)}")
        lines.append(f"- **Skor etiketi:** {item.get('score_label', '')}")
        lines.append("")
        lines.append("**Aday özel PGx değerlendirmesi:**")
        lines.append("")
        lines.append(f"- {item.get('candidate_specific_risk_label_tr', '')}")
        lines.append(f"- Aday özel risk düzeyi kodu: `{item.get('candidate_specific_risk_level', '')}`")
        lines.append("")
        lines.append("**Aday kaynak ilacın yerine konulduğunda toplam senaryo:**")
        lines.append("")
        lines.append(f"- Toplam aktif bayrak sayısı: {item.get('candidate_risk_flag_count', 0)}")
        lines.append(f"- Genel senaryo dikkat düzeyi: {item.get('candidate_overall_risk_label_tr', '')}")
        if item.get("same_gene_attention_count", 0):
            lines.append(f"- **Aynı gen ekseni notu:** {item.get('same_gene_attention_count')} adet")
        if item.get("penalties"):
            lines.append(f"- **Skor ceza nedenleri:** {', '.join(item.get('penalties', []))}")
        else:
            lines.append("- **Skor ceza nedenleri:** Bu aday için MVP skor cezası oluşmadı.")
        if item.get("candidate_specific_findings"):
            for finding in item.get("candidate_specific_findings", []):
                lines.append(
                    f"- **{finding.get('gene', '')} bulgusu:** {finding.get('plain_language', '')}"
                )
        if item.get("mvp_data_status") == "unsupported_candidate":
            lines.append(f"- **Veri notu:** {UNSUPPORTED_CANDIDATE_NOTICE}")
        elif item.get("mvp_data_status") == "insufficient_pgx_rule_data":
            lines.append(f"- **Veri notu:** {INSUFFICIENT_PGX_RULE_NOTICE}")
        elif item.get("mvp_data_status") != "evaluated":
            lines.append(f"- **Veri notu:** {DATA_LIMIT_NOTICE}")
        lines.append("")
    lines.append("## Veri Kısıtları")
    lines.append("")
    lines.append("- Graph seed klinik eşdeğerlik iddiası taşımaz; yalnızca demo bağlamı sağlar.")
    lines.append("- Adaylar desteklenen MVP seed kapsamıyla sınırlı olarak değerlendirilir.")
    lines.append("- Aday seed içinde yoksa veya phenotype rule yoksa düşük riskli olduğu sonucuna varılamaz.")
    lines.append("- Skor klinik güvenlik değerlendirmesi değildir; yalnızca MVP alternatif uygunluk ön skoru olarak yorumlanmalıdır.")
    lines.append("- Gemini veya başka bir LLM bu sıralamada karar verici olarak kullanılmamıştır.")
    lines.append("")
    lines.append("## Sonuç")
    lines.append("")
    if candidates:
        top = candidates[0]
        top_score = top.get("score", 0)
        top_candidates = [item for item in candidates if item.get("score", 0) == top_score]
        top_names = [item.get("candidate_drug", "") for item in top_candidates]
        all_top_unsupported = all(item.get("mvp_data_status") == "unsupported_candidate" for item in top_candidates)
        all_top_insufficient = all(item.get("mvp_data_status") == "insufficient_pgx_rule_data" for item in top_candidates)
        if len(top_candidates) > 1 and all_top_unsupported:
            subject = "Her iki aday" if len(top_candidates) == 2 else "Bu adaylar"
            lines.append(
                f"{join_names_tr(top_names)} aynı skorla listelenmiştir. "
                f"{subject} da mevcut MVP seed kapsamında desteklenmediği için PGx açısından değerlendirilememiştir. "
                "Bu sonuç tedavi önerisi değildir; yalnızca mevcut MVP seed kapsamındaki veri durumunu ve graph tabanlı aday bağlamını gösterir."
            )
        elif len(top_candidates) > 1 and all_top_insufficient:
            subject = "Her iki aday" if len(top_candidates) == 2 else "Bu adaylar"
            lines.append(
                f"{join_names_tr(top_names)} aynı skorla listelenmiştir. "
                f"{subject} da ClinPGx chemical olarak çözülmüş ve MVP seed içinde tanınır hale gelmiştir; "
                "ancak usable phenotype-effect rule bulunmadığı için PGx açısından değerlendirilememiştir. "
                "Bu sonuç tedavi önerisi değildir; yalnızca mevcut MVP seed kapsamındaki veri durumunu ve graph tabanlı aday bağlamını gösterir."
            )
        elif len(top_candidates) > 1:
            lines.append(
                f"{join_names_tr(top_names)} aynı {SCORE_NAME} değeriyle listelenmiştir. "
                "Bu sonuç tedavi önerisi değildir; yalnızca mevcut MVP seed kapsamındaki farmakogenetik dikkat durumu ön sıralamasıdır."
            )
        else:
            lines.append(
                f"Bu çalıştırmada {source} için {len(candidates)} aday listelenmiştir. "
                f"En yüksek {SCORE_NAME} değeri {top.get('candidate_drug', '')} için {top_score} olarak hesaplanmıştır. "
                "Bu sonuç tedavi önerisi değildir; yalnızca mevcut MVP seed kapsamındaki farmakogenetik dikkat durumu ön sıralamasıdır."
            )
    else:
        lines.append(
            "Bu kaynak ilaç için candidate_alternatives.csv içinde aday bulunamadı. "
            "Bu durum klinik alternatif olmadığı anlamına gelmez; yalnızca MVP seed kapsamının sınırlı olduğunu gösterir."
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MVP-2 alternative candidate pre-ranker")
    parser.add_argument("--seed-dir", default="clinpgx_mvp_seed", help="MVP seed klasörü")
    parser.add_argument("--source-drug", required=True, help="Alternatif aday aranacak kaynak ilaç")
    parser.add_argument("--profile-id", default="P1_normal", help="mvp_demo_profiles.json içindeki profil ID")
    parser.add_argument("--current-drugs", required=True, help="Virgülle ayrılmış mevcut ilaç listesi")
    parser.add_argument("--candidate-file", default="candidate_alternatives.csv", help="Aday seed CSV dosyası")
    parser.add_argument("--graph-file", default="drug_graph_edges.csv", help="Graph edge seed CSV dosyası")
    parser.add_argument("--out-dir", default="clinpgx_mvp_seed/alternative_outputs", help="Çıktı klasörü")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_dir = Path(args.seed_dir)
    seed = load_seed_data(seed_dir)
    profile = build_profile_from_args(seed, args.profile_id, None)
    current_drugs = split_drugs(args.current_drugs)
    if not current_drugs:
        raise ValueError("--current-drugs boş olamaz.")

    candidate_file = resolve_input_file(args.candidate_file, seed_dir)
    graph_file = resolve_input_file(args.graph_file, seed_dir)
    candidate_rows = read_csv(candidate_file)
    graph_rows = read_csv(graph_file)

    source_candidates = find_candidates(candidate_rows, args.source_drug)
    current_result = analyze_profile_and_drugs(seed, profile, current_drugs)
    source_only_result = analyze_profile_and_drugs(seed, profile, [args.source_drug])
    source_summary = summarize_source_result(source_only_result, args.source_drug)
    source_summary["current_list_overall_risk_level"] = current_result.get("overall_risk_level")
    source_summary["current_list_risk_flag_count"] = current_result.get("risk_flag_count")

    evaluated = [
        evaluate_candidate(
            seed=seed,
            profile=profile,
            graph_rows=graph_rows,
            source_drug=args.source_drug,
            current_drugs=current_drugs,
            candidate_row=row,
            source_summary=source_summary,
        )
        for row in source_candidates
    ]
    ranked = rank_candidates(evaluated)

    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    payload = {
        "source_drug": args.source_drug,
        "profile_id": args.profile_id,
        "profile": profile,
        "current_drugs": current_drugs,
        "source_result_summary": source_summary,
        "candidate_results": ranked,
        "safety_notice": SAFETY_NOTICE,
        "score_name": SCORE_NAME,
        "candidate_file": str(candidate_file),
        "graph_file": str(graph_file),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "alternative_candidates.csv", rows_for_candidate_csv(ranked))
    write_json(out_dir / "alternative_result_full.json", payload)
    write_text(out_dir / "alternative_report.md", render_markdown_report(payload))

    print("\n=== ALTERNATIVE RANKING DONE ===")
    print(f"Source drug: {args.source_drug}")
    print(f"Profile: {profile.get('profile_name')}")
    print(f"Candidates: {len(ranked)}")
    for item in ranked:
        print(
            f"- #{item['rank']} {item['candidate_drug']}: "
            f"{item['score']} | {item['score_label']} | {item['mvp_data_status']}"
        )
    print("\nÇıktılar:")
    print(f"- {out_dir / 'alternative_candidates.csv'}")
    print(f"- {out_dir / 'alternative_result_full.json'}")
    print(f"- {out_dir / 'alternative_report.md'}")


if __name__ == "__main__":
    main()
