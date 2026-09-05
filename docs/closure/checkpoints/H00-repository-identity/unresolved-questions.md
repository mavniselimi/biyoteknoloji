# H00 - unresolved questions

The baseline exists and is measured. These are the things about it that a person still has to settle.

## Open

- Is the author identity on the baseline commit the identity this project should carry? It cannot be changed without rewriting history.
- Where, if anywhere, is this repository published? The answer interacts with the quarantined data in the tree.
- Does the version the baseline tag names match how this project intends to number releases?
- Three files under `docs/examples/wp04/` record a session-scoped cache path from the machine that produced them. They are recorded drill output with a content hash and were committed unmodified rather than edited after the fact. Should the producer scrub that field before writing, and should the existing files be regenerated?

