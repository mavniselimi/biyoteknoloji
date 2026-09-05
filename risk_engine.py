#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
risk_engine.py

ClinPGx MVP seed dosyalarını kullanarak sentetik CYP profili + seçilen ilaçlar için
farmakogenetik "dikkat bayrağı" üretir.

Girdi dosyaları:
- supported_genes.csv
- supported_drugs.csv
- drug_gene_guidelines.csv
- phenotype_effect_rules.csv
- mvp_demo_profiles.json

Örnek kullanım:
python risk_engine.py \
  --seed-dir clinpgx_mvp_seed \
  --profile-id P2_cyp2c19_poor \
  --drugs clopidogrel,voriconazole,amitriptyline \
  --out-dir risk_outputs

Listeleme:
python risk_engine.py --seed-dir clinpgx_mvp_seed --list-profiles
python risk_engine.py --seed-dir clinpgx_mvp_seed --list-drugs

ÖNEMLİ:
Bu script klinik karar, doz önerisi veya tedavi önerisi üretmez.
MVP içinde kaynaklı farmakogenetik dikkat bayrağı / ön değerlendirme üretir.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


CLINICAL_WARNING_TR = (
    "Bu çıktı klinik karar, doz önerisi veya tedavi önerisi değildir. "
    "ClinPGx kaynaklı veriler ve sentetik CYP profilleri kullanılarak oluşturulmuş "
    "açıklanabilir farmakogenetik ön değerlendirme / MVP dikkat bayrağıdır."
)

RISK_SCORE = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

RISK_LABEL_TR = {
    "none": "Düşük / uyarı yok",
    "low": "Düşük dikkat",
    "medium": "Orta dikkat",
    "high": "Yüksek dikkat",
}

EVIDENCE_RANK = {
    "high_guideline_supported": 5,
    "manual_mvp_rule": 4,
    "medium_variant_annotation": 3,
    "medium_low_variant_annotation": 2,
    "low_variant_annotation": 1,
    "exploratory": 0,
}

# Profil fenotipi ile rule fenotip grubunu eşleştirme.
# Sol taraf kullanıcının profili, sağ taraf kabul edilecek rule grupları.
PROFILE_MATCH_GROUPS = {
    "poor": {"poor", "decreased_function"},
    "intermediate": {"intermediate", "decreased_function"},
    # MVP güvenlik tercihi:
    # Normal fenotipte aktif risk bayrağı üretmiyoruz. ClinPGx ham verisinde
    # "normal metabolizer" çoğu zaman karşılaştırma grubu olarak geçtiği için,
    # bunu risk tetikleyici saymak yanlış pozitif üretebilir.
    "normal": set(),
    "rapid": {"rapid", "ultrarapid"},
    "ultrarapid": {"ultrarapid", "rapid"},
    "decreased_function": {"poor", "intermediate", "decreased_function"},
}


# -----------------------------
# Dosya yardımcıları
# -----------------------------

def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV bulunamadı: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        print(f"[SAVED EMPTY] {path}")
        return

    fieldnames: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[SAVED] {path} ({len(rows)} rows)")


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"JSON bulunamadı: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {path}")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"[SAVED] {path}")


def find_seed_file(seed_dir: Path, filename: str) -> Path:
    """
    Kullanıcı scripti proje kökünde, seed klasöründe veya direkt dosyaların olduğu yerde çalıştırabilir.
    Bu yüzden birkaç olası konumu deniyoruz.
    """
    candidates = [
        seed_dir / filename,
        Path.cwd() / filename,
        Path.cwd() / "clinpgx_mvp_seed" / filename,
        Path.cwd() / "clinpgx_outputs_v2" / filename,
        Path("/mnt/data") / filename,
    ]

    for path in candidates:
        if path.exists():
            return path

    tried = "\n".join(str(p) for p in candidates)
    raise FileNotFoundError(f"{filename} bulunamadı. Denenen yollar:\n{tried}")


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def norm_key(value: Any) -> str:
    return norm_text(value).lower()


def split_drugs(raw: str) -> List[str]:
    if not raw:
        return []
    parts = re.split(r"[,;|]", raw)
    return [norm_text(p) for p in parts if norm_text(p)]


def compact(value: Any, max_len: int = 900) -> str:
    text = norm_text(value)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


