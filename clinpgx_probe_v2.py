#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clinpgx_probe_v2.py

ClinPGx API ikinci keşif scripti.

Bu sürümün amacı:
1) Gene symbol ve drug/chemical name üzerinden ClinPGx PA ID çözmek.
2) Gene ID + Chemical ID ile guidelineAnnotation sorgulamak.
3) Aynı ikili için /report/pair endpointini farklı resultType değerleriyle denemek.
4) Gene bazlı variantAnnotation çekip MVP'ye uygun özet satırlar üretmek.
5) Ham sonuçları JSON, özetleri CSV olarak kaydetmek.

Klinik karar, doz veya tedavi önerisi üretmez.
Sadece kaynaklı farmakogenetik veri keşfi yapar.
"""

import csv
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


BASE_URL = "https://api.clinpgx.org/v1"
OPENAPI_URL = "https://api.clinpgx.org/openapi.json"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pgx-mvp-probe-v2/0.2",
}

REQUEST_DELAY_SECONDS = 0.6
OUT_DIR = Path("clinpgx_outputs_v2")


# MVP için test edeceğimiz ilk küçük set.
GENES = [
    "CYP2C19",
    "CYP2D6",
    "CYP2C9",
    "CYP3A4",
    "CYP1A2",
]

DRUGS = [
    "clopidogrel",
    "amitriptyline",
    "voriconazole",
    "codeine",
    "tamoxifen",
    "citalopram",
    "sertraline",
    "fluoxetine",
    "paroxetine",
    "warfarin",
    "omeprazole",
]

# Pair endpointinde hangi sonuç türleri işe yarıyor onu keşfediyoruz.
PAIR_RESULT_TYPES = [
    "guidelineAnnotation",
    "GuidelineAnnotation",
    "summaryAnnotation",
    "SummaryAnnotation",
    "variantAnnotation",
    "VariantAnnotation",
    "label",
    "DrugLabel",
    "pathway",
    "Pathway",
    "dataAnnotation",
    "DataAnnotation",
    "connection",
    "Connection",
]


def sleep_softly() -> None:
    time.sleep(REQUEST_DELAY_SECONDS)


def safe_get(
    path_or_url: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    quiet_404: bool = True,
) -> Tuple[Optional[Any], Optional[requests.Response]]:
    """GET isteği atar. JSON dönerse parse eder."""
    sleep_softly()

    if path_or_url.startswith("http"):
        url = path_or_url
    else:
        url = BASE_URL + path_or_url

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=35)
    except requests.RequestException as exc:
        print(f"\n[NETWORK ERROR] {url}")
        print(exc)
        return None, None

    if not response.ok:
        if not (quiet_404 and response.status_code == 404):
            print(f"\n[HTTP {response.status_code}] {response.url}")
            print(response.text[:500])
        return None, response

    try:
        return response.json(), response
    except ValueError:
        print(f"\n[JSON PARSE ERROR] {response.url}")
        print(response.text[:500])
        return None, response


def save_json(payload: Any, filename: str) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {path}")
    return path


def write_csv(rows: List[Dict[str, Any]], filename: str) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / filename

    if not rows:
        path.write_text("", encoding="utf-8")
        print(f"[SAVED EMPTY] {path}")
        return path

    # Tüm satırlardaki kolonları birleştir.
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

    print(f"[SAVED] {path} ({len(rows)} rows)")
    return path


def flatten_items(payload: Any) -> List[Any]:
    """ClinPGx cevaplarını listeye indirger."""
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


def compact(value: Any, max_len: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def term(obj: Any) -> str:
    """ClinPGx term dict'lerinden okunabilir term çıkarır."""
    if isinstance(obj, dict):
        return str(obj.get("term") or obj.get("name") or obj.get("symbol") or obj.get("id") or "")
    return str(obj or "")


def list_terms(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, list):
        return "; ".join(term(v) for v in values if term(v))
    return term(values)


def get_first(items: List[Any]) -> Optional[Dict[str, Any]]:
    for item in items:
        if isinstance(item, dict):
            return item
    return None


def resolve_gene(symbol: str) -> Optional[Dict[str, Any]]:
    """Gene symbol -> ClinPGx Gene object."""
    payload, response = safe_get("/data/gene", params={"symbol": symbol, "view": "base"})
    items = flatten_items(payload)
    obj = get_first(items)

    if obj:
        print(f"[GENE] {symbol:10s} -> {obj.get('id')} | {obj.get('name')}")
    else:
        print(f"[GENE NOT FOUND] {symbol}")

    return obj


