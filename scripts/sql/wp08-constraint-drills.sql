-- WP-08 constraint drills: 35 cases against migration 0006 on real PostgreSQL.
--
-- Each case states what it attempts and whether the database is expected to
-- accept or refuse it. A drill that is expected to FAIL and succeeds is a
-- schema defect, not a passing test: E21 and E34 were written after two such
-- defects were found, where a NULL column collapsed a CHECK to NULL and
-- PostgreSQL admitted the row.
--
-- Reproduce (no Alembic, no network):
--   initdb -D "$PGDATA" -U pgx
--   pg_ctl -D "$PGDATA" -o "-p 55408 -k /tmp/pgsock08 -c listen_addresses=" -l /tmp/pg.log start
--   createdb -h /tmp/pgsock08 -p 55408 -U pgx pgx_wp08
--   for f in wp02 wp03 wp05 wp06 wp07 wp08; do
--     psql -h /tmp/pgsock08 -p 55408 -U pgx -d pgx_wp08 -v ON_ERROR_STOP=1 \
--          -f build/$f-schema.sql
--   done
--   psql -h /tmp/pgsock08 -p 55408 -U pgx -d pgx_wp08 \
--        -f scripts/sql/wp08-constraint-drills.sql
--
-- The build/*.sql files are produced by scripts/render_wp0*_schema.py. They
-- are rendered DDL executed on a real server; they are not Alembic evidence.

\set ON_ERROR_STOP 0
\pset pager off
-- Seed the minimum rows WP-08 references.
INSERT INTO source_registry (id, source_key, display_name, role, version_policy, license_policy, citation_policy, active)
VALUES ('a0000000-0000-4000-8000-000000000001','clinpgx.api','ClinPGx API','SUPPORTING_ANNOTATION','unknown','unknown','unknown',true),
       ('a0000000-0000-4000-8000-000000000002','dpwg.knmp','DPWG','PRIMARY_GUIDELINE','unknown','unknown','unknown',true);
INSERT INTO dataset_versions (id, public_id, status, manifest_hash)
VALUES ('11111111-1111-4111-8111-111111111111','PGX-DATA-20260830-900','BUILDING','sha256:0000000000000000000000000000000000000000000000000000000000000000');
INSERT INTO genes (id, normalized_symbol, preferred_name)
VALUES ('22222222-2222-4222-8222-222222222222','CYP2C19','cytochrome P450 2C19');
INSERT INTO drugs (id, normalized_name, preferred_name)
VALUES ('33333333-3333-4333-8333-333333333333','clopidogrel','clopidogrel');
INSERT INTO evidence_builds
 (id, dataset_public_id, evidence_build_key, content_hash, snapshot_manifest_hash,
  canonical_build_key, canonical_build_content_hash, allocation_content_hash,
  build_relative_path, mode, production_eligible, blocking_issue_count, built_at)
VALUES ('44444444-4444-4444-8444-444444444444','PGX-DATA-20260830-900','PGX-DATA-20260830-900/abc',
        'sha256:1111111111111111111111111111111111111111111111111111111111111111',
        'sha256:2222222222222222222222222222222222222222222222222222222222222222',
        'PGX-DATA-20260830-900/def',
        'sha256:3333333333333333333333333333333333333333333333333333333333333333',
        'sha256:4444444444444444444444444444444444444444444444444444444444444444',
        'data/evidence/PGX-DATA-20260830-900','LEGACY_MIGRATION',false,3235, now());

\echo '--- E1 a production-eligible LEGACY_MIGRATION build (expect FAIL)'
INSERT INTO evidence_builds (id, dataset_public_id, evidence_build_key, content_hash, snapshot_manifest_hash, canonical_build_key, canonical_build_content_hash, allocation_content_hash, build_relative_path, mode, production_eligible, built_at)
VALUES ('44444444-4444-4444-8444-444444444445','PGX-DATA-20260830-900','k2','sha256:1111111111111111111111111111111111111111111111111111111111111111','sha256:2222222222222222222222222222222222222222222222222222222222222222','c','sha256:3333333333333333333333333333333333333333333333333333333333333333','sha256:4444444444444444444444444444444444444444444444444444444444444444','data/evidence/x','LEGACY_MIGRATION',true, now());

\echo '--- E2 an eligible build carrying blocking issues (expect FAIL)'
INSERT INTO evidence_builds (id, dataset_public_id, evidence_build_key, content_hash, snapshot_manifest_hash, canonical_build_key, canonical_build_content_hash, allocation_content_hash, build_relative_path, mode, production_eligible, blocking_issue_count, built_at)
VALUES ('44444444-4444-4444-8444-444444444446','PGX-DATA-20260830-900','k3','sha256:1111111111111111111111111111111111111111111111111111111111111111','sha256:2222222222222222222222222222222222222222222222222222222222222222','c','sha256:3333333333333333333333333333333333333333333333333333333333333333','sha256:4444444444444444444444444444444444444444444444444444444444444444','data/evidence/y','PRODUCTION',true, 5, now());

\echo '--- E3 an UNKNOWN_LEGACY record with no version string (expect ok)'
INSERT INTO evidence_records
 (id, source_registry_id, dataset_version_id, evidence_build_id, natural_key,
  record_type, record_type_mapping_status, source_record_id, source_record_version,
  source_record_version_status, origin_source_status, raw_hash, source_payload_hash,
  evidence_content_hash)
VALUES ('55555555-5555-4555-8555-555555555551','a0000000-0000-4000-8000-000000000001',
        '11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444',
        'PGX-DATA-20260830-900|clinpgx.api|VARIANT_ANNOTATION|981351915|UNKNOWN_LEGACY',
        'VARIANT_ANNOTATION','CONFIRMED','981351915', NULL,'UNKNOWN_LEGACY','NOT_STATED_BY_SOURCE',
        'sha256:5555555555555555555555555555555555555555555555555555555555555555',
        'sha256:6666666666666666666666666666666666666666666666666666666666666666',
        'sha256:7777777777777777777777777777777777777777777777777777777777777777');
SELECT source_record_version IS NULL AS e3_version_is_null, source_record_version_status AS e3_status FROM evidence_records WHERE id='55555555-5555-4555-8555-555555555551';

\echo '--- E4 UNKNOWN_LEGACY carrying a fabricated version string (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_hash)
VALUES ('55555555-5555-4555-8555-555555555552','a0000000-0000-4000-8000-000000000001','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','nk2','VARIANT_ANNOTATION','CONFIRMED','x','v1','UNKNOWN_LEGACY','NOT_STATED_BY_SOURCE','sha256:5555555555555555555555555555555555555555555555555555555555555555');

\echo '--- E5 KNOWN with no version value (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_hash)
VALUES ('55555555-5555-4555-8555-555555555553','a0000000-0000-4000-8000-000000000001','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','nk3','VARIANT_ANNOTATION','CONFIRMED','x',NULL,'KNOWN','NOT_STATED_BY_SOURCE','sha256:5555555555555555555555555555555555555555555555555555555555555555');

\echo '--- E6 STATED_BY_SOURCE with no origin key (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_hash)
VALUES ('55555555-5555-4555-8555-555555555554','a0000000-0000-4000-8000-000000000001','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','nk4','GUIDELINE_ANNOTATION','CONFIRMED','PA1','0','KNOWN','STATED_BY_SOURCE','sha256:5555555555555555555555555555555555555555555555555555555555555555');

\echo '--- E7 NOT_STATED_BY_SOURCE carrying an origin key anyway (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, origin_source_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_hash)
VALUES ('55555555-5555-4555-8555-555555555555','a0000000-0000-4000-8000-000000000001','a0000000-0000-4000-8000-000000000002','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','nk5','GUIDELINE_ANNOTATION','CONFIRMED','PA1','0','KNOWN','NOT_STATED_BY_SOURCE','sha256:5555555555555555555555555555555555555555555555555555555555555555');

\echo '--- E8 a well-formed guideline record with a stated origin (expect ok)'
INSERT INTO evidence_records (id, source_registry_id, origin_source_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_origin_value, raw_hash, source_payload_hash, evidence_content_hash, finalized_at, production_eligible)
VALUES ('55555555-5555-4555-8555-555555555556','a0000000-0000-4000-8000-000000000001','a0000000-0000-4000-8000-000000000002','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','PGX-DATA-20260830-900|clinpgx.api|GUIDELINE_ANNOTATION|PA166104948|0','GUIDELINE_ANNOTATION','CONFIRMED','PA166104948','0','KNOWN','STATED_BY_SOURCE','DPWG','sha256:5555555555555555555555555555555555555555555555555555555555555555','sha256:6666666666666666666666666666666666666666666666666666666666666666','sha256:7777777777777777777777777777777777777777777777777777777777777777', now(), true);

\echo '--- E9 a PENDING_REVIEW mapping marked production eligible (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, origin_source_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_origin_value, raw_hash, finalized_at, production_eligible)
VALUES ('55555555-5555-4555-8555-555555555557','a0000000-0000-4000-8000-000000000001','a0000000-0000-4000-8000-000000000002','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','nk7','DRUG_LABEL_ANNOTATION','PENDING_REVIEW','PA2','0','KNOWN','STATED_BY_SOURCE','FDA','sha256:5555555555555555555555555555555555555555555555555555555555555555', now(), true);

\echo '--- E10 two records sharing one natural key in one build (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_hash)
VALUES ('55555555-5555-4555-8555-555555555558','a0000000-0000-4000-8000-000000000001','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','PGX-DATA-20260830-900|clinpgx.api|VARIANT_ANNOTATION|981351915|UNKNOWN_LEGACY','VARIANT_ANNOTATION','CONFIRMED','981351915',NULL,'UNKNOWN_LEGACY','NOT_STATED_BY_SOURCE','sha256:5555555555555555555555555555555555555555555555555555555555555555');

\echo '--- E11 editing a finalized record (expect FAIL, trigger)'
UPDATE evidence_records SET source_payload_hash='sha256:9999999999999999999999999999999999999999999999999999999999999999' WHERE id='55555555-5555-4555-8555-555555555556';

\echo '--- E12 deleting any evidence record (expect FAIL, trigger)'
DELETE FROM evidence_records WHERE id='55555555-5555-4555-8555-555555555551';

\echo '--- E13 editing a NOT-yet-finalized record (expect ok)'
UPDATE evidence_records SET source_text='assembled later' WHERE id='55555555-5555-4555-8555-555555555551';

\echo '--- E14 one record linked to two genes (expect ok, 1 row here)'
INSERT INTO evidence_genes (id, evidence_record_id, gene_id, canonical_key, role, source_field)
VALUES ('66666666-6666-4666-8666-666666666661','55555555-5555-4555-8555-555555555556','22222222-2222-4222-8222-222222222222','GENE:CYP2C19','RELATED_ENTITY','relatedGenes');
SELECT count(*) AS e14_gene_links FROM evidence_genes;

\echo '--- E15 a gene link with a DRUG canonical key (expect FAIL)'
INSERT INTO evidence_genes (id, evidence_record_id, gene_id, canonical_key, role)
VALUES ('66666666-6666-4666-8666-666666666662','55555555-5555-4555-8555-555555555556','22222222-2222-4222-8222-222222222222','DRUG:clopidogrel','RELATED_ENTITY');

\echo '--- E16 an orphan gene link (expect FAIL, FK)'
INSERT INTO evidence_genes (id, evidence_record_id, gene_id, canonical_key, role)
VALUES ('66666666-6666-4666-8666-666666666663','99999999-9999-4999-8999-999999999999','22222222-2222-4222-8222-222222222222','GENE:CYP2C19','RELATED_ENTITY');

\echo '--- E17 a text fragment with empty text (expect FAIL)'
INSERT INTO evidence_text_fragments (id, evidence_record_id, field_name, ordinal, text, text_hash, exact_text_hash)
VALUES ('77777777-7777-4777-8777-777777777771','55555555-5555-4555-8555-555555555556','summaryMarkdown.html',0,'','sha256:8888888888888888888888888888888888888888888888888888888888888888','sha256:8888888888888888888888888888888888888888888888888888888888888888');

\echo '--- E18 a source quotation containing dosing language (expect ok)'
INSERT INTO evidence_text_fragments (id, evidence_record_id, field_name, ordinal, text, text_format, text_hash, exact_text_hash)
VALUES ('77777777-7777-4777-8777-777777777772','55555555-5555-4555-8555-555555555556','summaryMarkdown.html',0,'Avoid clopidogrel use in patients who are CYP2C19 poor metabolizers; consider an alternative antiplatelet therapy.','text/html','sha256:8888888888888888888888888888888888888888888888888888888888888888','sha256:8888888888888888888888888888888888888888888888888888888888888888');
SELECT length(text) AS e18_text_len FROM evidence_text_fragments WHERE id='77777777-7777-4777-8777-777777777772';

\echo '--- E19 a publication with a non-digit PMID (expect FAIL)'
INSERT INTO publication_references (id, pmid) VALUES ('88888888-8888-4888-8888-888888888881','not-a-pmid');

\echo '--- E20 a valid publication (expect ok)'
INSERT INTO publication_references (id, pmid, doi, title, publication_year, identity)
VALUES ('88888888-8888-4888-8888-888888888882','21412232','10.1038/clpt.2011.34','Pharmacogenetics: from bench to byte--an update of guidelines.',2011,'pmid:21412232');

\echo '--- E21 an identity matching neither pmid nor doi, doi present (expect FAIL)'
INSERT INTO publication_references (id, pmid, doi, identity) VALUES ('88888888-8888-4888-8888-888888888883','12345','10.1038/clpt.2011.99','title:something');

\echo '--- E22 two publications claiming one identity (expect FAIL)'
INSERT INTO publication_references (id, pmid, identity) VALUES ('88888888-8888-4888-8888-888888888884','21412232','pmid:21412232');

\echo '--- E23 a provenance row addressing neither a pointer nor a row (expect FAIL)'
INSERT INTO evidence_provenance (id, evidence_record_id, dataset_public_id, snapshot_manifest_hash, artifact_path, artifact_sha256, source_payload_hash)
VALUES ('99999999-9999-4999-8999-999999999991','55555555-5555-4555-8555-555555555556','PGX-DATA-20260830-900','sha256:2222222222222222222222222222222222222222222222222222222222222222','responses/pair_probe_raw.json','sha256:aaaa111111111111111111111111111111111111111111111111111111111111','sha256:6666666666666666666666666666666666666666666666666666666666666666');

\echo '--- E24 a provenance row addressing both (expect FAIL)'
INSERT INTO evidence_provenance (id, evidence_record_id, dataset_public_id, snapshot_manifest_hash, artifact_path, artifact_sha256, json_pointer, csv_row_number, source_payload_hash)
VALUES ('99999999-9999-4999-8999-999999999992','55555555-5555-4555-8555-555555555556','PGX-DATA-20260830-900','sha256:2222222222222222222222222222222222222222222222222222222222222222','responses/pair_probe_raw.json','sha256:aaaa111111111111111111111111111111111111111111111111111111111111','/a/b',3,'sha256:6666666666666666666666666666666666666666666666666666666666666666');

\echo '--- E25 two locators for one record, both retained (expect ok, 2 rows)'
INSERT INTO evidence_provenance (id, evidence_record_id, dataset_public_id, snapshot_manifest_hash, artifact_path, artifact_sha256, json_pointer, requested_container, source_payload_hash)
VALUES ('99999999-9999-4999-8999-999999999993','55555555-5555-4555-8555-555555555556','PGX-DATA-20260830-900','sha256:2222222222222222222222222222222222222222222222222222222222222222','responses/pair_probe_raw.json','sha256:aaaa111111111111111111111111111111111111111111111111111111111111','/CYP2C19::clopidogrel/pair/guidelineAnnotation/0','guidelineAnnotation','sha256:6666666666666666666666666666666666666666666666666666666666666666'),
       ('99999999-9999-4999-8999-999999999994','55555555-5555-4555-8555-555555555556','PGX-DATA-20260830-900','sha256:2222222222222222222222222222222222222222222222222222222222222222','responses/pair_probe_raw.json','sha256:aaaa111111111111111111111111111111111111111111111111111111111111','/CYP2C19::clopidogrel/pair/GuidelineAnnotation/0','GuidelineAnnotation','sha256:6666666666666666666666666666666666666666666666666666666666666666');
SELECT count(*) AS e25_locators FROM evidence_provenance WHERE evidence_record_id='55555555-5555-4555-8555-555555555556';

\echo '--- E26 an absolute artifact path (expect FAIL)'
INSERT INTO evidence_provenance (id, evidence_record_id, dataset_public_id, snapshot_manifest_hash, artifact_path, artifact_sha256, json_pointer, source_payload_hash)
VALUES ('99999999-9999-4999-8999-999999999995','55555555-5555-4555-8555-555555555556','PGX-DATA-20260830-900','sha256:2222222222222222222222222222222222222222222222222222222222222222','/etc/passwd','sha256:aaaa111111111111111111111111111111111111111111111111111111111111','/a','sha256:6666666666666666666666666666666666666666666666666666666666666666');

\echo '--- E27 an import issue with a lowercase code (expect FAIL)'
INSERT INTO evidence_import_issues (id, evidence_build_id, code, severity, subject, detail)
VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1','44444444-4444-4444-8444-444444444444','origin_missing','BLOCKING','x','y');

\echo '--- E28 a well-formed import issue (expect ok)'
INSERT INTO evidence_import_issues (id, evidence_build_id, evidence_record_id, code, severity, subject, detail, natural_key)
VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2','44444444-4444-4444-8444-444444444444','55555555-5555-4555-8555-555555555551','SOURCE_VERSION_UNKNOWN_LEGACY','BLOCKING','981351915','no version metadata survives for this record','PGX-DATA-20260830-900|clinpgx.api|VARIANT_ANNOTATION|981351915|UNKNOWN_LEGACY');
SELECT count(*) AS e28_issues FROM evidence_import_issues;

\echo '--- E29 the dataset is still BUILDING (expect BUILDING)'
SELECT status AS e29_status FROM dataset_versions WHERE public_id='PGX-DATA-20260830-900';

\echo '--- E30 an evidence publication link with no ordinal collision (expect ok)'
INSERT INTO evidence_publications (id, evidence_record_id, publication_reference_id, ordinal, source_field)
VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1','55555555-5555-4555-8555-555555555556','88888888-8888-4888-8888-888888888882',0,'literature');
SELECT count(*) AS e30_links FROM evidence_publications;

\echo '--- E31 a second publication at the same ordinal (expect FAIL)'
INSERT INTO evidence_publications (id, evidence_record_id, publication_reference_id, ordinal)
VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2','55555555-5555-4555-8555-555555555556','88888888-8888-4888-8888-888888888882',0);

\echo '--- E32 evidence_records has no project risk column (expect 0)'
SELECT count(*) AS e32_project_columns FROM information_schema.columns
WHERE table_name IN ('evidence_records','evidence_text_fragments','evidence_genes','evidence_drugs','evidence_provenance','publication_references')
  AND column_name IN ('risk','risk_level','demo_risk_level','risk_meaning','attention_level','plain_language_mvp','evidence_strength','usable_for_mvp','drug_behavior_hint','effect_direction','normalized_phenotype_group','candidate_score');

\echo '--- E33 a title-derived identity beside a NULL doi (expect FAIL)'
INSERT INTO publication_references (id, pmid, identity) VALUES ('88888888-8888-4888-8888-88888888888e','12345','title:something');

\echo '--- E34 production eligible with an absent record type mapping (expect FAIL)'
INSERT INTO evidence_records (id, source_registry_id, origin_source_id, dataset_version_id, evidence_build_id, natural_key, record_type, record_type_mapping_status, source_record_id, source_record_version, source_record_version_status, origin_source_status, raw_origin_value, raw_hash, finalized_at, production_eligible)
VALUES ('55555555-5555-4555-8555-5555555555d2','a0000000-0000-4000-8000-000000000001','a0000000-0000-4000-8000-000000000002','11111111-1111-4111-8111-111111111111','44444444-4444-4444-8444-444444444444','nk-d2','GUIDELINE_ANNOTATION',NULL,'PA9','0','KNOWN','STATED_BY_SOURCE','DPWG','sha256:5555555555555555555555555555555555555555555555555555555555555555', now(), true);

\echo '--- E35 an identity that legitimately derives from the doi (expect ok)'
INSERT INTO publication_references (id, doi, identity) VALUES ('88888888-8888-4888-8888-888888888885','10.1038/clpt.2011.35','doi:10.1038/clpt.2011.35');
SELECT count(*) AS e35_publications FROM publication_references;
