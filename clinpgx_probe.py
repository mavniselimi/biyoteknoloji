#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Jun 20 16:27:53 2026

@author: ferob
"""

# clinpgx_probe.py
# Amaç: ClinPGx API'den gen, ilaç/chemical ve guideline annotation verisini keşfetmek.
# Klinik karar üretmez; sadece veri çeker ve gösterir.

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


BASE_URL = "https://api.clinpgx.org/v1"

# Swagger sayfasında görünen OpenAPI dosyası.
OPENAPI_URLS = [
    "https://api.clinpgx.org/openapi.json",
    "https://api.clinpgx.org/swagger/openapi.json",
]

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "pgx-mvp-probe/0.1",
}

# ClinPGx tarafında agresif istek atmayalım.
REQUEST_DELAY_SECONDS = 0.6


def safe_get(url: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[requests.Response]]:
    """GET isteği atar; JSON dönerse parse eder, hata olursa açıklayıcı basar."""
    time.sleep(REQUEST_DELAY_SECONDS)

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        print(f"\n[NETWORK ERROR] {url}")
        print(exc)
        return None, None

    if not response.ok:
        print(f"\n[HTTP {response.status_code}] {response.url}")
        print(response.text[:500])
        return None, response

    try:
        return response.json(), response
    except ValueError:
        print(f"\n[JSON PARSE ERROR] {response.url}")
        print(response.text[:500])
        return None, response


def load_openapi() -> Dict[str, Any]:
    """OpenAPI JSON'u çeker."""
    last_error = None

    for url in OPENAPI_URLS:
        data, response = safe_get(url)
        if isinstance(data, dict) and "paths" in data:
            print(f"[OK] OpenAPI yüklendi: {url}")
            return data

        last_error = response

    raise RuntimeError(
        "OpenAPI JSON yüklenemedi. Swagger sayfasından openapi.json yolunu tekrar kontrol et."
    )


def print_available_endpoints(spec: Dict[str, Any]) -> None:
    """API'deki endpointleri ve kısa açıklamalarını gösterir."""
    print("\n=== AVAILABLE ENDPOINTS ===")

    paths = spec.get("paths", {})
    for path, methods in sorted(paths.items()):
        get_op = methods.get("get", {})
        desc = get_op.get("summary") or get_op.get("description") or ""
        print(f"GET {path:55s} {desc}")


def get_query_param_names(spec: Dict[str, Any], path: str) -> List[str]:
    """Bir endpoint için OpenAPI'de tanımlı query parametre adlarını bulur."""
    op = spec.get("paths", {}).get(path, {}).get("get", {})
    params = op.get("parameters", [])

    names = []
    for p in params:
        if p.get("in") == "query" and p.get("name"):
            names.append(p["name"])

    return names


def flatten_items(payload: Any) -> List[Any]:
    """
    API cevabı liste, dict, data/items/results gibi gelebilir.
    Bunu mümkün olduğunca listeye çevirir.
    """
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

        # Eğer tek obje geldiyse onu listeye koy.
        return [payload]

    return []


def compact_value(value: Any, max_len: int = 180) -> str:
    """Uzun JSON değerlerini tek satırlık kısaltır."""
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)

    text = " ".join(text.split())
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def summarize_object(obj: Any) -> Dict[str, str]:
    """Dönen objeden MVP için işe yarayabilecek alanları seçer."""
    if not isinstance(obj, dict):
        return {"value": compact_value(obj)}

    preferred_keys = [
        "id",
        "name",
        "symbol",
        "type",
        "objCls",
        "url",
        "title",
        "source",
        "evidenceLevel",
        "recommendation",
        "text",
        "description",
        "summary",
        "statement",
        "genes",
        "chemicals",
        "variants",
        "diseases",
        "phenotypes",
    ]

    summary = {}
    for key in preferred_keys:
        if key in obj and obj[key] not in [None, "", [], {}]:
            summary[key] = compact_value(obj[key])

    # Hiç beklenen alan yoksa ilk birkaç alanı göster.
    if not summary:
        for key, value in list(obj.items())[:8]:
            summary[key] = compact_value(value)

    return summary


def print_result(title: str, payload: Any, max_items: int = 5) -> List[Any]:
    """Cevabı okunabilir şekilde ekrana basar."""
    items = flatten_items(payload)

    print(f"\n=== {title} ===")
    print(f"Toplam görünen kayıt: {len(items)}")

    for idx, item in enumerate(items[:max_items], start=1):
        print(f"\n--- Kayıt {idx} ---")
        summary = summarize_object(item)
        for key, value in summary.items():
            print(f"{key}: {value}")

    return items