def resolve_chemical(name: str) -> Optional[Dict[str, Any]]:
    """Chemical name -> ClinPGx Chemical object."""
    payload, response = safe_get("/data/chemical", params={"name": name, "view": "base"})
    items = flatten_items(payload)
    obj = get_first(items)

    if obj:
        print(f"[DRUG] {name:16s} -> {obj.get('id')} | {obj.get('name')}")
    else:
        print(f"[DRUG NOT FOUND] {name}")

    return obj


def get_by_id(kind: str, obj_id: str, view: str = "base") -> Optional[Dict[str, Any]]:
    """Gene/Chemical/GuidelineAnnotation gibi objeleri ID ile çeker."""
    payload, response = safe_get(f"/data/{kind}/{obj_id}", params={"view": view})
    items = flatten_items(payload)
    return get_first(items)


def query_guideline_annotations(
    gene_id: str,
    chemical_id: str,
    view: str = "base",
) -> List[Dict[str, Any]]:
    """
    Doğru strateji:
    /data/guidelineAnnotation?relatedGenes.accessionId=PA124&relatedChemicals.accessionId=PA449053
    """
    param_sets = [
        {
            "relatedGenes.accessionId": gene_id,
            "relatedChemicals.accessionId": chemical_id,
            "view": view,
        },
        # Bazı ilişkiler sadece gen veya sadece ilaç üzerinden gelebilir; bunları da kontrol ediyoruz.
        {
            "relatedGenes.accessionId": gene_id,
            "view": view,
        },
        {
            "relatedChemicals.accessionId": chemical_id,
            "view": view,
        },
    ]

    all_items: List[Dict[str, Any]] = []

    for params in param_sets:
        payload, response = safe_get("/data/guidelineAnnotation", params=params)
        items = [x for x in flatten_items(payload) if isinstance(x, dict)]

        # Sadece ikiliye ait olanları tercih ediyoruz.
        all_items.extend(items)

        label = "&".join(f"{k}={v}" for k, v in params.items())
        print(f"  [guidelineAnnotation] {label} -> {len(items)}")

    # Duplicate temizle.
    return dedupe_by_id(all_items)


def report_pair(
    first_id: str,
    second_id: str,
    result_type: str,
    view: str = "base",
) -> List[Dict[str, Any]]:
    path = f"/report/pair/{first_id}/{second_id}/{result_type}"
    payload, response = safe_get(path, params={"view": view})
    return [x for x in flatten_items(payload) if isinstance(x, dict)]


def try_pair_all_types(gene_id: str, chemical_id: str) -> Dict[str, List[Dict[str, Any]]]:
    results: Dict[str, List[Dict[str, Any]]] = {}

    for result_type in PAIR_RESULT_TYPES:
        items = report_pair(gene_id, chemical_id, result_type)
        if items:
            print(f"  [pair] {gene_id} + {chemical_id} / {result_type} -> {len(items)}")
            results[result_type] = dedupe_by_id(items)

    return results


def connected_objects(obj_id: str, obj_type: str = "Chemical") -> List[Dict[str, Any]]:
    """
    /report/connectedObjects/{id}/{type}
    type için Chemical/Gene gibi değerleri deniyoruz.
    """
    payload, response = safe_get(f"/report/connectedObjects/{obj_id}/{obj_type}", params=None)
    items = [x for x in flatten_items(payload) if isinstance(x, dict)]
    print(f"  [connectedObjects] {obj_id}/{obj_type} -> {len(items)}")
    return items


