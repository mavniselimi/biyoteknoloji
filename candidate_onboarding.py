#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
candidate_onboarding.py

MVP-2-beta candidate onboarding katmani.

candidate_alternatives.csv icindeki aday ilaclari mevcut MVP seed veri katmanina
kontrollu sekilde dahil etmeye calisir. Bu script klinik karar, doz onerisi,
tedavi degisikligi onerisi veya PGx risk kurali uretmez.

Varsayilan calisma seed dosyalarini overwrite etmez; yalnizca extension ve rapor
dosyalari uretir. --merge verilirse duplicate kontroluyle seed'e ekleme yapar.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


BASE_URL = "https://api.clinpgx.org/v1"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pgx-mvp-candidate-onboarding/0.1",
}

SAFETY_NOTICE = (
    "Bu rapor klinik karar, doz önerisi veya tedavi değişikliği önerisi değildir. "
    "Aday ilaçlar yalnızca MVP veri setinde değerlendirilebilir hale getirme amacıyla incelenmiştir."
)

CHEMICAL_RESOLVE_NOTICE = (
    "Adayın ClinPGx chemical olarak çözülmesi, o adayın farmakogenetik açıdan düşük riskli olduğu "
    "anlamına gelmez. Yalnızca MVP veri setinde değerlendirilebilir hale getirme adımıdır."
)

NO_RULE_NOTICE = (
    "Bu aday ClinPGx chemical olarak çözüldü; ancak mevcut MVP seed kapsamında farmakogenetik "
    "phenotype rule bulunamadı."
)

SUPPORTED_DRUG_COLUMNS = [
    "drug",
    "drug_id",
    "canonical_name",
    "types",
    "drug_behavior_hint",
    "pediatric",
    "mvp_supported",
    "smiles",
]

GUIDELINE_COLUMNS = [
    "pair_key",
    "gene",
    "gene_id",
    "drug",
    "drug_id",
    "annotation_id",
    "objCls",
    "name",
    "source",
    "source_container",
    "recommendation",
    "dosingInformation",
    "alternateDrugAvailable",
    "hasTestingInfo",
    "pediatric",
    "otherPrescribingGuidance",
    "summary",
    "text_excerpt",
    "literature_titles",
    "pmids",
    "dois",
    "years",
    "evidence_tier",
    "usable_for_mvp",
]

ANNOTATION_ROW_COLUMNS = [
    "source_hint",
    "annotation_id",
    "objCls",
    "sentence",
    "description",
    "related_genes",
    "related_chemicals",
    "location_display",
    "gene_phenotype",
    "metabolizers1",
    "metabolizers2",
    "polarity",
    "significance",
    "phenotype_categories",
    "score",
    "literature_title",
    "literature_pmid",
    "literature_doi",
    "literature_year",
    "query_gene",
    "query_gene_id",
    "query_drug",
    "query_drug_id",
]

EFFECT_RULE_COLUMNS = [
    "gene",
    "gene_id",
    "drug",
    "drug_id",
    "phenotype_or_genotype",
    "normalized_phenotype_group",
    "drug_behavior_hint",
    "effect_direction",
    "risk_meaning",
    "demo_risk_level",
    "effect_polarity",
    "phenotype_category",
    "significance",
    "score",
    "evidence_strength",
    "source_container",
    "annotation_id",
    "objCls",
    "evidence_sentence",
    "plain_language_mvp",
    "literature_titles",
    "pmids",
    "dois",
    "years",
    "usable_for_mvp",
]

PAIR_RESULT_TYPES = [
    "guidelineAnnotation",
    "GuidelineAnnotation",
    "variantAnnotation",
    "VariantAnnotation",
    "label",
    "DrugLabel",
]


def norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def norm_key(value: Any) -> str:
    return norm_text(value).lower()


def compact(value: Any, max_len: int = 1200) -> str:
    text = norm_text(value)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def html_to_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("html", "")
    text = str(value or "")
    out = []
    in_tag = False
    for char in text:
        if char == "<":
            in_tag = True
            out.append(" ")
        elif char == ">":
            in_tag = False
        elif not in_tag:
            out.append(char)
    return compact("".join(out), 5000)


def term(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("term") or obj.get("name") or obj.get("symbol") or obj.get("id") or "")
    return str(obj or "")


def list_terms(values: Any) -> str:
    if isinstance(values, list):
        return "; ".join(term(v) for v in values if term(v))
    return term(values)