# -----------------------------
# Veri modeli
# -----------------------------

@dataclass
class SeedData:
    genes: List[Dict[str, str]]
    drugs: List[Dict[str, str]]
    guidelines: List[Dict[str, str]]
    rules: List[Dict[str, str]]
    profiles: Dict[str, Any]

    gene_by_key: Dict[str, Dict[str, str]]
    drug_by_key: Dict[str, Dict[str, str]]
    guidelines_by_pair: Dict[Tuple[str, str], List[Dict[str, str]]]
    rules_by_drug: Dict[str, List[Dict[str, str]]]


def load_seed_data(seed_dir: Path) -> SeedData:
    genes_path = find_seed_file(seed_dir, "supported_genes.csv")
    drugs_path = find_seed_file(seed_dir, "supported_drugs.csv")
    guidelines_path = find_seed_file(seed_dir, "drug_gene_guidelines.csv")
    rules_path = find_seed_file(seed_dir, "phenotype_effect_rules.csv")
    profiles_path = find_seed_file(seed_dir, "mvp_demo_profiles.json")

    print("[LOAD]", genes_path)
    genes = read_csv(genes_path)
    print("[LOAD]", drugs_path)
    drugs = read_csv(drugs_path)
    print("[LOAD]", guidelines_path)
    guidelines = read_csv(guidelines_path)
    print("[LOAD]", rules_path)
    rules = read_csv(rules_path)
    print("[LOAD]", profiles_path)
    profiles = read_json(profiles_path)

    gene_by_key = {}
    for row in genes:
        gene_by_key[norm_key(row.get("gene"))] = row
        gene_by_key[norm_key(row.get("gene_id"))] = row

    drug_by_key = {}
    for row in drugs:
        drug_by_key[norm_key(row.get("drug"))] = row
        drug_by_key[norm_key(row.get("canonical_name"))] = row
        drug_by_key[norm_key(row.get("drug_id"))] = row

    guidelines_by_pair: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for row in guidelines:
        pair = (norm_key(row.get("gene")), norm_key(row.get("drug")))
        guidelines_by_pair.setdefault(pair, []).append(row)

    rules_by_drug: Dict[str, List[Dict[str, str]]] = {}
    for row in rules:
        if norm_key(row.get("usable_for_mvp")) not in {"yes", "supporting_only"}:
            continue
        rules_by_drug.setdefault(norm_key(row.get("drug")), []).append(row)

    return SeedData(
        genes=genes,
        drugs=drugs,
        guidelines=guidelines,
        rules=rules,
        profiles=profiles,
        gene_by_key=gene_by_key,
        drug_by_key=drug_by_key,
        guidelines_by_pair=guidelines_by_pair,
        rules_by_drug=rules_by_drug,
    )


# -----------------------------
# Fenotip eşleştirme
# -----------------------------

def normalize_profile_phenotype(value: str) -> str:
    v = norm_key(value)

    if v in {"pm", "poor", "poor metabolizer", "zayif", "zayıf"}:
        return "poor"
    if v in {"im", "intermediate", "intermediate metabolizer", "orta"}:
        return "intermediate"
    if v in {"nm", "normal", "normal metabolizer"}:
        return "normal"
    if v in {"rm", "rapid", "rapid metabolizer", "hizli", "hızlı"}:
        return "rapid"
    if v in {"um", "ultrarapid", "ultra rapid", "ultrarapid metabolizer", "ultra-rapid metabolizer"}:
        return "ultrarapid"
    if "poor" in v:
        return "poor"
    if "intermediate" in v:
        return "intermediate"
    if "ultrarapid" in v or "ultra-rapid" in v:
        return "ultrarapid"
    if "rapid" in v:
        return "rapid"
    if "normal" in v:
        return "normal"
    if "decreased" in v:
        return "decreased_function"

    return v


def normalize_rule_group(value: str) -> str:
    v = norm_key(value)

    if v in {"poor", "intermediate", "normal", "rapid", "ultrarapid", "decreased_function"}:
        return v
    if "poor" in v:
        return "poor"
    if "intermediate" in v:
        return "intermediate"
    if "ultrarapid" in v or "ultra-rapid" in v:
        return "ultrarapid"
    if "rapid" in v:
        return "rapid"
    if "normal" in v:
        return "normal"
    if "decreased" in v:
        return "decreased_function"
    if "diplotype" in v or "haplotype" in v or "*" in v:
        return "diplotype_or_haplotype"
    if v:
        return v
    return ""