def query_variant_annotations_by_gene(
    gene_symbol: str,
    view: str = "base",
    max_keep: int = 30,
) -> List[Dict[str, Any]]:
    """
    Gene bazlı variantAnnotation çok kayıt döndürebilir.
    Bu yüzden filtrelenebilir ham bir örnek alıp MVP satırına çevireceğiz.
    """
    payload, response = safe_get(
        "/data/variantAnnotation",
        params={"location.genes.symbol": gene_symbol, "view": view},
        quiet_404=False,
    )
    items = [x for x in flatten_items(payload) if isinstance(x, dict)]

    print(f"[variantAnnotation] {gene_symbol} -> {len(items)} raw kayıt")

    # MVP'ye daha yakın olanları öne al:
    # - relatedChemicals var
    # - significance yes veya score pozitif
    # - sentence var
    filtered = []
    for item in items:
        if not item.get("relatedChemicals"):
            continue
        if not item.get("sentence") and not item.get("description"):
            continue

        significance = term(item.get("significance")).lower()
        score = item.get("score")
        try:
            score_float = float(score)
        except Exception:
            score_float = 0.0

        if significance in ["yes", "not stated"] or score_float > 0:
            filtered.append(item)

    # Daha yüksek score ve significance yes öne gelsin.
    def rank_key(x: Dict[str, Any]) -> Tuple[int, float]:
        significance = term(x.get("significance")).lower()
        sig_bonus = 1 if significance == "yes" else 0
        try:
            score_float = float(x.get("score") or 0.0)
        except Exception:
            score_float = 0.0
        return sig_bonus, score_float

    filtered.sort(key=rank_key, reverse=True)

    print(f"[variantAnnotation] {gene_symbol} -> {len(filtered)} filtreli kayıt")
    return filtered[:max_keep]