def flatten_items(payload: Any) -> List[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ["data", "items", "results", "content", "objects", "resources"]:
            if key in payload:
                nested = flatten_items(payload[key])
                if nested:
                    return nested
        return [payload]
    return []


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_fields: List[str] = []
    seen = set(fieldnames)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                extra_fields.append(key)
    final_fields = fieldnames + extra_fields
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=final_fields)
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
    candidates = [path, Path.cwd() / path_like, seed_dir / path_like, Path.cwd() / seed_dir / path_like]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"{path_like} bulunamadı.")


def unique_candidate_drugs(candidate_rows: List[Dict[str, str]]) -> List[str]:
    return sorted({norm_text(row.get("candidate_drug")) for row in candidate_rows if norm_text(row.get("candidate_drug"))})


def load_existing_resolved_chemicals(outputs_dir: Path) -> Dict[str, Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    csv_path = outputs_dir / "resolved_chemicals.csv"
    for row in read_csv(csv_path):
        name = row.get("name") or row.get("drug")
        if name:
            by_name[norm_key(name)] = dict(row)

    json_path = outputs_dir / "resolved_chemicals.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for name, obj in data.items():
                    if isinstance(obj, dict):
                        by_name.setdefault(norm_key(obj.get("name") or name), obj)
        except Exception:
            pass

    return by_name


def normalize_chemical_to_supported_row(drug_name: str, chemical: Dict[str, Any]) -> Dict[str, Any]:
    types_value = chemical.get("types", "")
    if isinstance(types_value, list):
        types = "; ".join(str(v) for v in types_value)
    else:
        types = str(types_value or "")

    behavior = "prodrug_activation" if "Prodrug" in types else "active_drug_or_general_drug"
    if not types:
        behavior = "active_drug_or_general_drug"

    return {
        "drug": norm_key(chemical.get("name") or drug_name),
        "drug_id": chemical.get("id", ""),
        "canonical_name": chemical.get("name") or drug_name,
        "types": types,
        "drug_behavior_hint": behavior,
        "pediatric": chemical.get("pediatric", ""),
        "mvp_supported": "candidate",
        "smiles": chemical.get("smiles", ""),
    }


def api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[str]]:
    url = path if path.startswith("http") else BASE_URL + path
    try:
        import requests
    except Exception:
        requests = None

    if requests is not None:
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=12)
        except Exception as exc:
            return None, f"api_error: {exc}"
        if not response.ok:
            return None, f"http_{response.status_code}"
        try:
            return response.json(), None
        except Exception as exc:
            return None, f"json_error: {exc}"

    try:
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
    except Exception as exc:
        return None, f"urllib_import_error: {exc}"

    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + urlencode(params)
    try:
        request = Request(url, headers=HEADERS)
        with urlopen(request, timeout=12) as response:
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                return None, f"http_{status}"
            body = response.read().decode("utf-8")
    except Exception as exc:
        return None, f"api_error: {exc}"
    try:
        return json.loads(body), None
    except Exception as exc:
        return None, f"json_error: {exc}"


def resolve_chemical_live(name: str) -> Tuple[Optional[Dict[str, Any]], str]:
    payload, error = api_get("/data/chemical", params={"name": name, "view": "base"})
    if error:
        return None, error
    items = [item for item in flatten_items(payload) if isinstance(item, dict)]
    if not items:
        return None, "not_found_in_api"
    return items[0], "resolved_via_api"


def extract_related_ids(items: Any) -> List[str]:
    if not isinstance(items, list):
        return []
    return [str(x.get("id") or x.get("accessionId")) for x in items if isinstance(x, dict) and (x.get("id") or x.get("accessionId"))]


def extract_related_names(items: Any, key: str = "name") -> List[str]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if isinstance(item, dict):
            value = item.get(key) or item.get("symbol") or item.get("name") or item.get("id")
            if value:
                out.append(str(value))
    return out


def is_exact_pair(annotation: Dict[str, Any], gene_id: str, drug_id: str, gene_symbol: str, drug_name: str) -> bool:
    related_gene_ids = set(extract_related_ids(annotation.get("relatedGenes")))
    related_drug_ids = set(extract_related_ids(annotation.get("relatedChemicals")))
    related_gene_symbols = {norm_key(x) for x in extract_related_names(annotation.get("relatedGenes"), key="symbol")}
    related_drug_names = {norm_key(x) for x in extract_related_names(annotation.get("relatedChemicals"), key="name")}
    gene_ok = gene_id in related_gene_ids or norm_key(gene_symbol) in related_gene_symbols
    drug_ok = drug_id in related_drug_ids or norm_key(drug_name) in related_drug_names
    return gene_ok and drug_ok


def annotation_id(annotation: Dict[str, Any]) -> str:
    return str(annotation.get("accessionId") or annotation.get("id") or "")


