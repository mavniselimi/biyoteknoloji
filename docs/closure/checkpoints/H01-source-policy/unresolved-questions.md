# H01 - unresolved questions

Everything below is unknown, not merely undecided. A reviewer who approves a source while one of its rows is open is approving the unknown, which is the specific thing this file exists to prevent.

## Per source

### `cpic.database`

- **Gap:** the live data-usage policy page is a client-rendered application and did not render to readable text, so the CC0 declaration is confirmed from the distribution CPIC publishes rather than from the policy page itself. A human should confirm the policy page agrees.
- **Still unknown:** `AUTOMATED_ACQUISITION`
- **Note:** CC0 waives copyright; it says nothing about the rate at which a server may be queried, so automated acquisition stays UNKNOWN until the API's own terms are read.

### `cpic.api`

- **Gap:** the API's own terms of use, as distinct from the data licence, were not located. Terms for an interface and terms for its content are different documents and are not assumed to agree.
- **Still unknown:** `AUTOMATED_ACQUISITION`, `BULK_DOWNLOAD`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** The content licence does not license the service. Query-rate and bulk-access permissions are a separate question and remain unanswered.

### `cpic.publications`

- **Gap:** each guideline would have to be checked against its own publisher. The project does not need the publication text if it uses the database, which is why this is proposed for deferral rather than research.
- **Still unknown:** `LOCAL_STORAGE`, `INTERNAL_ANALYSIS`, `DERIVED_WORK_CREATION`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `AUTOMATED_ACQUISITION`, `BULK_DOWNLOAD`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** Citing a guideline is not reusing its text. The distinction matters for what the platform may display.

### `clinpgx.website`

- **Conflict:** `LICENCE_CONTRADICTS_ITS_OWN_USE_RESTRICTION`
- **Still unknown:** `DERIVED_WORK_CREATION`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `AUTOMATED_ACQUISITION`, `BULK_DOWNLOAD`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** The two halves of the statement cannot both be honoured: CC-BY-SA-4.0 permits commercial use and forbids adding restrictions, and the overlay does both. This is not a question a maintainer should answer.

### `clinpgx.api`

- **Conflict:** `MATERIAL_ALREADY_ACQUIRED_UNDER_UNDETERMINED_TERMS`
- **Gap:** the API terms are a separate document from the website terms and were not found. The evidence build already in this repository was acquired through this API, which makes the question retrospective as well as prospective.
- **Still unknown:** `LOCAL_STORAGE`, `INTERNAL_ANALYSIS`, `DERIVED_WORK_CREATION`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `AUTOMATED_ACQUISITION`, `BULK_DOWNLOAD`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** The quarantined evidence build in data/evidence/PGX-DATA-20260830-900 carries provider_source_key clinpgx.api throughout. Whatever is decided here applies to material already held.

### `dpwg.knmp`

- **Conflict:** `AUTHORITATIVE_BUT_NO_STATED_TERMS`
- **Gap:** absence of a statement is not permission. The machine-readable form of these recommendations reaches most consumers through the G-Standaard, which is licensed commercially by Z-Index and whose terms prohibit reproduction.
- **Still unknown:** `LOCAL_STORAGE`, `INTERNAL_ANALYSIS`, `DERIVED_WORK_CREATION`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `AUTOMATED_ACQUISITION`, `BULK_DOWNLOAD`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** DPWG's scientific standing is not in question. Its reuse terms are simply not stated anywhere the project could find, and the commercial channel that does carry the structured data forbids reproduction.

### `druglabel.fda`

- **Conflict:** `OPEN_API_TERMS_OVER_POSSIBLY_COPYRIGHTED_CONTENT`
- **Gap:** 17 U.S.C. 105 removes copyright from works of the United States government. A label authored by a sponsor and filed with the agency is not obviously such a work. The API terms and the content status are different questions and only the first is answered.
- **Still unknown:** `DERIVED_WORK_CREATION`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** Reading a label to decide what a rule says is not the same as republishing its wording, and the second is the one that is unresolved.

### `druglabel.titck`

- **Conflict:** `REQUIRED_FOR_JURISDICTION_BUT_UNREACHABLE`
- **Gap:** every attempt to reach the site failed before any document was read: the robots policy itself returned a server error or timed out. With no readable robots policy there is no robots-compliant automated route, and no terms document was seen at all.
- **Still unknown:** `LOCAL_STORAGE`, `INTERNAL_ANALYSIS`, `DERIVED_WORK_CREATION`, `AGGREGATED_REDISTRIBUTION`, `VERBATIM_REDISTRIBUTION`, `COMMERCIAL_USE`, `AUTOMATED_ACQUISITION`, `BULK_DOWNLOAD`, `THIRD_PARTY_SHARING`, `PUBLIC_DISPLAY`
- **Note:** The Turkish regulator is the one source a Turkish deployment would be expected to carry, and it is the one the project currently cannot reach at all.


## Questions that apply to every source

- Does the project accept material acquired before its source policy existed? The quarantined evidence build was acquired through `clinpgx.api` under terms nobody had established.
- What does the project do when a source's terms change after acquisition? Nothing currently re-checks them.
- Which jurisdiction's law governs these readings? The sources span the United States, the Netherlands and Turkey, and the deployment's jurisdiction is not recorded anywhere in the repository.