def phenotype_matches(profile_pheno: str, rule_group: str) -> bool:
    """
    Sentetik profil fenotipi ile rule fenotip grubunu eşleştirir.
    Diplotype/haplotype seviyesindeki ham literatür satırlarını sentetik profille otomatik eşleştirmiyoruz;
    onlar evidence olarak kalır, ana risk tetikleyici olmaz.
    """
    p = normalize_profile_phenotype(profile_pheno)
    r = normalize_rule_group(rule_group)

    if not p or not r:
        return False

    allowed = PROFILE_MATCH_GROUPS.get(p, {p})
    return r in allowed


def build_profile_from_args(seed: SeedData, profile_id: Optional[str], profile_json: Optional[str]) -> Dict[str, Any]:
    if profile_json:
        loaded = json.loads(profile_json)
        if "phenotypes" not in loaded:
            loaded = {
                "profile_name": "Custom profile",
                "phenotypes": loaded,
                "demo_use": "Komut satırından verilen özel profil.",
            }
        return loaded

    if not profile_id:
        # default: normal profil
        profile_id = "P1_normal"

    if profile_id not in seed.profiles:
        available = ", ".join(seed.profiles.keys())
        raise KeyError(f"Profil bulunamadı: {profile_id}. Mevcut profiller: {available}")

    return seed.profiles[profile_id]


# -----------------------------
# Risk hesaplama
# -----------------------------

def risk_rank(row: Dict[str, str]) -> Tuple[int, int, float, int]:
    """
    Gruplama sırasında aynı gene-drug-phenotype için en iyi temsilciyi seçmek.
    """
    risk_level = norm_key(row.get("demo_risk_level")) or "none"
    risk_score = RISK_SCORE.get(risk_level, 0)

    evidence = norm_key(row.get("evidence_strength"))
    evidence_score = EVIDENCE_RANK.get(evidence, 0)

    score = safe_float(row.get("score"), 0.0)

    source = norm_key(row.get("source_container"))
    manual_bonus = 1 if "manual" in source else 0

    return (risk_score, evidence_score, score, manual_bonus)


def choose_representative_rules(matched_rules: List[Dict[str, str]], max_evidence: int = 5) -> Tuple[Optional[Dict[str, str]], List[Dict[str, str]]]:
    if not matched_rules:
        return None, []

    # Aynı annotation'ın report/pair:variantAnnotation ve report/pair:VariantAnnotation tekrarlarını azalt.
    deduped = []
    seen = set()
    for r in matched_rules:
        marker = (
            norm_key(r.get("gene")),
            norm_key(r.get("drug")),
            norm_key(r.get("normalized_phenotype_group")),
            norm_key(r.get("effect_direction")),
            norm_key(r.get("risk_meaning")),
            norm_key(r.get("annotation_id")),
        )
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(r)

    deduped.sort(key=risk_rank, reverse=True)
    return deduped[0], deduped[:max_evidence]


def guideline_summary(guidelines: List[Dict[str, str]], max_items: int = 3) -> Dict[str, Any]:
    if not guidelines:
        return {
            "has_guideline": False,
            "sources": [],
            "guideline_summaries": [],
            "pmids": [],
            "dois": [],
        }

    # CPIC öne gelsin.
    ordered = sorted(
        guidelines,
        key=lambda r: (0 if norm_key(r.get("source")) == "cpic" else 1, norm_key(r.get("source")), norm_key(r.get("annotation_id"))),
    )

    sources = []
    summaries = []
    pmids = []
    dois = []
    annotation_ids = []

    for g in ordered[:max_items]:
        if g.get("source"):
            sources.append(g["source"])
        if g.get("summary"):
            summaries.append(compact(g["summary"], max_len=500))
        if g.get("pmids"):
            pmids.extend([x.strip() for x in str(g["pmids"]).split(";") if x.strip()])
        if g.get("dois"):
            dois.extend([x.strip() for x in str(g["dois"]).split(";") if x.strip()])
        if g.get("annotation_id"):
            annotation_ids.append(g["annotation_id"])

    return {
        "has_guideline": True,
        "sources": sorted(set(sources)),
        "annotation_ids": list(dict.fromkeys(annotation_ids)),
        "guideline_summaries": summaries,
        "pmids": list(dict.fromkeys(pmids)),
        "dois": list(dict.fromkeys(dois)),
    }