def dedupe_annotations(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for item in items:
        marker = annotation_id(item) or json.dumps(item, sort_keys=True)[:300]
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def summarize_annotation(item: Dict[str, Any], source_hint: str, gene: str, gene_id: str, drug: str, drug_id: str) -> Dict[str, Any]:
    location = item.get("location") or {}
    literature = item.get("literature")
    literature_title = ""
    literature_year = ""
    literature_pmid = ""
    literature_doi = ""
    if isinstance(literature, dict):
        literature_title = literature.get("title") or ""
        literature_year = literature.get("year") or ""
        for cr in literature.get("crossReferences", []) or []:
            if not isinstance(cr, dict):
                continue
            resource = str(cr.get("resource", "")).lower()
            if resource == "pubmed":
                literature_pmid = cr.get("resourceId", "")
            elif resource == "doi":
                literature_doi = cr.get("resourceId", "")

    return {
        "source_hint": source_hint,
        "annotation_id": annotation_id(item),
        "objCls": item.get("objCls", ""),
        "sentence": item.get("sentence", ""),
        "description": item.get("description", ""),
        "related_genes": "; ".join(extract_related_names(item.get("relatedGenes"), key="symbol")),
        "related_chemicals": "; ".join(extract_related_names(item.get("relatedChemicals"), key="name")),
        "location_display": location.get("displayName", "") if isinstance(location, dict) else "",
        "gene_phenotype": term(location.get("genePhenotype")) if isinstance(location, dict) else "",
        "metabolizers1": list_terms(item.get("metabolizers1")),
        "metabolizers2": list_terms(item.get("metabolizers2")),
        "polarity": term(item.get("polarity")),
        "significance": term(item.get("significance")),
        "phenotype_categories": list_terms(item.get("phenotypeCategories")),
        "score": item.get("score", ""),
        "literature_title": literature_title,
        "literature_pmid": literature_pmid,
        "literature_doi": literature_doi,
        "literature_year": literature_year,
        "query_gene": gene,
        "query_gene_id": gene_id,
        "query_drug": drug,
        "query_drug_id": drug_id,
    }


def extract_literature_info(literature: Any) -> Dict[str, str]:
    entries = []
    if isinstance(literature, dict):
        entries = [literature]
    elif isinstance(literature, list):
        entries = [x for x in literature if isinstance(x, dict)]

    titles: List[str] = []
    pmids: List[str] = []
    dois: List[str] = []
    years: List[str] = []
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


def guideline_to_extension_row(gene: str, gene_id: str, drug: str, drug_id: str, annotation: Dict[str, Any], source: str) -> Dict[str, Any]:
    summary = html_to_text(annotation.get("summaryMarkdown"))
    text = html_to_text(annotation.get("textMarkdown"))
    lit = extract_literature_info(annotation.get("literature"))
    return {
        "pair_key": f"{gene}::{drug}",
        "gene": gene,
        "gene_id": gene_id,
        "drug": drug,
        "drug_id": drug_id,
        "annotation_id": annotation_id(annotation),
        "objCls": annotation.get("objCls", ""),
        "name": annotation.get("name", ""),
        "source": annotation.get("source", ""),
        "source_container": source,
        "recommendation": annotation.get("recommendation", ""),
        "dosingInformation": annotation.get("dosingInformation", ""),
        "alternateDrugAvailable": annotation.get("alternateDrugAvailable", ""),
        "hasTestingInfo": annotation.get("hasTestingInfo", ""),
        "pediatric": annotation.get("pediatric", ""),
        "otherPrescribingGuidance": annotation.get("otherPrescribingGuidance", ""),
        "summary": compact(summary),
        "text_excerpt": compact(text, 1500),
        "literature_titles": lit["literature_titles"],
        "pmids": lit["pmids"],
        "dois": lit["dois"],
        "years": lit["years"],
        "evidence_tier": "high_guideline",
        "usable_for_mvp": "yes",
    }


def query_guideline_annotations(gene_id: str, drug_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    payload, error = api_get(
        "/data/guidelineAnnotation",
        params={"relatedGenes.accessionId": gene_id, "relatedChemicals.accessionId": drug_id, "view": "base"},
    )
    if error:
        return [], error
    return [x for x in flatten_items(payload) if isinstance(x, dict)], None


def query_pair_result(gene_id: str, drug_id: str, result_type: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    payload, error = api_get(f"/report/pair/{gene_id}/{drug_id}/{result_type}", params={"view": "base"})
    if error:
        return [], error
    return [x for x in flatten_items(payload) if isinstance(x, dict)], None


def is_significance_no(row: Dict[str, Any]) -> bool:
    return norm_key(row.get("significance")) == "no"


def normalize_phenotype_group(phenotype: str) -> str:
    p = norm_key(phenotype)
    if "poor metabolizer" in p or p == "poor":
        return "poor"
    if "intermediate metabolizer" in p or p == "intermediate":
        return "intermediate"
    if "normal metabolizer" in p or p == "normal":
        return "normal"
    if "ultrarapid metabolizer" in p or "ultra-rapid metabolizer" in p or p == "ultrarapid":
        return "ultrarapid"
    if "rapid metabolizer" in p or p == "rapid":
        return "rapid"
    if "decreased function" in p:
        return "decreased_function"
    if "*" in p:
        return "diplotype_or_haplotype"
    if p:
        return "other"
    return ""


def variant_to_nontriggering_effect_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if is_significance_no(row):
        return None
    phenotype = row.get("gene_phenotype") or row.get("metabolizers1") or row.get("location_display") or row.get("phenotype_or_genotype") or ""
    normalized = normalize_phenotype_group(phenotype)
    if normalized in {"", "normal"}:
        return None
    # Güvenli tercih: aday onboarding otomatik risk kuralı tetiklemez.
    return {
        "gene": row.get("query_gene", ""),
        "gene_id": row.get("query_gene_id", ""),
        "drug": row.get("query_drug", ""),
        "drug_id": row.get("query_drug_id", ""),
        "phenotype_or_genotype": phenotype,
        "normalized_phenotype_group": normalized,
        "drug_behavior_hint": "active_drug_or_general_drug",
        "effect_direction": "needs_manual_review",
        "risk_meaning": "candidate_onboarding_review_required",
        "demo_risk_level": "none",
        "effect_polarity": row.get("polarity", ""),
        "phenotype_category": row.get("phenotype_categories", ""),
        "significance": row.get("significance", ""),
        "score": row.get("score", ""),
        "evidence_strength": "candidate_annotation_review_required",
        "source_container": row.get("source_hint", ""),
        "annotation_id": row.get("annotation_id", ""),
        "objCls": row.get("objCls", ""),
        "evidence_sentence": compact(row.get("sentence") or row.get("description"), 1200),
        "plain_language_mvp": "",
        "literature_titles": row.get("literature_title", ""),
        "pmids": row.get("literature_pmid", ""),
        "dois": row.get("literature_doi", ""),
        "years": row.get("literature_year", ""),
        "usable_for_mvp": "no",
    }


def load_gene_rows(seed_dir: Path, genes: List[str]) -> List[Dict[str, str]]:
    rows = read_csv(seed_dir / "supported_genes.csv")
    wanted = {norm_key(g) for g in genes}
    return [row for row in rows if norm_key(row.get("gene")) in wanted]


def probe_candidate_annotations(
    chemical_rows: Dict[str, Dict[str, Any]],
    gene_rows: List[Dict[str, str]],
    *,
    dry_run: bool,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    pair_raw: Dict[str, Any] = {}
    guideline_rows: List[Dict[str, Any]] = []
    variant_rows: List[Dict[str, Any]] = []
    label_rows: List[Dict[str, Any]] = []
    guideline_extension_rows: List[Dict[str, Any]] = []
    effect_extension_rows: List[Dict[str, Any]] = []

    if dry_run:
        return pair_raw, guideline_rows, variant_rows, label_rows, guideline_extension_rows, effect_extension_rows

    for drug, chemical in chemical_rows.items():
        drug_id = str(chemical.get("id") or chemical.get("drug_id") or "")
        if not drug_id:
            continue
        drug_name = str(chemical.get("name") or drug)

        for gene in gene_rows:
            gene_symbol = gene.get("gene", "")
            gene_id = gene.get("gene_id", "")
            if not gene_symbol or not gene_id:
                continue

            pair_key = f"{gene_symbol}::{drug_name}"
            pair_raw[pair_key] = {
                "gene": gene,
                "drug": chemical,
                "guidelineAnnotation": [],
                "pair": {},
                "errors": [],
            }

            guideline_items, guideline_error = query_guideline_annotations(gene_id, drug_id)
            if guideline_error:
                pair_raw[pair_key]["errors"].append({"guidelineAnnotation": guideline_error})
            exact_guidelines = [
                item for item in guideline_items
                if is_exact_pair(item, gene_id, drug_id, gene_symbol, drug_name)
            ]
            exact_guidelines = dedupe_annotations(exact_guidelines)
            pair_raw[pair_key]["guidelineAnnotation"] = exact_guidelines
            for item in exact_guidelines:
                guideline_rows.append(summarize_annotation(item, "data/guidelineAnnotation", gene_symbol, gene_id, drug_name, drug_id))
                guideline_extension_rows.append(guideline_to_extension_row(
                    gene_symbol, gene_id, drug_name, drug_id, item, "data/guidelineAnnotation"
                ))

            for result_type in PAIR_RESULT_TYPES:
                items, error = query_pair_result(gene_id, drug_id, result_type)
                if error:
                    pair_raw[pair_key]["errors"].append({result_type: error})
                    continue
                exact_items = [
                    item for item in items
                    if is_exact_pair(item, gene_id, drug_id, gene_symbol, drug_name)
                ]
                exact_items = dedupe_annotations(exact_items)
                if not exact_items:
                    continue
                pair_raw[pair_key]["pair"][result_type] = exact_items

                for item in exact_items:
                    source_hint = f"report/pair:{result_type}"
                    row = summarize_annotation(item, source_hint, gene_symbol, gene_id, drug_name, drug_id)
                    if result_type.lower() == "label" or result_type == "DrugLabel":
                        label_rows.append(row)
                    elif result_type.lower() == "variantannotation":
                        if not is_significance_no(row):
                            variant_rows.append(row)
                            effect_row = variant_to_nontriggering_effect_row(row)
                            if effect_row:
                                effect_extension_rows.append(effect_row)
                    elif result_type.lower() == "guidelineannotation":
                        guideline_rows.append(row)
                        guideline_extension_rows.append(guideline_to_extension_row(
                            gene_symbol, gene_id, drug_name, drug_id, item, source_hint
                        ))

    guideline_rows = dedupe_rows(guideline_rows, ["query_gene", "query_drug", "annotation_id", "source_hint"])
    variant_rows = dedupe_rows(variant_rows, ["query_gene", "query_drug", "annotation_id", "source_hint"])
    label_rows = dedupe_rows(label_rows, ["query_gene", "query_drug", "annotation_id", "source_hint"])
    guideline_extension_rows = dedupe_rows(guideline_extension_rows, ["gene", "drug", "annotation_id", "source_container"])
    effect_extension_rows = dedupe_rows(effect_extension_rows, ["gene", "drug", "normalized_phenotype_group", "effect_direction", "risk_meaning", "annotation_id"])
    return pair_raw, guideline_rows, variant_rows, label_rows, guideline_extension_rows, effect_extension_rows


def dedupe_rows(rows: Iterable[Dict[str, Any]], key_fields: List[str]) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for row in rows:
        marker = tuple(norm_key(row.get(field)) for field in key_fields)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out


def backup_seed_file(target_path: Path) -> str:
    if not target_path.exists():
        return ""
    backup = target_path.with_name(target_path.name + ".bak")
    shutil.copy2(target_path, backup)
    return str(backup)


def merge_rows(
    target_path: Path,
    extension_rows: List[Dict[str, Any]],
    fieldnames: List[str],
    key_func,
    *,
    backup_path: str = "",
) -> Dict[str, Any]:
    existing = read_csv(target_path)
    existing_keys = {key_func(row) for row in existing}
    added = []
    skipped = []
    for row in extension_rows:
        key = key_func(row)
        if key in existing_keys:
            skipped.append(row)
            continue
        existing_keys.add(key)
        existing.append(row)
        added.append(row)

    if added:
        write_csv(target_path, existing, fieldnames)

    return {
        "target": str(target_path),
        "added": len(added),
        "skipped_duplicates": len(skipped),
        "backup": backup_path,
    }


def merge_supported_drugs(target_path: Path, extension_rows: List[Dict[str, Any]], backup_path: str = "") -> Dict[str, Any]:
    existing = read_csv(target_path)
    existing_drugs = {norm_key(row.get("drug")) for row in existing if norm_key(row.get("drug"))}
    existing_ids = {norm_key(row.get("drug_id")) for row in existing if norm_key(row.get("drug_id"))}
    added = []
    skipped = []

    for row in extension_rows:
        drug_key = norm_key(row.get("drug"))
        drug_id_key = norm_key(row.get("drug_id"))
        if (drug_key and drug_key in existing_drugs) or (drug_id_key and drug_id_key in existing_ids):
            skipped.append(row)
            continue
        existing.append(row)
        added.append(row)
        if drug_key:
            existing_drugs.add(drug_key)
        if drug_id_key:
            existing_ids.add(drug_id_key)

    if added:
        write_csv(target_path, existing, SUPPORTED_DRUG_COLUMNS)

    return {
        "target": str(target_path),
        "added": len(added),
        "skipped_duplicates": len(skipped),
        "backup": backup_path,
    }


def guideline_key(row: Dict[str, Any]) -> Tuple[str, str, str]:
    return (norm_key(row.get("gene")), norm_key(row.get("drug")), norm_key(row.get("annotation_id")))


def effect_key(row: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    return (
        norm_key(row.get("gene")),
        norm_key(row.get("drug")),
        norm_key(row.get("normalized_phenotype_group")),
        norm_key(row.get("effect_direction")),
        norm_key(row.get("risk_meaning")),
        norm_key(row.get("annotation_id")),
    )


def perform_merge(seed_dir: Path, supported_ext: List[Dict[str, Any]], guideline_ext: List[Dict[str, Any]], effect_ext: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    supported_path = seed_dir / "supported_drugs.csv"
    guideline_path = seed_dir / "drug_gene_guidelines.csv"
    effect_path = seed_dir / "phenotype_effect_rules.csv"
    backups = {
        str(supported_path): backup_seed_file(supported_path),
        str(guideline_path): backup_seed_file(guideline_path),
        str(effect_path): backup_seed_file(effect_path),
    }
    merge_results = []
    merge_results.append(merge_supported_drugs(supported_path, supported_ext, backup_path=backups[str(supported_path)]))
    merge_results.append(merge_rows(guideline_path, guideline_ext, GUIDELINE_COLUMNS, guideline_key, backup_path=backups[str(guideline_path)]))
    merge_results.append(merge_rows(effect_path, effect_ext, EFFECT_RULE_COLUMNS, effect_key, backup_path=backups[str(effect_path)]))
    return merge_results


def run_beta_ranker(seed_dir: Path) -> Dict[str, Any]:
    out_dir = seed_dir / "alternative_outputs_beta"
    cmd = [
        sys.executable,
        "alternative_ranker.py",
        "--seed-dir",
        str(seed_dir),
        "--source-drug",
        "clopidogrel",
        "--profile-id",
        "P2_cyp2c19_poor",
        "--current-drugs",
        "clopidogrel,voriconazole,codeine,warfarin,amitriptyline",
        "--out-dir",
        str(out_dir),
    ]
    completed = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True)
    result_path = out_dir / "alternative_result_full.json"
    candidate_statuses = []
    if result_path.exists():
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
            for item in data.get("candidate_results", []) or []:
                candidate_statuses.append({
                    "candidate_drug": item.get("candidate_drug"),
                    "mvp_data_status": item.get("mvp_data_status"),
                    "score": item.get("score"),
                    "candidate_specific_risk_level": item.get("candidate_specific_risk_level"),
                })
        except Exception:
            pass
    return {
        "command": " ".join(cmd),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "candidate_statuses": candidate_statuses,
    }


def render_report(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# MVP-2 Candidate Onboarding Raporu")
    lines.append("")
    lines.append("## Güvenlik Notu")
    lines.append("")
    lines.append(SAFETY_NOTICE)
    lines.append("")
    lines.append(CHEMICAL_RESOLVE_NOTICE)
    lines.append("")
    lines.append("## Aday İlaç Listesi")
    lines.append("")
    for drug in payload.get("candidates", []):
        lines.append(f"- {drug}")
    lines.append("")
    lines.append("## ClinPGx Chemical Çözüm Durumu")
    lines.append("")
    lines.append("| Aday | Mevcut seed | Resolve durumu | Chemical ID | Not |")
    lines.append("|---|---|---|---|---|")
    for item in payload.get("candidate_statuses", []):
        note = item.get("note", "")
        lines.append(
            f"| {item.get('candidate_drug', '')} | {item.get('already_supported')} | "
            f"{item.get('resolve_status', '')} | {item.get('drug_id', '')} | {note} |"
        )
    lines.append("")
    lines.append("## Gene-Drug Annotation Durumu")
    lines.append("")
    counts = payload.get("annotation_counts", {})
    lines.append(f"- GuidelineAnnotation satırı: {counts.get('guideline_rows', 0)}")
    lines.append(f"- VariantAnnotation satırı: {counts.get('variant_rows', 0)}")
    lines.append(f"- Label satırı: {counts.get('label_rows', 0)}")
    lines.append("")
    if counts.get("guideline_rows", 0) == 0 and counts.get("variant_rows", 0) == 0:
        lines.append("Mevcut çalıştırmada adaylar için usable farmakogenetik phenotype rule oluşturacak kayıt doğrulanamadı.")
        lines.append("")
    for item in payload.get("candidate_statuses", []):
        if item.get("resolve_status") in {"resolved_existing_outputs", "resolved_via_api"} and item.get("usable_effect_rules", 0) == 0:
            lines.append(f"- **{item.get('candidate_drug')}:** {NO_RULE_NOTICE}")
    lines.append("")
    lines.append("## Seed Extension Özeti")
    lines.append("")
    lines.append(f"- `candidate_supported_drugs_extension.csv`: {counts.get('supported_extension_rows', 0)} satır")
    lines.append(f"- `candidate_drug_gene_guidelines_extension.csv`: {counts.get('guideline_extension_rows', 0)} satır")
    lines.append(f"- `candidate_phenotype_effect_rules_extension.csv`: {counts.get('effect_extension_rows', 0)} satır")
    lines.append("")
    lines.append("## Merge Durumu")
    lines.append("")
    if payload.get("merge_requested"):
        for result in payload.get("merge_results", []):
            lines.append(
                f"- {result.get('target')}: added={result.get('added')}, "
                f"skipped_duplicates={result.get('skipped_duplicates')}, backup={result.get('backup') or 'yok'}"
            )
    else:
        lines.append("Merge yapılmadı. Mevcut seed dosyaları değiştirilmedi; yalnızca extension dosyaları üretildi.")
    lines.append("")
    if payload.get("beta_ranker_result"):
        lines.append("### Alternative Ranker Entegrasyon Kontrolü")
        lines.append("")
        beta = payload["beta_ranker_result"]
        lines.append(f"- Komut dönüş kodu: {beta.get('returncode')}")
        for status in beta.get("candidate_statuses", []):
            lines.append(
                f"- {status.get('candidate_drug')}: {status.get('mvp_data_status')} "
                f"(score={status.get('score')}, risk_level={status.get('candidate_specific_risk_level')})"
            )
        lines.append("")
    lines.append("## Veri Kısıtları")
    lines.append("")
    lines.append("- Candidate onboarding otomatik klinik öneri üretmez.")
    lines.append("- ClinPGx chemical çözümü PGx rule bulunduğu anlamına gelmez.")
    lines.append("- Label kayıtları ayrı tutulur; risk rule tetikleyicisi yapılmaz.")
    lines.append("- Normal metabolizer karşılaştırmaları risk tetikleyicisi yapılmaz.")
    lines.append("- Otomatik oluşturulan effect rule extension satırları `usable_for_mvp=no` olarak tutulur ve manuel inceleme gerektirir.")
    if payload.get("dry_run"):
        lines.append("- Dry-run modunda API çağrısı ve merge yapılmadı.")
    lines.append("")
    lines.append("## Sonraki Adım")
    lines.append("")
    if payload.get("merge_requested"):
        lines.append("Merge sonrası alternative ranker çıktısındaki aday statüleri kontrol edilmelidir. Usable rule olmayan adaylar `insufficient_pgx_rule_data` olarak kalmalıdır.")
    else:
        lines.append("Extension dosyaları incelendikten sonra uygun görülürse `--merge` ile seed dosyalarına kontrollü ekleme yapılabilir.")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MVP-2 candidate onboarding")
    parser.add_argument("--seed-dir", default="clinpgx_mvp_seed")
    parser.add_argument("--candidate-file", default="candidate_alternatives.csv")
    parser.add_argument("--out-dir", default="clinpgx_mvp_seed/candidate_onboarding_outputs")
    parser.add_argument("--clinpgx-outputs-dir", default="clinpgx_outputs_v2")
    parser.add_argument("--genes", default="CYP2C19,CYP2D6,CYP2C9,CYP3A4,CYP1A2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_dir = Path(args.seed_dir)
    out_dir = Path(args.out_dir)
    outputs_dir = Path(args.clinpgx_outputs_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidate_file = resolve_input_file(args.candidate_file, seed_dir)
    candidate_rows = read_csv(candidate_file)
    candidates = unique_candidate_drugs(candidate_rows)
    genes = [norm_text(g) for g in str(args.genes).split(",") if norm_text(g)]
    gene_rows = load_gene_rows(seed_dir, genes)
    supported_rows = read_csv(seed_dir / "supported_drugs.csv")
    supported_by_name = {norm_key(row.get("drug")): row for row in supported_rows}
    existing_chemicals = load_existing_resolved_chemicals(outputs_dir)

    candidate_statuses: List[Dict[str, Any]] = []
    resolved_for_extension: Dict[str, Dict[str, Any]] = {}
    supported_extension_rows: List[Dict[str, Any]] = []

    for candidate in candidates:
        already_supported = norm_key(candidate) in supported_by_name
        status = {
            "candidate_drug": candidate,
            "already_supported": already_supported,
            "resolve_status": "",
            "drug_id": "",
            "note": "",
            "usable_effect_rules": 0,
        }

        chemical: Optional[Dict[str, Any]] = None
        if already_supported:
            row = supported_by_name[norm_key(candidate)]
            chemical = {
                "id": row.get("drug_id", ""),
                "name": row.get("canonical_name") or row.get("drug"),
                "types": row.get("types", ""),
                "pediatric": row.get("pediatric", ""),
                "smiles": row.get("smiles", ""),
            }
            status["resolve_status"] = "already_supported"
        elif norm_key(candidate) in existing_chemicals:
            chemical = existing_chemicals[norm_key(candidate)]
            status["resolve_status"] = "resolved_existing_outputs"
        elif args.dry_run:
            status["resolve_status"] = "not_found_in_existing_outputs"
            status["note"] = "dry-run nedeniyle API resolve denenmedi"
        else:
            chemical, resolve_status = resolve_chemical_live(candidate)
            status["resolve_status"] = resolve_status

        if chemical:
            drug_id = str(chemical.get("id") or chemical.get("drug_id") or "")
            status["drug_id"] = drug_id
            resolved_for_extension[candidate] = chemical
            if not already_supported:
                supported_extension_rows.append(normalize_chemical_to_supported_row(candidate, chemical))
        elif not status["note"]:
            status["note"] = "Mevcut çıktılarda bulunamadı ve API üzerinden çözülemedi."

        candidate_statuses.append(status)

    pair_raw, guideline_rows, variant_rows, label_rows, guideline_extension_rows, effect_extension_rows = probe_candidate_annotations(
        resolved_for_extension,
        gene_rows,
        dry_run=args.dry_run,
    )

    effect_counts_by_drug: Dict[str, int] = {}
    for row in effect_extension_rows:
        if row.get("usable_for_mvp") == "yes":
            effect_counts_by_drug[row.get("drug", "")] = effect_counts_by_drug.get(row.get("drug", ""), 0) + 1
    for status in candidate_statuses:
        status["usable_effect_rules"] = effect_counts_by_drug.get(status.get("candidate_drug", ""), 0)

    write_csv(out_dir / "candidate_supported_drugs_extension.csv", supported_extension_rows, SUPPORTED_DRUG_COLUMNS)
    write_csv(out_dir / "candidate_guideline_annotation_rows.csv", guideline_rows, ANNOTATION_ROW_COLUMNS)
    write_csv(out_dir / "candidate_variant_annotation_rows.csv", variant_rows, ANNOTATION_ROW_COLUMNS)
    write_csv(out_dir / "candidate_label_rows.csv", label_rows, ANNOTATION_ROW_COLUMNS)
    write_json(out_dir / "candidate_pair_probe_raw.json", pair_raw)
    write_csv(out_dir / "candidate_drug_gene_guidelines_extension.csv", guideline_extension_rows, GUIDELINE_COLUMNS)
    write_csv(out_dir / "candidate_phenotype_effect_rules_extension.csv", effect_extension_rows, EFFECT_RULE_COLUMNS)

    merge_results: List[Dict[str, Any]] = []
    beta_ranker_result: Optional[Dict[str, Any]] = None
    if args.merge and not args.dry_run:
        merge_results = perform_merge(seed_dir, supported_extension_rows, guideline_extension_rows, effect_extension_rows)
        beta_ranker_result = run_beta_ranker(seed_dir)

    payload = {
        "candidates": candidates,
        "candidate_statuses": candidate_statuses,
        "annotation_counts": {
            "supported_extension_rows": len(supported_extension_rows),
            "guideline_rows": len(guideline_rows),
            "variant_rows": len(variant_rows),
            "label_rows": len(label_rows),
            "guideline_extension_rows": len(guideline_extension_rows),
            "effect_extension_rows": len(effect_extension_rows),
        },
        "merge_requested": bool(args.merge and not args.dry_run),
        "merge_results": merge_results,
        "beta_ranker_result": beta_ranker_result,
        "dry_run": bool(args.dry_run),
        "candidate_file": str(candidate_file),
        "clinpgx_outputs_dir": str(outputs_dir),
    }
    write_json(out_dir / "candidate_onboarding_result_full.json", payload)
    write_text(out_dir / "candidate_onboarding_report.md", render_report(payload))

    print("\n=== CANDIDATE ONBOARDING DONE ===")
    print(f"Candidates: {len(candidates)}")
    for status in candidate_statuses:
        print(
            f"- {status['candidate_drug']}: {status['resolve_status']} "
            f"| supported={status['already_supported']} | id={status.get('drug_id', '')}"
        )
    print("\nÇıktılar:")
    for name in [
        "candidate_supported_drugs_extension.csv",
        "candidate_guideline_annotation_rows.csv",
        "candidate_variant_annotation_rows.csv",
        "candidate_label_rows.csv",
        "candidate_pair_probe_raw.json",
        "candidate_drug_gene_guidelines_extension.csv",
        "candidate_phenotype_effect_rules_extension.csv",
        "candidate_onboarding_report.md",
    ]:
        print(f"- {out_dir / name}")


if __name__ == "__main__":
    main()
