#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_mvp_seed_dataset.py

ClinPGx V2 probe çıktılarından MVP için temiz seed dataset üretir.

Girdi beklenen dosyalar:
- resolved_genes.json / resolved_genes.csv
- resolved_chemicals.json / resolved_chemicals.csv
- pair_probe_raw.json
- mvp_candidate_drug_gene_edges.csv veya .json
- variant_annotation_filtered_raw.json veya variant_annotation_filtered_rows.csv

Çıktılar:
- supported_genes.csv
- supported_drugs.csv
- drug_gene_guidelines.csv
- phenotype_effect_rules.csv
- mvp_demo_profiles.json
- mvp_seed_summary.json

Klinik karar, doz veya tedavi önerisi üretmez.
Bu script sadece MVP veri katmanını temizler ve normalize eder.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# -----------------------------
# Genel ayarlar
# -----------------------------

HIGH_PRIORITY_GENES = {"CYP2C19", "CYP2D6", "CYP2C9"}
MEDIUM_PRIORITY_GENES = {"CYP3A4"}
LOW_PRIORITY_GENES = {"CYP1A2"}

# MVP'de en temiz ve jüriye en anlaşılır örnekleri öne alıyoruz.
PREFERRED_GENE_DRUG_PAIRS = {
    ("CYP2C19", "clopidogrel"),
    ("CYP2C19", "voriconazole"),
    ("CYP2C19", "amitriptyline"),
    ("CYP2C19", "citalopram"),
    ("CYP2C19", "sertraline"),
    ("CYP2D6", "codeine"),
    ("CYP2D6", "amitriptyline"),
    ("CYP2D6", "tamoxifen"),
    ("CYP2C9", "warfarin"),
    ("CYP3A4", "voriconazole"),
    ("CYP1A2", "amitriptyline"),
}

# ClinPGx'ten gelen ham cümleyi risk motorunun anlayacağı sınıflara yaklaştırmak için
# güvenli, demo amaçlı manuel override tablosu.
# Bu tablo klinik karar değildir; MVP risk açıklaması üretir.
MANUAL_EFFECT_HINTS: Dict[Tuple[str, str], Dict[str, Any]] = {
    ("CYP2C19", "clopidogrel"): {
        "drug_behavior": "prodrug_activation",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer"],
        "effect_direction": "decreased_activation",
        "risk_meaning": "reduced_response_attention",
        "risk_level": "high",
        "plain_language": (
            "CYP2C19 aktivitesi düşük olduğunda clopidogrel aktif metabolite daha az dönüşebilir; "
            "bu durum antiplatelet yanıtın azalması açısından dikkat gerektirir."
        ),
    },
    ("CYP2C19", "voriconazole"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer"],
        "effect_direction": "decreased_clearance",
        "risk_meaning": "increased_exposure_attention",
        "risk_level": "high",
        "plain_language": (
            "CYP2C19 aktivitesi düşük olduğunda voriconazole metabolizması azalabilir; "
            "maruziyet artışı açısından dikkat gerekir."
        ),
    },
    ("CYP2C19", "amitriptyline"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer"],
        "effect_direction": "altered_metabolism",
        "risk_meaning": "exposure_change_attention",
        "risk_level": "medium",
        "plain_language": (
            "CYP2C19 fenotipi amitriptyline metabolizmasını etkileyebilir; "
            "maruziyet değişimi açısından farmakogenetik dikkat bayrağı üretilebilir."
        ),
    },
    ("CYP2C19", "citalopram"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer"],
        "effect_direction": "altered_metabolism",
        "risk_meaning": "exposure_or_response_change_attention",
        "risk_level": "medium",
        "plain_language": (
            "CYP2C19 fenotipi citalopram yanıtı veya maruziyetiyle ilişkili olabilir; "
            "MVP düzeyinde dikkat bayrağı olarak gösterilir."
        ),
    },
    ("CYP2C19", "sertraline"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer"],
        "effect_direction": "altered_metabolism",
        "risk_meaning": "exposure_or_response_change_attention",
        "risk_level": "medium",
        "plain_language": (
            "CYP2C19 fenotipi sertraline yanıtı veya maruziyetiyle ilişkili olabilir; "
            "MVP düzeyinde dikkat bayrağı olarak gösterilir."
        ),
    },
    ("CYP2D6", "codeine"): {
        "drug_behavior": "prodrug_activation",
        "phenotypes": ["poor metabolizer", "ultrarapid metabolizer"],
        "effect_direction": "altered_activation",
        "risk_meaning": "reduced_effect_or_toxicity_attention",
        "risk_level": "high",
        "plain_language": (
            "Codeine CYP2D6 ile aktif metabolite dönüşen bir prodrug örneğidir; "
            "CYP2D6 poor veya ultrarapid fenotipleri etki azalması ya da toksisite açısından dikkat gerektirebilir."
        ),
    },
    ("CYP2D6", "tamoxifen"): {
        "drug_behavior": "prodrug_activation",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer"],
        "effect_direction": "decreased_activation",
        "risk_meaning": "reduced_active_metabolite_attention",
        "risk_level": "medium",
        "plain_language": (
            "CYP2D6 aktivitesi tamoxifen aktif metabolit oluşumu ile ilişkilidir; "
            "düşük CYP2D6 aktivitesi farmakogenetik dikkat bayrağı olarak işaretlenebilir."
        ),
    },
    ("CYP2D6", "amitriptyline"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer", "ultrarapid metabolizer"],
        "effect_direction": "altered_metabolism",
        "risk_meaning": "exposure_change_attention",
        "risk_level": "medium",
        "plain_language": (
            "CYP2D6 fenotipi amitriptyline metabolizmasını etkileyebilir; "
            "maruziyet veya yanıt değişimi açısından dikkat bayrağı üretilebilir."
        ),
    },
    ("CYP2C9", "warfarin"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["poor metabolizer", "intermediate metabolizer", "decreased function"],
        "effect_direction": "decreased_clearance",
        "risk_meaning": "increased_exposure_or_sensitivity_attention",
        "risk_level": "high",
        "plain_language": (
            "CYP2C9 fonksiyon azalması warfarin duyarlılığı ve maruziyet açısından dikkat gerektirebilir; "
            "MVP çıktısı klinik doz önerisi yerine ön uyarı üretir."
        ),
    },
    ("CYP3A4", "voriconazole"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["altered function"],
        "effect_direction": "possible_altered_metabolism",
        "risk_meaning": "low_confidence_attention",
        "risk_level": "low",
        "plain_language": (
            "CYP3A4-voriconazole ilişkisi MVP'de destekleyici örnek olarak tutulabilir; "
            "ana klinik demo için CYP2C19-voriconazole daha güçlüdür."
        ),
    },
    ("CYP1A2", "amitriptyline"): {
        "drug_behavior": "active_drug_clearance",
        "phenotypes": ["altered function"],
        "effect_direction": "possible_altered_metabolism",
        "risk_meaning": "low_confidence_attention",
        "risk_level": "low",
        "plain_language": (
            "CYP1A2-amitriptyline ilişkisi MVP'de düşük öncelikli destekleyici örnek olarak tutulabilir."
        ),
    },
}