def dedupe_by_id(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    for item in items:
        item_id = item.get("id") or item.get("accessionId") or json.dumps(item, sort_keys=True)[:200]
        if item_id in seen:
            continue
        seen.add(item_id)
        out.append(item)

    return out


def extract_related_names(objects: Any, key: str = "name") -> str:
    if not objects:
        return ""
    if isinstance(objects, list):
        return "; ".join(str(o.get(key) or o.get("symbol") or o.get("id") or "") for o in objects if isinstance(o, dict))
    return compact(objects)


def html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def summarize_annotation(item: Dict[str, Any], source_hint: str = "") -> Dict[str, Any]:
    location = item.get("location") or {}

    row = {
        "source_hint": source_hint,
        "annotation_id": item.get("accessionId") or item.get("id") or "",
        "objCls": item.get("objCls") or "",
        "sentence": item.get("sentence") or "",
        "description": item.get("description") or "",
        "related_genes": extract_related_names(item.get("relatedGenes"), key="symbol"),
        "related_chemicals": extract_related_names(item.get("relatedChemicals"), key="name"),
        "location_display": location.get("displayName") if isinstance(location, dict) else "",
        "gene_phenotype": term(location.get("genePhenotype")) if isinstance(location, dict) else "",
        "metabolizers1": list_terms(item.get("metabolizers1")),
        "metabolizers2": list_terms(item.get("metabolizers2")),
        "polarity": term(item.get("polarity")),
        "significance": term(item.get("significance")),
        "phenotype_categories": list_terms(item.get("phenotypeCategories")),
        "score": item.get("score", ""),
        "literature_title": "",
        "literature_pmid": "",
        "literature_doi": "",
        "literature_year": "",
    }

    literature = item.get("literature")
    if isinstance(literature, dict):
        row["literature_title"] = literature.get("title") or ""
        row["literature_year"] = literature.get("year") or ""

        for cr in literature.get("crossReferences", []) or []:
            if not isinstance(cr, dict):
                continue
            resource = cr.get("resource", "").lower()
            if resource == "pubmed":
                row["literature_pmid"] = cr.get("resourceId", "")
            elif resource == "doi":
                row["literature_doi"] = cr.get("resourceId", "")

    return row


def summarize_gene(obj: Dict[str, Any]) -> Dict[str, Any]:
    vip_summary = obj.get("vipSummary") or {}

    return {
        "id": obj.get("id", ""),
        "symbol": obj.get("symbol", ""),
        "name": obj.get("name", ""),
        "cpicGene": obj.get("cpicGene", ""),
        "pharmVarGene": obj.get("pharmVarGene", ""),
        "alleleFile": obj.get("alleleFile", ""),
        "alleleFunctionSource": obj.get("alleleFunctionSource", ""),
        "alleleType": obj.get("alleleType", ""),
        "vipTier": obj.get("vipTier", ""),
        "vipSummary_text": html_to_text(vip_summary.get("html", "")) if isinstance(vip_summary, dict) else "",
    }


def summarize_chemical(obj: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": obj.get("id", ""),
        "name": obj.get("name", ""),
        "objCls": obj.get("objCls", ""),
        "types": "; ".join(obj.get("types", []) or []),
        "pediatric": obj.get("pediatric", ""),
        "smiles": obj.get("smiles", ""),
    }


def make_mvp_edge_row(
    gene_symbol: str,
    drug_name: str,
    gene_id: str,
    drug_id: str,
    annotation: Dict[str, Any],
    source_hint: str,
) -> Dict[str, Any]:
    base = summarize_annotation(annotation, source_hint=source_hint)

    # MVP risk motoru için en gerekli normalize kolonlar.
    phenotype = base.get("gene_phenotype") or base.get("metabolizers1") or base.get("location_display")
    chemical_names = base.get("related_chemicals") or drug_name
    sentence = base.get("sentence") or base.get("description")

    return {
        "query_gene": gene_symbol,
        "query_gene_id": gene_id,
        "query_drug": drug_name,
        "query_drug_id": drug_id,
        "edge_source": source_hint,
        "annotation_id": base.get("annotation_id", ""),
        "objCls": base.get("objCls", ""),
        "related_chemicals": chemical_names,
        "phenotype_or_genotype": phenotype,
        "effect_polarity": base.get("polarity", ""),
        "phenotype_category": base.get("phenotype_categories", ""),
        "significance": base.get("significance", ""),
        "score": base.get("score", ""),
        "evidence_sentence": sentence,
        "literature_title": base.get("literature_title", ""),
        "literature_pmid": base.get("literature_pmid", ""),
        "literature_doi": base.get("literature_doi", ""),
        "literature_year": base.get("literature_year", ""),
    }


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    # OpenAPI sadece kontrol amaçlı.
    spec, response = safe_get(OPENAPI_URL)
    if isinstance(spec, dict) and "paths" in spec:
        print(f"[OK] OpenAPI loaded: {OPENAPI_URL}")
        print(f"[INFO] endpoints: {len(spec.get('paths', {}))}")
        save_json(spec, "openapi_snapshot.json")
    else:
        print("[WARN] OpenAPI çekilemedi ama ana sorgulara devam ediyorum.")

    print("\n=== 1) Resolve Gene IDs ===")
    genes: Dict[str, Dict[str, Any]] = {}
    for symbol in GENES:
        obj = resolve_gene(symbol)
        if obj:
            genes[symbol] = obj

    print("\n=== 2) Resolve Chemical IDs ===")
    chemicals: Dict[str, Dict[str, Any]] = {}
    for name in DRUGS:
        obj = resolve_chemical(name)
        if obj:
            chemicals[name] = obj

    save_json(genes, "resolved_genes.json")
    save_json(chemicals, "resolved_chemicals.json")
    write_csv([summarize_gene(x) for x in genes.values()], "resolved_genes.csv")
    write_csv([summarize_chemical(x) for x in chemicals.values()], "resolved_chemicals.csv")

    print("\n=== 3) Gene-Drug Relationship Probe ===")
    pair_raw: Dict[str, Any] = {}
    mvp_edges: List[Dict[str, Any]] = []
    guideline_rows: List[Dict[str, Any]] = []
    pair_rows: List[Dict[str, Any]] = []

    # Çok istek atmamak için makul küçük çiftler.
    # CYP3A4/CYP1A2 ilişki az çıkarsa yine de problem değil; keşif için deniyoruz.
    candidate_pairs = [
        ("CYP2C19", "clopidogrel"),
        ("CYP2C19", "voriconazole"),
        ("CYP2C19", "amitriptyline"),
        ("CYP2C19", "citalopram"),
        ("CYP2C19", "sertraline"),
        ("CYP2D6", "codeine"),
        ("CYP2D6", "amitriptyline"),
        ("CYP2D6", "tamoxifen"),
        ("CYP2D6", "fluoxetine"),
        ("CYP2D6", "paroxetine"),
        ("CYP2C9", "warfarin"),
        ("CYP3A4", "voriconazole"),
        ("CYP1A2", "amitriptyline"),
    ]

    for gene_symbol, drug_name in candidate_pairs:
        gene = genes.get(gene_symbol)
        drug = chemicals.get(drug_name)

        if not gene or not drug:
            print(f"\n[SKIP PAIR] {gene_symbol} + {drug_name}: ID eksik.")
            continue

        gene_id = str(gene["id"])
        drug_id = str(drug["id"])

        print(f"\n--- PAIR: {gene_symbol}({gene_id}) + {drug_name}({drug_id}) ---")

        pair_key = f"{gene_symbol}::{drug_name}"
        pair_raw[pair_key] = {
            "gene": gene,
            "drug": drug,
            "guidelineAnnotation": [],
            "pair": {},
            "connected": {},
        }

        guideline_items = query_guideline_annotations(gene_id, drug_id, view="base")
        pair_raw[pair_key]["guidelineAnnotation"] = guideline_items

        for item in guideline_items:
            row = summarize_annotation(item, source_hint="data/guidelineAnnotation")
            row.update({
                "query_gene": gene_symbol,
                "query_gene_id": gene_id,
                "query_drug": drug_name,
                "query_drug_id": drug_id,
            })
            guideline_rows.append(row)
            mvp_edges.append(make_mvp_edge_row(
                gene_symbol, drug_name, gene_id, drug_id, item, "data/guidelineAnnotation"
            ))

        pair_results = try_pair_all_types(gene_id, drug_id)
        pair_raw[pair_key]["pair"] = pair_results

        for result_type, items in pair_results.items():
            for item in items:
                row = summarize_annotation(item, source_hint=f"report/pair:{result_type}")
                row.update({
                    "query_gene": gene_symbol,
                    "query_gene_id": gene_id,
                    "query_drug": drug_name,
                    "query_drug_id": drug_id,
                    "pair_result_type": result_type,
                })
                pair_rows.append(row)
                mvp_edges.append(make_mvp_edge_row(
                    gene_symbol, drug_name, gene_id, drug_id, item, f"report/pair:{result_type}"
                ))

    save_json(pair_raw, "pair_probe_raw.json")
    write_csv(guideline_rows, "guideline_annotation_rows.csv")
    write_csv(pair_rows, "pair_annotation_rows.csv")

    print("\n=== 4) Gene-level VariantAnnotation Probe ===")
    variant_raw: Dict[str, Any] = {}
    variant_rows: List[Dict[str, Any]] = []

    # Şimdilik CYP2C19 ve CYP2D6 yeter; bunlar MVP'de en güçlü adaylar.
    for symbol in ["CYP2C19", "CYP2D6", "CYP2C9"]:
        if symbol not in genes:
            continue

        items = query_variant_annotations_by_gene(symbol, view="base", max_keep=40)
        variant_raw[symbol] = items

        for item in items:
            row = summarize_annotation(item, source_hint="data/variantAnnotation")
            row["query_gene"] = symbol
            row["query_gene_id"] = genes[symbol].get("id", "")
            variant_rows.append(row)

            # VariantAnnotation gene-level geldiği için query_drug boş olabilir;
            # relatedChemicals içinden MVP edge üretmek daha mantıklı.
            related_chemicals = item.get("relatedChemicals") or []
            if isinstance(related_chemicals, list):
                for chem in related_chemicals:
                    if not isinstance(chem, dict):
                        continue
                    mvp_edges.append(make_mvp_edge_row(
                        symbol,
                        chem.get("name", ""),
                        str(genes[symbol].get("id", "")),
                        str(chem.get("id", "")),
                        item,
                        "data/variantAnnotation"
                    ))

    save_json(variant_raw, "variant_annotation_filtered_raw.json")
    write_csv(variant_rows, "variant_annotation_filtered_rows.csv")

    # Duplicate temizliği: aynı annotation + gene + drug aynıysa tek satır.
    deduped_edges: List[Dict[str, Any]] = []
    seen_edges = set()
    for row in mvp_edges:
        marker = (
            row.get("query_gene_id", ""),
            row.get("query_drug_id", ""),
            row.get("annotation_id", ""),
            row.get("edge_source", ""),
        )
        if marker in seen_edges:
            continue
        seen_edges.add(marker)
        deduped_edges.append(row)

    write_csv(deduped_edges, "mvp_candidate_drug_gene_edges.csv")
    save_json(deduped_edges, "mvp_candidate_drug_gene_edges.json")

    print("\n=== DONE ===")
    print(f"Output folder: {OUT_DIR.resolve()}")
    print("En önemli dosyalar:")
    print(" - resolved_genes.csv")
    print(" - resolved_chemicals.csv")
    print(" - guideline_annotation_rows.csv")
    print(" - pair_annotation_rows.csv")
    print(" - variant_annotation_filtered_rows.csv")
    print(" - mvp_candidate_drug_gene_edges.csv")
    print("\nBunları bana atarsan üçüncü aşamada temiz MVP seed dataset + risk motoru kodunu yazarız.")


if __name__ == "__main__":
    main()
