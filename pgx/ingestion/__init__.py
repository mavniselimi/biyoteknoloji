# -*- coding: utf-8 -*-
"""Source acquisition (WP-04).

This package retrieves raw responses from scientific sources and records what it
did. It does not interpret them.

The boundary is worth stating plainly, because it is the one thing most likely
to be eroded later: **acquiring a record asserts nothing about that record.**
Nothing here decides that a gene symbol resolved, that two source records
describe the same drug, that an annotation means anything clinically, or that a
source may back a release. Those are WP-05 (source policy), WP-07 (canonical
resolution), WP-09 to WP-11 (curation and rules), and none of them exist yet.

What ingestion produces is: raw bytes, their SHA-256, the exact request that
produced them, and an honest account of whether the run finished.
"""