def analyze_drug(
    seed: SeedData,
    profile: Dict[str, Any],
    drug_input: str,
    max_evidence_per_finding: int = 5,
) -> Dict[str, Any]:
    drug_key = norm_key(drug_input)
    drug_info = seed.drug_by_key.get(drug_key)

    if not drug_info:
        return {
            "drug": drug_input,
            "status": "unsupported_drug",
            "overall_risk_level": "none",
            "overall_risk_score": 0,
            "findings": [],
            "message": "Bu ilaç seed veri setinde desteklenmiyor.",
        }

    drug_name = drug_info.get("drug") or drug_info.get("canonical_name") or drug_input
    canonical_key = norm_key(drug_name)
    rules = seed.rules_by_drug.get(canonical_key, [])

    if not rules:
        return {
            "drug": drug_name,
            "drug_id": drug_info.get("drug_id", ""),
            "status": "no_rules_for_drug",
            "overall_risk_level": "none",
            "overall_risk_score": 0,
            "findings": [],
            "message": "Bu ilaç için phenotype_effect_rules içinde aktif kural bulunamadı.",
        }

    phenotypes = profile.get("phenotypes", {})
    findings = []

    # İlaç için ilişkili gene'leri dolaş.
    genes_for_drug = sorted({r.get("gene", "") for r in rules if r.get("gene")})

    for gene in genes_for_drug:
        user_pheno_raw = phenotypes.get(gene)
        user_pheno = normalize_profile_phenotype(user_pheno_raw or "")

        pair_rules = [r for r in rules if norm_key(r.get("gene")) == norm_key(gene)]

        pair = (norm_key(gene), norm_key(drug_name))
        guidelines = seed.guidelines_by_pair.get(pair, [])
        guideline_info = guideline_summary(guidelines)

        if not user_pheno:
            findings.append({
                "gene": gene,
                "drug": drug_name,
                "status": "missing_profile_phenotype",
                "risk_level": "none",
                "risk_score": 0,
                "user_phenotype": "",
                "message": f"Profil içinde {gene} fenotipi bulunamadı.",
                "guideline": guideline_info,
            })
            continue

        matched = [
            r for r in pair_rules
            if phenotype_matches(user_pheno, r.get("normalized_phenotype_group", ""))
        ]

        representative, evidence_rows = choose_representative_rules(matched, max_evidence=max_evidence_per_finding)

        if representative is None:
            # Bu gene-drug ilişkisi var ama kullanıcının fenotipi için aktif uyarı yok.
            findings.append({
                "gene": gene,
                "gene_id": pair_rules[0].get("gene_id", "") if pair_rules else "",
                "drug": drug_name,
                "drug_id": drug_info.get("drug_id", ""),
                "status": "gene_drug_known_no_profile_match",
                "risk_level": "none",
                "risk_score": 0,
                "user_phenotype": user_pheno,
                "matched_rule_group": "",
                "effect_direction": "",
                "risk_meaning": "",
                "plain_language": f"{drug_name} için {gene} ilişkisi veri setinde var; ancak {user_pheno} fenotipi için MVP kuralı uyarı üretmedi.",
                "guideline": guideline_info,
                "evidence_count": 0,
                "evidence_examples": [],
            })
            continue

        risk_level = norm_key(representative.get("demo_risk_level")) or "medium"
        risk_score = RISK_SCORE.get(risk_level, 2)

        evidence_examples = []
        for row in evidence_rows:
            evidence_examples.append({
                "annotation_id": row.get("annotation_id", ""),
                "source_container": row.get("source_container", ""),
                "objCls": row.get("objCls", ""),
                "phenotype_or_genotype": row.get("phenotype_or_genotype", ""),
                "normalized_phenotype_group": row.get("normalized_phenotype_group", ""),
                "effect_direction": row.get("effect_direction", ""),
                "risk_meaning": row.get("risk_meaning", ""),
                "evidence_strength": row.get("evidence_strength", ""),
                "significance": row.get("significance", ""),
                "score": row.get("score", ""),
                "sentence": compact(row.get("evidence_sentence", ""), max_len=650),
                "pmids": row.get("pmids", ""),
                "dois": row.get("dois", ""),
            })

        plain_language = representative.get("plain_language_mvp") or representative.get("evidence_sentence") or ""
        if not plain_language:
            plain_language = f"{drug_name} ile {gene} arasında kullanıcının {user_pheno} fenotipi için farmakogenetik dikkat ilişkisi bulundu."

        findings.append({
            "gene": gene,
            "gene_id": representative.get("gene_id", ""),
            "drug": drug_name,
            "drug_id": drug_info.get("drug_id", ""),
            "status": "risk_flag",
            "risk_level": risk_level,
            "risk_label_tr": RISK_LABEL_TR.get(risk_level, risk_level),
            "risk_score": risk_score,
            "user_phenotype": user_pheno,
            "matched_rule_group": representative.get("normalized_phenotype_group", ""),
            "phenotype_or_genotype_source": representative.get("phenotype_or_genotype", ""),
            "drug_behavior_hint": representative.get("drug_behavior_hint", drug_info.get("drug_behavior_hint", "")),
            "effect_direction": representative.get("effect_direction", ""),
            "risk_meaning": representative.get("risk_meaning", ""),
            "plain_language": compact(plain_language, max_len=900),
            "guideline": guideline_info,
            "evidence_strength": representative.get("evidence_strength", ""),
            "evidence_count": len(evidence_rows),
            "evidence_examples": evidence_examples,
        })

    # İlacın genel riskini bul.
    max_score = max((f.get("risk_score", 0) for f in findings), default=0)
    if max_score >= 3:
        overall = "high"
    elif max_score == 2:
        overall = "medium"
    elif max_score == 1:
        overall = "low"
    else:
        overall = "none"

    return {
        "drug": drug_name,
        "drug_id": drug_info.get("drug_id", ""),
        "drug_behavior_hint": drug_info.get("drug_behavior_hint", ""),
        "status": "analyzed",
        "overall_risk_level": overall,
        "overall_risk_label_tr": RISK_LABEL_TR.get(overall, overall),
        "overall_risk_score": max_score,
        "findings": findings,
    }