def build_candidate_params(spec: Dict[str, Any], path: str, term: str) -> List[Dict[str, Any]]:
    """
    Endpoint parametre isimleri kesin değişebilir.
    Bu yüzden hem OpenAPI'den gelen parametreleri hem de yaygın arama parametrelerini dener.
    """
    declared = set(get_query_param_names(spec, path))

    common_search_keys = [
        "q",
        "query",
        "search",
        "term",
        "name",
        "symbol",
        "id",
        "identifier",
    ]

    common_limit_keys = [
        "limit",
        "size",
        "pageSize",
        "count",
    ]

    candidate_params: List[Dict[str, Any]] = []

    # 1) Hiç parametresiz dene.
    candidate_params.append({})

    # 2) OpenAPI query parametreleri varsa onları kullan.
    if declared:
        for key in declared:
            low = key.lower()
            if any(hint in low for hint in ["q", "query", "search", "term", "name", "symbol", "id"]):
                params = {key: term}
                for limit_key in declared:
                    if limit_key in common_limit_keys:
                        params[limit_key] = 5
                candidate_params.append(params)

    # 3) Yaygın parametre isimlerini de dene.
    # Eğer OpenAPI query parametrelerini parse edemediysek bu özellikle işe yarar.
    for key in common_search_keys:
        params = {key: term}

        if not declared:
            params["limit"] = 5
        else:
            for limit_key in declared:
                if limit_key in common_limit_keys:
                    params[limit_key] = 5

        candidate_params.append(params)

    # Aynı parametreleri tekrarlama.
    unique = []
    seen = set()
    for p in candidate_params:
        marker = json.dumps(p, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            unique.append(p)

    return unique


def query_endpoint(spec: Dict[str, Any], path: str, term: str, max_success: int = 1) -> List[Any]:
    """
    Verilen endpointte farklı query parametreleriyle arama yapar.
    İlk başarılı sonucu döndürür.
    """
    url = BASE_URL + path
    print(f"\n\n### Endpoint deneniyor: GET {path}")
    print(f"Aranan terim: {term}")

    successes = []

    for params in build_candidate_params(spec, path, term):
        payload, response = safe_get(url, params=params)

        if payload is None:
            continue

        items = flatten_items(payload)
        print(f"[OK] {response.url} -> {len(items)} kayıt")

        # Kayıt varsa göster.
        if items:
            print_result(f"{path} | params={params}", payload)
            successes.append(payload)

        if len(successes) >= max_success:
            break

    if not successes:
        print(f"[NO RESULT] {path} içinde '{term}' için anlamlı kayıt bulunamadı.")

    return successes


def save_json(payload: Any, filename: str) -> None:
    out_dir = Path("clinpgx_outputs")
    out_dir.mkdir(exist_ok=True)

    path = out_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SAVED] {path}")


def main() -> None:
    spec = load_openapi()

    print_available_endpoints(spec)

    print("\n\n=== RELEVANT PARAMS ===")
    for path in [
        "/data/gene",
        "/data/chemical",
        "/data/guidelineAnnotation",
        "/data/variant/",
        "/data/variantAnnotation",
        "/report/pair/{firstObjId}/{secondObjId}/{resultType}",
        "/report/connectedObjects/{id}/{type}",
    ]:
        if path in spec.get("paths", {}):
            print(f"{path}: query params = {get_query_param_names(spec, path)}")
        else:
            print(f"{path}: OpenAPI içinde bulunamadı.")

    # MVP için ilk bakacağımız şeyler:
    # gen → CYP2C19 / CYP2D6
    # chemical/drug → clopidogrel / amitriptyline
    # guidelineAnnotation → gen-drug ilişkisi yakalama denemesi
    test_queries = [
        ("/data/gene", "CYP2C19"),
        ("/data/gene", "CYP2D6"),
        ("/data/chemical", "clopidogrel"),
        ("/data/chemical", "amitriptyline"),
        ("/data/guidelineAnnotation", "CYP2C19"),
        ("/data/guidelineAnnotation", "clopidogrel"),
        ("/data/variantAnnotation", "CYP2C19"),
    ]

    collected = {}

    for path, term in test_queries:
        if path not in spec.get("paths", {}):
            print(f"\n[SKIP] {path} OpenAPI içinde yok.")
            continue

        results = query_endpoint(spec, path, term)
        collected[f"{path}::{term}"] = results

    save_json(collected, "first_probe_results.json")

    print("\n\nBitti.")
    print("Çıktı dosyası: clinpgx_outputs/first_probe_results.json")
    print("Sonraki adım: Dönen JSON alanlarına göre drug_gene_edges.csv üretmek.")


if __name__ == "__main__":
    main()