# -----------------------------
# Dosya yardımcıları
# -----------------------------

def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {path}")


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
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
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[SAVED] {path} ({len(rows)} rows)")


def find_file(input_dir: Path, filename: str) -> Optional[Path]:
    candidates = [
        input_dir / filename,
        Path.cwd() / filename,
        Path.cwd() / "clinpgx_outputs_v2" / filename,
        Path.cwd() / "clinpgx_outputs" / filename,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_required_json(input_dir: Path, filename: str, default: Any = None) -> Any:
    p = find_file(input_dir, filename)
    if p is None:
        print(f"[WARN] Bulunamadı: {filename}")
        return default
    print(f"[LOAD] {p}")
    return read_json(p, default=default)


def load_optional_csv(input_dir: Path, filename: str) -> List[Dict[str, str]]:
    p = find_file(input_dir, filename)
    if p is None:
        print(f"[WARN] Bulunamadı: {filename}")
        return []
    print(f"[LOAD] {p}")
    return read_csv(p)


# -----------------------------
# Metin/JSON yardımcıları
# -----------------------------

def html_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("html", "")
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact(value: Any, max_len: int = 600) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def term(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("term") or obj.get("name") or obj.get("symbol") or obj.get("id") or "")
    return str(obj or "")


def list_terms(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, list):
        return "; ".join(term(v) for v in values if term(v))
    return term(values)


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def extract_related_names(items: Any, key: str = "name") -> List[str]:
    if not isinstance(items, list):
        return []
    out = []
    for x in items:
        if isinstance(x, dict):
            val = x.get(key) or x.get("symbol") or x.get("name") or x.get("id")
            if val:
                out.append(str(val))
    return out


def extract_related_ids(items: Any) -> List[str]:
    if not isinstance(items, list):
        return []
    return [str(x.get("id")) for x in items if isinstance(x, dict) and x.get("id")]


def extract_literature_info(literature: Any) -> Dict[str, str]:
    """
    GuidelineAnnotation içinde literature liste olabilir.
    VariantAnnotation içinde literature tek dict olabilir.
    """
    entries: List[Dict[str, Any]] = []
    if isinstance(literature, dict):
        entries = [literature]
    elif isinstance(literature, list):
        entries = [x for x in literature if isinstance(x, dict)]

    titles = []
    pmids = []
    dois = []
    years = []

    for lit in entries:
        if lit.get("title"):
            titles.append(str(lit["title"]))
        if lit.get("year"):
            years.append(str(lit["year"]))
        for cr in lit.get("crossReferences", []) or []:
            if not isinstance(cr, dict):
                continue
            resource = str(cr.get("resource", "")).lower()
            resource_id = str(cr.get("resourceId", ""))
            if resource == "pubmed" and resource_id:
                pmids.append(resource_id)
            elif resource == "doi" and resource_id:
                dois.append(resource_id)

    return {
        "literature_titles": " | ".join(dict.fromkeys(titles)),
        "pmids": "; ".join(dict.fromkeys(pmids)),
        "dois": "; ".join(dict.fromkeys(dois)),
        "years": "; ".join(dict.fromkeys(years)),
    }


def parse_pair_key(pair_key: str) -> Tuple[str, str]:
    if "::" in pair_key:
        a, b = pair_key.split("::", 1)
        return a.strip(), b.strip()
    return pair_key.strip(), ""


def is_exact_pair(annotation: Dict[str, Any], gene_id: str, drug_id: str, gene_symbol: str, drug_name: str) -> bool:
    related_gene_ids = set(extract_related_ids(annotation.get("relatedGenes")))
    related_drug_ids = set(extract_related_ids(annotation.get("relatedChemicals")))

    related_gene_symbols = {normalize_name(x) for x in extract_related_names(annotation.get("relatedGenes"), key="symbol")}
    related_drug_names = {normalize_name(x) for x in extract_related_names(annotation.get("relatedChemicals"), key="name")}

    gene_ok = gene_id in related_gene_ids or normalize_name(gene_symbol) in related_gene_symbols
    drug_ok = drug_id in related_drug_ids or normalize_name(drug_name) in related_drug_names

    return gene_ok and drug_ok


def annotation_id(annotation: Dict[str, Any]) -> str:
    return str(annotation.get("accessionId") or annotation.get("id") or "")


def dedupe_rows(rows: Iterable[Dict[str, Any]], key_fields: List[str]) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for row in rows:
        marker = tuple(str(row.get(k, "")) for k in key_fields)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out


# -----------------------------
# supported_genes / supported_drugs
# -----------------------------

def normalize_genes(resolved_genes: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for symbol, obj in sorted(resolved_genes.items()):
        if not isinstance(obj, dict):
            continue

        if symbol in HIGH_PRIORITY_GENES:
            priority = "high"
        elif symbol in MEDIUM_PRIORITY_GENES:
            priority = "medium"
        else:
            priority = "low"

        vip_summary_text = html_to_text((obj.get("vipSummary") or {}).get("html", ""))

        rows.append({
            "gene": symbol,
            "gene_id": obj.get("id", ""),
            "name": obj.get("name", ""),
            "cpicGene": obj.get("cpicGene", ""),
            "pharmVarGene": obj.get("pharmVarGene", ""),
            "alleleFile": obj.get("alleleFile", ""),
            "alleleFunctionSource": obj.get("alleleFunctionSource", ""),
            "alleleType": obj.get("alleleType", ""),
            "vipTier": obj.get("vipTier", ""),
            "mvp_priority": priority,
            "mvp_role": "core" if priority == "high" else "supporting",
            "notes": compact(vip_summary_text, max_len=700),
        })

    return rows


def normalize_drugs(resolved_chemicals: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []

    for drug_name, obj in sorted(resolved_chemicals.items()):
        if not isinstance(obj, dict):
            continue

        types = obj.get("types") or []
        types_str = "; ".join(types)

        if "Prodrug" in types:
            behavior = "prodrug_activation"
        else:
            behavior = "active_drug_or_general_drug"

        rows.append({
            "drug": drug_name,
            "drug_id": obj.get("id", ""),
            "canonical_name": obj.get("name", drug_name),
            "types": types_str,
            "drug_behavior_hint": behavior,
            "pediatric": obj.get("pediatric", ""),
            "mvp_supported": "yes" if drug_name in {d for _, d in PREFERRED_GENE_DRUG_PAIRS} else "candidate",
            "smiles": obj.get("smiles", ""),
        })

    return rows


# -----------------------------
# Guideline extraction
# -----------------------------

def guideline_to_row(
    pair_key: str,
    gene_symbol: str,
    drug_name: str,
    gene_id: str,
    drug_id: str,
    annotation: Dict[str, Any],
    source_container: str,
) -> Dict[str, Any]:
    summary = html_to_text(annotation.get("summaryMarkdown"))
    text = html_to_text(annotation.get("textMarkdown"))
    lit = extract_literature_info(annotation.get("literature"))

    return {
        "pair_key": pair_key,
        "gene": gene_symbol,
        "gene_id": gene_id,
        "drug": drug_name,
        "drug_id": drug_id,
        "annotation_id": annotation_id(annotation),
        "objCls": annotation.get("objCls", ""),
        "name": annotation.get("name", ""),
        "source": annotation.get("source", ""),
        "source_container": source_container,
        "recommendation": annotation.get("recommendation", ""),
        "dosingInformation": annotation.get("dosingInformation", ""),
        "alternateDrugAvailable": annotation.get("alternateDrugAvailable", ""),
        "hasTestingInfo": annotation.get("hasTestingInfo", ""),
        "pediatric": annotation.get("pediatric", ""),
        "otherPrescribingGuidance": annotation.get("otherPrescribingGuidance", ""),
        "summary": compact(summary, max_len=1200),
        "text_excerpt": compact(text, max_len=1500),
        "literature_titles": lit["literature_titles"],
        "pmids": lit["pmids"],
        "dois": lit["dois"],
        "years": lit["years"],
        "evidence_tier": "high_guideline",
        "usable_for_mvp": "yes",
    }


def extract_guidelines(pair_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    for pair_key, bundle in pair_raw.items():
        if not isinstance(bundle, dict):
            continue

        gene_symbol, drug_name = parse_pair_key(pair_key)
        gene = bundle.get("gene") or {}
        drug = bundle.get("drug") or {}
        gene_id = str(gene.get("id") or "")
        drug_id = str(drug.get("id") or "")

        # 1) query_guideline_annotations tarafından gelen guidelineAnnotation listesi
        for ann in bundle.get("guidelineAnnotation", []) or []:
            if not isinstance(ann, dict):
                continue
            if is_exact_pair(ann, gene_id, drug_id, gene_symbol, drug_name):
                rows.append(guideline_to_row(
                    pair_key, gene_symbol, drug_name, gene_id, drug_id, ann, "data/guidelineAnnotation"
                ))

        # 2) /report/pair resultType guidelineAnnotation / GuidelineAnnotation
        pair_block = bundle.get("pair") or {}
        for result_type in ["guidelineAnnotation", "GuidelineAnnotation"]:
            for ann in pair_block.get(result_type, []) or []:
                if not isinstance(ann, dict):
                    continue
                if is_exact_pair(ann, gene_id, drug_id, gene_symbol, drug_name):
                    rows.append(guideline_to_row(
                        pair_key, gene_symbol, drug_name, gene_id, drug_id, ann, f"report/pair:{result_type}"
                    ))

    rows = dedupe_rows(rows, ["gene_id", "drug_id", "annotation_id", "source"])
    rows.sort(key=lambda r: (
        0 if r.get("source") == "CPIC" else 1,
        r.get("gene", ""),
        r.get("drug", ""),
        r.get("annotation_id", ""),
    ))
    return rows


# -----------------------------
# Variant/effect extraction
# -----------------------------

def get_variant_items_from_pair_raw(pair_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []

    for pair_key, bundle in pair_raw.items():
        if not isinstance(bundle, dict):
            continue

        gene_symbol, drug_name = parse_pair_key(pair_key)
        gene = bundle.get("gene") or {}
        drug = bundle.get("drug") or {}
        gene_id = str(gene.get("id") or "")
        drug_id = str(drug.get("id") or "")

        pair_block = bundle.get("pair") or {}
        for result_type in ["variantAnnotation", "VariantAnnotation"]:
            for ann in pair_block.get(result_type, []) or []:
                if not isinstance(ann, dict):
                    continue
                # Pair endpoint zaten ilişki getirir; yine de exact kontrol yapıyoruz.
                # VariantAnnotation bazen relatedChemicals içinde birden çok drug taşır.
                related_drug_ids = set(extract_related_ids(ann.get("relatedChemicals")))
                if related_drug_ids and drug_id not in related_drug_ids:
                    continue
                enriched = dict(ann)
                enriched["_query_gene"] = gene_symbol
                enriched["_query_drug"] = drug_name
                enriched["_query_gene_id"] = gene_id
                enriched["_query_drug_id"] = drug_id
                enriched["_source_container"] = f"report/pair:{result_type}"
                items.append(enriched)

    return items


def get_variant_items_from_gene_raw(variant_raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []

    for gene_symbol, annotations in variant_raw.items():
        if not isinstance(annotations, list):
            continue
        for ann in annotations:
            if not isinstance(ann, dict):
                continue
            related_chemicals = ann.get("relatedChemicals") or []
            if not related_chemicals:
                continue
            for chem in related_chemicals:
                if not isinstance(chem, dict):
                    continue
                enriched = dict(ann)
                enriched["_query_gene"] = gene_symbol
                enriched["_query_drug"] = chem.get("name", "")
                enriched["_query_gene_id"] = ""
                enriched["_query_drug_id"] = chem.get("id", "")
                enriched["_source_container"] = "data/variantAnnotation"
                items.append(enriched)

    return items


def infer_phenotype(annotation: Dict[str, Any]) -> str:
    location = annotation.get("location") or {}
    if isinstance(location, dict):
        gp = term(location.get("genePhenotype"))
        if gp:
            return gp
        display = location.get("displayName")
        if display:
            return str(display)

    m1 = list_terms(annotation.get("metabolizers1"))
    if m1:
        return m1

    allele = annotation.get("alleleGenotype")
    if allele:
        return str(allele)

    return ""


def infer_effect_direction(sentence: str, polarity: str, drug_behavior_hint: str) -> str:
    s = normalize_name(sentence)
    p = normalize_name(polarity)

    if "active metabolite" in s and ("decreased" in s or "lower" in s or "reduced" in s):
        return "decreased_activation"
    if "activation" in s and ("decreased" in s or "reduced" in s):
        return "decreased_activation"
    if "response" in s and ("decreased" in s or "lower" in s or "reduced" in s):
        return "decreased_response"
    if "concentration" in s and ("increased" in s or "higher" in s):
        return "increased_concentration"
    if "metabolism" in s and ("decreased" in s or "lower" in s or "reduced" in s):
        return "decreased_metabolism"
    if "clearance" in s and ("decreased" in s or "lower" in s):
        return "decreased_clearance"
    if "formation of" in s and ("increased" in s or "higher" in s):
        return "increased_formation"

    if p == "decreased":
        if drug_behavior_hint == "prodrug_activation":
            return "decreased_activation_or_response"
        return "decreased_effect_or_exposure"
    if p == "increased":
        if drug_behavior_hint == "prodrug_activation":
            return "increased_activation_or_response"
        return "increased_effect_or_exposure"

    return "altered_effect_or_metabolism"


def infer_risk_meaning(effect_direction: str, drug_behavior_hint: str) -> str:
    if effect_direction in {"decreased_activation", "decreased_activation_or_response"}:
        return "reduced_effect_attention"
    if effect_direction in {"decreased_response"}:
        return "reduced_response_attention"
    if effect_direction in {"increased_concentration", "decreased_clearance", "decreased_metabolism"}:
        return "increased_exposure_attention"
    if effect_direction in {"increased_activation_or_response"}:
        return "increased_effect_or_toxicity_attention"
    if drug_behavior_hint == "prodrug_activation":
        return "activation_or_response_change_attention"
    return "exposure_or_response_change_attention"


def evidence_strength(source_container: str, significance: str, score: Any, has_guideline: bool) -> str:
    if has_guideline:
        return "high_guideline_supported"

    sig = normalize_name(significance)
    try:
        score_float = float(score or 0)
    except Exception:
        score_float = 0.0

    if sig == "yes" and score_float >= 1.5:
        return "medium_variant_annotation"
    if sig == "yes" and score_float > 0:
        return "medium_low_variant_annotation"
    if sig == "not stated" and score_float > 0:
        return "low_variant_annotation"
    return "exploratory"


def variant_to_effect_row(
    annotation: Dict[str, Any],
    drug_lookup: Dict[str, Dict[str, Any]],
    guideline_pairs: set[Tuple[str, str]],
) -> Optional[Dict[str, Any]]:
    gene = annotation.get("_query_gene", "")
    drug = annotation.get("_query_drug", "")
    gene_id = annotation.get("_query_gene_id", "")
    drug_id = annotation.get("_query_drug_id", "")
    source_container = annotation.get("_source_container", "")

    if not gene or not drug:
        return None

    if (gene, drug) not in PREFERRED_GENE_DRUG_PAIRS:
        # MVP ilk sürümde sadece seçtiğimiz anlaşılır çiftleri tutuyoruz.
        return None

    phenotype = infer_phenotype(annotation)
    sentence = annotation.get("sentence") or annotation.get("description") or ""
    polarity = term(annotation.get("polarity"))
    significance = term(annotation.get("significance"))
    score = annotation.get("score", "")

    drug_info = drug_lookup.get(normalize_name(drug), {})
    types = drug_info.get("types", "")
    drug_behavior_hint = "prodrug_activation" if "Prodrug" in str(types) else "active_drug_or_general_drug"

    manual = MANUAL_EFFECT_HINTS.get((gene, drug), {})
    effect_direction = manual.get("effect_direction") or infer_effect_direction(sentence, polarity, drug_behavior_hint)
    risk_meaning = manual.get("risk_meaning") or infer_risk_meaning(effect_direction, drug_behavior_hint)
    risk_level = manual.get("risk_level") or ("high" if "high" in evidence_strength(source_container, significance, score, (gene, drug) in guideline_pairs) else "medium")
    plain_language = manual.get("plain_language", "")

    lit = extract_literature_info(annotation.get("literature"))
    phenotype_categories = list_terms(annotation.get("phenotypeCategories"))

    ev_strength = evidence_strength(
        source_container=source_container,
        significance=significance,
        score=score,
        has_guideline=(gene, drug) in guideline_pairs,
    )

    # Klinik olmayan / negatif kayıtları ana effect rules'ta tutmayalım.
    if normalize_name(significance) == "no" and (gene, drug) not in guideline_pairs:
        return None

    return {
        "gene": gene,
        "gene_id": gene_id,
        "drug": drug,
        "drug_id": drug_id,
        "phenotype_or_genotype": phenotype,
        "normalized_phenotype_group": normalize_phenotype_group(phenotype),
        "drug_behavior_hint": drug_behavior_hint,
        "effect_direction": effect_direction,
        "risk_meaning": risk_meaning,
        "demo_risk_level": risk_level,
        "effect_polarity": polarity,
        "phenotype_category": phenotype_categories,
        "significance": significance,
        "score": score,
        "evidence_strength": ev_strength,
        "source_container": source_container,
        "annotation_id": annotation_id(annotation),
        "objCls": annotation.get("objCls", ""),
        "evidence_sentence": compact(sentence, max_len=1200),
        "plain_language_mvp": plain_language,
        "literature_titles": lit["literature_titles"],
        "pmids": lit["pmids"],
        "dois": lit["dois"],
        "years": lit["years"],
        "usable_for_mvp": "yes" if ev_strength != "exploratory" else "supporting_only",
    }


def normalize_phenotype_group(phenotype: str) -> str:
    p = normalize_name(phenotype)

    if "poor metabolizer" in p or " pm" in p or p.endswith("pm"):
        return "poor"
    if "intermediate metabolizer" in p or " im" in p or p.endswith("im"):
        return "intermediate"
    if "normal metabolizer" in p or " nm" in p or p.endswith("nm"):
        return "normal"
    if "rapid metabolizer" in p and "ultra" not in p:
        return "rapid"
    if "ultrarapid metabolizer" in p or "ultra-rapid metabolizer" in p or " um" in p or p.endswith("um"):
        return "ultrarapid"
    if "decreased function" in p:
        return "decreased_function"
    if "*" in p:
        return "diplotype_or_haplotype"
    if p:
        return "other"
    return ""


def build_manual_rule_rows(
    guideline_pairs: set[Tuple[str, str]],
    gene_id_lookup: Dict[str, str],
    drug_id_lookup: Dict[str, str],
    drug_lookup: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Her güçlü gene-drug çifti için en az bir temiz MVP kuralı garanti eder.
    Böylece variantAnnotation satırı eksik/karmaşık olsa bile demo çalışır.
    """
    rows = []

    for (gene, drug), rule in MANUAL_EFFECT_HINTS.items():
        if (gene, drug) not in PREFERRED_GENE_DRUG_PAIRS:
            continue

        drug_info = drug_lookup.get(normalize_name(drug), {})
        drug_behavior_hint = rule.get("drug_behavior") or drug_info.get("drug_behavior_hint", "")

        for phenotype in rule.get("phenotypes", ["altered function"]):
            rows.append({
                "gene": gene,
                "gene_id": gene_id_lookup.get(gene, ""),
                "drug": drug,
                "drug_id": drug_id_lookup.get(normalize_name(drug), ""),
                "phenotype_or_genotype": phenotype,
                "normalized_phenotype_group": normalize_phenotype_group(phenotype),
                "drug_behavior_hint": drug_behavior_hint,
                "effect_direction": rule.get("effect_direction", ""),
                "risk_meaning": rule.get("risk_meaning", ""),
                "demo_risk_level": rule.get("risk_level", "medium"),
                "effect_polarity": "",
                "phenotype_category": "MVP normalized rule",
                "significance": "",
                "score": "",
                "evidence_strength": "high_guideline_supported" if (gene, drug) in guideline_pairs else "manual_mvp_rule",
                "source_container": "manual_normalization_from_clinpgx_outputs",
                "annotation_id": "",
                "objCls": "MVP Rule",
                "evidence_sentence": "",
                "plain_language_mvp": rule.get("plain_language", ""),
                "literature_titles": "",
                "pmids": "",
                "dois": "",
                "years": "",
                "usable_for_mvp": "yes",
            })

    return rows


def build_effect_rules(
    pair_raw: Dict[str, Any],
    variant_raw: Dict[str, Any],
    guidelines: List[Dict[str, Any]],
    drug_rows: List[Dict[str, Any]],
    gene_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    guideline_pairs = {(r["gene"], r["drug"]) for r in guidelines}

    drug_lookup = {normalize_name(r["drug"]): r for r in drug_rows}
    gene_id_lookup = {r["gene"]: r["gene_id"] for r in gene_rows}
    drug_id_lookup = {normalize_name(r["drug"]): r["drug_id"] for r in drug_rows}

    variant_items = get_variant_items_from_pair_raw(pair_raw)
    variant_items += get_variant_items_from_gene_raw(variant_raw)

    rows: List[Dict[str, Any]] = []
    for item in variant_items:
        row = variant_to_effect_row(item, drug_lookup, guideline_pairs)
        if row:
            rows.append(row)

    manual_rows = build_manual_rule_rows(guideline_pairs, gene_id_lookup, drug_id_lookup, drug_lookup)
    rows.extend(manual_rows)

    rows = dedupe_rows(rows, [
        "gene", "drug", "phenotype_or_genotype", "effect_direction", "risk_meaning", "annotation_id", "source_container"
    ])

    # Öncelik sırası: guideline destekli ve manual normalized rule önce.
    def rank(row: Dict[str, Any]) -> Tuple[int, int, float, str, str]:
        strength = row.get("evidence_strength", "")
        if strength == "high_guideline_supported":
            tier = 0
        elif strength == "manual_mvp_rule":
            tier = 1
        elif "medium" in strength:
            tier = 2
        elif "low" in strength:
            tier = 3
        else:
            tier = 4

        usable = 0 if row.get("usable_for_mvp") == "yes" else 1
        try:
            score = -float(row.get("score") or 0)
        except Exception:
            score = 0.0

        return (tier, usable, score, row.get("gene", ""), row.get("drug", ""))

    rows.sort(key=rank)
    return rows


# -----------------------------
# Demo profiles
# -----------------------------

def build_demo_profiles() -> Dict[str, Any]:
    return {
        "P1_normal": {
            "profile_name": "Normal metabolizma profili",
            "phenotypes": {
                "CYP2C19": "normal",
                "CYP2D6": "normal",
                "CYP2C9": "normal",
                "CYP3A4": "normal",
                "CYP1A2": "normal",
            },
            "demo_use": "Kontrol senaryosu; risk motorunun normal profilde daha az uyarı üretmesini göstermek için.",
        },
        "P2_cyp2c19_poor": {
            "profile_name": "CYP2C19 poor metabolizer profili",
            "phenotypes": {
                "CYP2C19": "poor",
                "CYP2D6": "normal",
                "CYP2C9": "normal",
                "CYP3A4": "normal",
                "CYP1A2": "normal",
            },
            "demo_use": "Clopidogrel veya voriconazole gibi CYP2C19 ilişkili ilaçlarda farmakogenetik uyarı göstermek için.",
        },
        "P3_cyp2d6_poor": {
            "profile_name": "CYP2D6 poor metabolizer profili",
            "phenotypes": {
                "CYP2C19": "normal",
                "CYP2D6": "poor",
                "CYP2C9": "normal",
                "CYP3A4": "normal",
                "CYP1A2": "normal",
            },
            "demo_use": "Codeine, tamoxifen veya amitriptyline gibi CYP2D6 ilişkili ilaçlarda dikkat bayrağı göstermek için.",
        },
        "P4_cyp2d6_ultrarapid": {
            "profile_name": "CYP2D6 ultrarapid metabolizer profili",
            "phenotypes": {
                "CYP2C19": "normal",
                "CYP2D6": "ultrarapid",
                "CYP2C9": "normal",
                "CYP3A4": "normal",
                "CYP1A2": "normal",
            },
            "demo_use": "Prodrug aktivasyonu ve olası yüksek aktivite senaryosunu göstermek için.",
        },
        "P5_cyp2c9_decreased": {
            "profile_name": "CYP2C9 decreased/intermediate fonksiyon profili",
            "phenotypes": {
                "CYP2C19": "normal",
                "CYP2D6": "normal",
                "CYP2C9": "intermediate",
                "CYP3A4": "normal",
                "CYP1A2": "normal",
            },
            "demo_use": "Warfarin gibi CYP2C9 ilişkili ilaçlarda maruziyet/duyarlılık dikkat bayrağı göstermek için.",
        },
        "P6_mixed_high_attention": {
            "profile_name": "Karışık yüksek dikkat profili",
            "phenotypes": {
                "CYP2C19": "poor",
                "CYP2D6": "poor",
                "CYP2C9": "intermediate",
                "CYP3A4": "normal",
                "CYP1A2": "normal",
            },
            "demo_use": "Birden fazla gen–ilaç uyarısının aynı raporda nasıl göründüğünü göstermek için.",
        },
    }


# -----------------------------
# Özet ve main
# -----------------------------

def build_summary(
    gene_rows: List[Dict[str, Any]],
    drug_rows: List[Dict[str, Any]],
    guideline_rows: List[Dict[str, Any]],
    effect_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    guideline_pairs = sorted({f"{r['gene']}::{r['drug']}" for r in guideline_rows})
    effect_pairs = sorted({f"{r['gene']}::{r['drug']}" for r in effect_rows if r.get("usable_for_mvp") == "yes"})

    risk_counts: Dict[str, int] = {}
    for row in effect_rows:
        risk = row.get("demo_risk_level", "") or "unknown"
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    evidence_counts: Dict[str, int] = {}
    for row in effect_rows:
        ev = row.get("evidence_strength", "") or "unknown"
        evidence_counts[ev] = evidence_counts.get(ev, 0) + 1

    return {
        "created_by": "clean_mvp_seed_dataset.py",
        "purpose": "ClinPGx V2 probe çıktılarından MVP için temiz seed dataset üretimi",
        "clinical_warning": (
            "Bu çıktılar klinik karar, doz önerisi veya tedavi önerisi değildir. "
            "MVP içinde kaynaklı farmakogenetik dikkat bayrağı üretmek için kullanılmalıdır."
        ),
        "counts": {
            "supported_genes": len(gene_rows),
            "supported_drugs": len(drug_rows),
            "guideline_rows": len(guideline_rows),
            "effect_rule_rows": len(effect_rows),
            "guideline_gene_drug_pairs": len(guideline_pairs),
            "usable_effect_gene_drug_pairs": len(effect_pairs),
        },
        "guideline_pairs": guideline_pairs,
        "effect_pairs": effect_pairs,
        "risk_counts": risk_counts,
        "evidence_counts": evidence_counts,
        "recommended_mvp_core": [
            "CYP2C19 + clopidogrel",
            "CYP2C19 + voriconazole",
            "CYP2D6 + codeine",
            "CYP2D6 + amitriptyline",
            "CYP2C9 + warfarin",
        ],
        "next_step": (
            "Bu seed dosyalarını risk_engine.py veya Streamlit/Django arayüzüne bağla: "
            "profile phenotypes + selected drugs -> phenotype_effect_rules eşleşmesi -> risk report."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClinPGx V2 çıktılarından MVP seed dataset üretir.")
    parser.add_argument(
        "--input-dir",
        default="clinpgx_outputs_v2",
        help="V2 çıktılarının bulunduğu klasör. Varsayılan: clinpgx_outputs_v2",
    )
    parser.add_argument(
        "--out-dir",
        default="clinpgx_mvp_seed",
        help="Temiz seed çıktılarının yazılacağı klasör. Varsayılan: clinpgx_mvp_seed",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)

    print("=== ClinPGx MVP Seed Cleaner ===")
    print(f"Input dir : {input_dir.resolve()}")
    print(f"Output dir: {out_dir.resolve()}")

    resolved_genes = load_required_json(input_dir, "resolved_genes.json", default={}) or {}
    resolved_chemicals = load_required_json(input_dir, "resolved_chemicals.json", default={}) or {}
    pair_raw = load_required_json(input_dir, "pair_probe_raw.json", default={}) or {}
    variant_raw = load_required_json(input_dir, "variant_annotation_filtered_raw.json", default={}) or {}

    if not resolved_genes:
        raise FileNotFoundError("resolved_genes.json bulunamadı veya boş.")
    if not resolved_chemicals:
        raise FileNotFoundError("resolved_chemicals.json bulunamadı veya boş.")
    if not pair_raw:
        raise FileNotFoundError("pair_probe_raw.json bulunamadı veya boş.")

    print("\n=== Normalize supported genes/drugs ===")
    gene_rows = normalize_genes(resolved_genes)
    drug_rows = normalize_drugs(resolved_chemicals)

    print("\n=== Extract exact gene-drug guidelines ===")
    guideline_rows = extract_guidelines(pair_raw)

    print("\n=== Build phenotype effect rules ===")
    effect_rows = build_effect_rules(
        pair_raw=pair_raw,
        variant_raw=variant_raw,
        guidelines=guideline_rows,
        drug_rows=drug_rows,
        gene_rows=gene_rows,
    )

    print("\n=== Build demo profiles ===")
    demo_profiles = build_demo_profiles()

    print("\n=== Save outputs ===")
    write_csv(out_dir / "supported_genes.csv", gene_rows)
    write_csv(out_dir / "supported_drugs.csv", drug_rows)
    write_csv(out_dir / "drug_gene_guidelines.csv", guideline_rows)
    write_csv(out_dir / "phenotype_effect_rules.csv", effect_rows)
    write_json(out_dir / "mvp_demo_profiles.json", demo_profiles)

    summary = build_summary(gene_rows, drug_rows, guideline_rows, effect_rows)
    write_json(out_dir / "mvp_seed_summary.json", summary)

    print("\n=== DONE ===")
    print("Üretilen ana dosyalar:")
    print(f"- {out_dir / 'supported_genes.csv'}")
    print(f"- {out_dir / 'supported_drugs.csv'}")
    print(f"- {out_dir / 'drug_gene_guidelines.csv'}")
    print(f"- {out_dir / 'phenotype_effect_rules.csv'}")
    print(f"- {out_dir / 'mvp_demo_profiles.json'}")
    print(f"- {out_dir / 'mvp_seed_summary.json'}")

    print("\nKısa özet:")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