def detect_same_gene_attention(drug_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Basit graph hissi: aynı gen üzerinden birden fazla seçili ilaç etkileniyorsa bunu raporda göster.
    Bu DDI iddiası değildir; sadece 'aynı farmakogenetik eksen' uyarısıdır.
    """
    gene_to_drugs: Dict[str, List[str]] = {}

    for dres in drug_results:
        if dres.get("status") != "analyzed":
            continue
        for finding in dres.get("findings", []):
            if finding.get("status") not in {"risk_flag", "gene_drug_known_no_profile_match"}:
                continue
            gene = finding.get("gene")
            drug = finding.get("drug")
            if gene and drug:
                gene_to_drugs.setdefault(gene, [])
                if drug not in gene_to_drugs[gene]:
                    gene_to_drugs[gene].append(drug)

    notes = []
    for gene, drugs in sorted(gene_to_drugs.items()):
        if len(drugs) >= 2:
            notes.append({
                "gene": gene,
                "drugs": drugs,
                "message": (
                    f"Seçilen ilaçlardan {', '.join(drugs)} aynı {gene} farmakogenetik ekseniyle ilişkilidir. "
                    "Bu bulgu doğrudan ilaç-ilaç etkileşimi iddiası değildir; MVP içinde aynı gen üzerinden birden fazla dikkat noktasını görünür kılar."
                ),
            })
    return notes


def analyze_profile_and_drugs(
    seed: SeedData,
    profile: Dict[str, Any],
    selected_drugs: List[str],
    max_evidence_per_finding: int = 5,
) -> Dict[str, Any]:
    drug_results = [
        analyze_drug(seed, profile, drug, max_evidence_per_finding=max_evidence_per_finding)
        for drug in selected_drugs
    ]

    max_score = max((d.get("overall_risk_score", 0) for d in drug_results), default=0)
    if max_score >= 3:
        overall = "high"
    elif max_score == 2:
        overall = "medium"
    elif max_score == 1:
        overall = "low"
    else:
        overall = "none"

    risk_flags = []
    for d in drug_results:
        for f in d.get("findings", []):
            if f.get("status") == "risk_flag":
                risk_flags.append(f)

    return {
        "clinical_warning": CLINICAL_WARNING_TR,
        "profile": profile,
        "selected_drugs": selected_drugs,
        "overall_risk_level": overall,
        "overall_risk_label_tr": RISK_LABEL_TR.get(overall, overall),
        "overall_risk_score": max_score,
        "risk_flag_count": len(risk_flags),
        "drug_results": drug_results,
        "same_gene_attention": detect_same_gene_attention(drug_results),
        "gemini_prompt_hint": (
            "Bu JSON'u klinik karar, doz veya tedavi önerisi üretmeden; "
            "farmakogenetik dikkat noktalarını açıklayan kısa, anlaşılır bir ön değerlendirme raporuna çevir."
        ),
    }


# -----------------------------
# Çıktı formatları
# -----------------------------

def flatten_findings_for_csv(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    profile_name = result.get("profile", {}).get("profile_name", "")

    for dres in result.get("drug_results", []):
        if not dres.get("findings"):
            rows.append({
                "profile_name": profile_name,
                "drug": dres.get("drug", ""),
                "drug_id": dres.get("drug_id", ""),
                "gene": "",
                "user_phenotype": "",
                "status": dres.get("status", ""),
                "risk_level": dres.get("overall_risk_level", ""),
                "risk_score": dres.get("overall_risk_score", ""),
                "effect_direction": "",
                "risk_meaning": "",
                "plain_language": dres.get("message", ""),
                "guideline_sources": "",
                "guideline_annotation_ids": "",
                "evidence_strength": "",
                "evidence_count": "",
            })
            continue

        for f in dres.get("findings", []):
            guideline = f.get("guideline", {}) or {}
            rows.append({
                "profile_name": profile_name,
                "drug": f.get("drug", dres.get("drug", "")),
                "drug_id": f.get("drug_id", dres.get("drug_id", "")),
                "gene": f.get("gene", ""),
                "gene_id": f.get("gene_id", ""),
                "user_phenotype": f.get("user_phenotype", ""),
                "status": f.get("status", ""),
                "risk_level": f.get("risk_level", ""),
                "risk_score": f.get("risk_score", ""),
                "effect_direction": f.get("effect_direction", ""),
                "risk_meaning": f.get("risk_meaning", ""),
                "plain_language": f.get("plain_language", f.get("message", "")),
                "guideline_sources": "; ".join(guideline.get("sources", []) or []),
                "guideline_annotation_ids": "; ".join(guideline.get("annotation_ids", []) or []),
                "guideline_summary": " | ".join(guideline.get("guideline_summaries", []) or []),
                "evidence_strength": f.get("evidence_strength", ""),
                "evidence_count": f.get("evidence_count", ""),
            })

    return rows


def render_markdown_report(result: Dict[str, Any]) -> str:
    profile = result.get("profile", {})
    lines: List[str] = []

    lines.append("# CYP450 Farmakogenetik MVP Risk Ön Değerlendirme Raporu")
    lines.append("")
    lines.append(f"**Genel sonuç:** {result.get('overall_risk_label_tr')}  ")
    lines.append(f"**Risk bayrağı sayısı:** {result.get('risk_flag_count', 0)}")
    lines.append("")
    lines.append(f"> {result.get('clinical_warning')}")
    lines.append("")

    lines.append("## Profil")
    lines.append("")
    lines.append(f"**Profil adı:** {profile.get('profile_name', 'Bilinmeyen profil')}")
    lines.append("")
    lines.append("| Gen | Fenotip |")
    lines.append("|---|---|")
    for gene, pheno in (profile.get("phenotypes", {}) or {}).items():
        lines.append(f"| {gene} | {pheno} |")
    lines.append("")

    lines.append("## İlaç Bazlı Bulgular")
    lines.append("")

    for dres in result.get("drug_results", []):
        lines.append(f"### {dres.get('drug')}")
        lines.append("")
        lines.append(f"**Genel ilaç riski:** {dres.get('overall_risk_label_tr', dres.get('overall_risk_level'))}")
        lines.append("")

        if dres.get("status") != "analyzed":
            lines.append(f"- {dres.get('message', 'Bu ilaç analiz edilemedi.')}")
            lines.append("")
            continue

        for f in dres.get("findings", []):
            gene = f.get("gene", "")
            status = f.get("status", "")

            if status == "risk_flag":
                lines.append(f"#### {gene} bulgusu")
                lines.append("")
                lines.append(f"- **Kullanıcı fenotipi:** {f.get('user_phenotype')}")
                lines.append(f"- **Risk düzeyi:** {f.get('risk_label_tr', f.get('risk_level'))}")
                lines.append(f"- **Etki yönü:** `{f.get('effect_direction')}`")
                lines.append(f"- **Risk anlamı:** `{f.get('risk_meaning')}`")
                lines.append(f"- **Açıklama:** {f.get('plain_language')}")
                guideline = f.get("guideline", {}) or {}
                if guideline.get("has_guideline"):
                    sources = ", ".join(guideline.get("sources", []) or [])
                    lines.append(f"- **Guideline kaynağı:** {sources or 'var'}")
                    summaries = guideline.get("guideline_summaries", []) or []
                    if summaries:
                        lines.append(f"- **Guideline özeti:** {summaries[0]}")
                if f.get("evidence_strength"):
                    lines.append(f"- **Kanıt tipi:** `{f.get('evidence_strength')}`")
                lines.append("")
            elif status == "gene_drug_known_no_profile_match":
                lines.append(f"- **{gene}:** Veri setinde gen–ilaç ilişkisi var, ancak bu profil fenotipi için aktif MVP uyarısı yok.")
            elif status == "missing_profile_phenotype":
                lines.append(f"- **{gene}:** Profil içinde fenotip bilgisi yok.")
            else:
                lines.append(f"- **{gene}:** {f.get('message', status)}")

        lines.append("")

    same_gene = result.get("same_gene_attention", []) or []
    if same_gene:
        lines.append("## Aynı Gen Ekseninde Birden Fazla İlaç")
        lines.append("")
        for note in same_gene:
            lines.append(f"- **{note.get('gene')}:** {note.get('message')}")
        lines.append("")

    lines.append("## Gemini'ye Gönderilecek Özet")
    lines.append("")
    lines.append("Bu rapordaki yapılandırılmış JSON çıktısı `gemini_input.json` içinde kaydedildi.")
    lines.append("Gemini sadece raporlama/sadeleştirme katmanı olarak kullanılmalı; risk hesaplama bu kural motorunda yapılmalıdır.")
    lines.append("")

    return "\n".join(lines)


def make_gemini_input(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gemini'ye gereksiz dev evidence listesi göndermeyelim.
    Sade, açıklanabilir, risk motoru çıktısı odaklı JSON verelim.
    """
    compact_drugs = []

    for dres in result.get("drug_results", []):
        compact_findings = []
        for f in dres.get("findings", []):
            if f.get("status") != "risk_flag":
                continue
            guideline = f.get("guideline", {}) or {}
            compact_findings.append({
                "gene": f.get("gene"),
                "user_phenotype": f.get("user_phenotype"),
                "risk_level": f.get("risk_level"),
                "risk_label_tr": f.get("risk_label_tr"),
                "effect_direction": f.get("effect_direction"),
                "risk_meaning": f.get("risk_meaning"),
                "plain_language": f.get("plain_language"),
                "guideline_sources": guideline.get("sources", []),
                "guideline_summary": (guideline.get("guideline_summaries", []) or [""])[0],
                "evidence_strength": f.get("evidence_strength"),
            })

        compact_drugs.append({
            "drug": dres.get("drug"),
            "drug_behavior_hint": dres.get("drug_behavior_hint"),
            "overall_risk_level": dres.get("overall_risk_level"),
            "overall_risk_label_tr": dres.get("overall_risk_label_tr"),
            "findings": compact_findings,
        })

    return {
        "task": (
            "Klinik karar veya doz önerisi vermeden, bu farmakogenetik MVP risk motoru çıktısını "
            "hekimin/öğrencinin okuyabileceği kısa Türkçe ön değerlendirme raporuna çevir."
        ),
        "must_include_warning": CLINICAL_WARNING_TR,
        "profile": result.get("profile"),
        "selected_drugs": result.get("selected_drugs"),
        "overall_risk_level": result.get("overall_risk_level"),
        "overall_risk_label_tr": result.get("overall_risk_label_tr"),
        "risk_flag_count": result.get("risk_flag_count"),
        "drug_results": compact_drugs,
        "same_gene_attention": result.get("same_gene_attention", []),
        "style": {
            "language": "tr",
            "tone": "clinical-but-not-prescriptive",
            "avoid": [
                "doz önerisi verme",
                "tedavi değişikliği önerme",
                "kesin klinik hüküm verme",
            ],
        },
    }


# -----------------------------
# CLI helpers
# -----------------------------

def print_profiles(seed: SeedData) -> None:
    print("\n=== Demo Profiller ===")
    for pid, profile in seed.profiles.items():
        print(f"\n{pid}")
        print(f"  Ad: {profile.get('profile_name')}")
        print(f"  Kullanım: {profile.get('demo_use')}")
        for gene, pheno in (profile.get("phenotypes", {}) or {}).items():
            print(f"    {gene}: {pheno}")


def print_drugs(seed: SeedData) -> None:
    print("\n=== Desteklenen İlaçlar ===")
    for row in sorted(seed.drugs, key=lambda r: norm_key(r.get("drug"))):
        print(
            f"- {row.get('drug')} "
            f"({row.get('drug_id')}) | {row.get('types')} | {row.get('mvp_supported')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClinPGx MVP risk engine")
    parser.add_argument("--seed-dir", default="clinpgx_mvp_seed", help="Seed dosyalarının klasörü.")
    parser.add_argument("--profile-id", default="P1_normal", help="mvp_demo_profiles.json içindeki profil ID.")
    parser.add_argument(
        "--profile-json",
        default=None,
        help='Özel profil JSON. Örn: \'{"CYP2C19":"poor","CYP2D6":"normal","CYP2C9":"intermediate"}\'',
    )
    parser.add_argument(
        "--drugs",
        default="clopidogrel,voriconazole,codeine,amitriptyline,warfarin",
        help="Virgülle ayrılmış ilaç listesi.",
    )
    parser.add_argument("--out-dir", default="risk_outputs", help="Çıktı klasörü.")
    parser.add_argument("--max-evidence", type=int, default=5, help="Her bulgu için saklanacak örnek evidence sayısı.")
    parser.add_argument("--list-profiles", action="store_true", help="Profil listesini gösterip çık.")
    parser.add_argument("--list-drugs", action="store_true", help="Desteklenen ilaçları gösterip çık.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed = load_seed_data(Path(args.seed_dir))

    if args.list_profiles:
        print_profiles(seed)
        return

    if args.list_drugs:
        print_drugs(seed)
        return

    profile = build_profile_from_args(seed, args.profile_id, args.profile_json)
    selected_drugs = split_drugs(args.drugs)

    if not selected_drugs:
        raise ValueError("--drugs boş olamaz. Örn: --drugs clopidogrel,codeine")

    result = analyze_profile_and_drugs(
        seed=seed,
        profile=profile,
        selected_drugs=selected_drugs,
        max_evidence_per_finding=args.max_evidence,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_json(out_dir / "risk_result_full.json", result)
    write_json(out_dir / "gemini_input.json", make_gemini_input(result))
    write_csv(out_dir / "risk_findings.csv", flatten_findings_for_csv(result))
    write_text(out_dir / "risk_report.md", render_markdown_report(result))

    print("\n=== ANALYSIS DONE ===")
    print(f"Profile: {profile.get('profile_name')}")
    print(f"Selected drugs: {', '.join(selected_drugs)}")
    print(f"Overall risk: {result.get('overall_risk_label_tr')} ({result.get('overall_risk_level')})")
    print(f"Risk flags: {result.get('risk_flag_count')}")
    print("\nAna çıktılar:")
    print(f"- {out_dir / 'risk_report.md'}")
    print(f"- {out_dir / 'risk_findings.csv'}")
    print(f"- {out_dir / 'risk_result_full.json'}")
    print(f"- {out_dir / 'gemini_input.json'}")


if __name__ == "__main__":
    main()
