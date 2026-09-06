# H04 - unresolved questions

The mechanism is implemented and tested. What is open is who uses it, on what, and under what authority.

## Open

- Who is the data owner? The mechanism requires a name and a role and will not supply either.
- May a decision be recorded while WP-23's role assignment set is empty, so that the recorded role can be checked against nothing?
- After a rejection, may the same report be approved later, or does a rejection require a new build?
- Should the ledger live beside the data, in the database, or both? It is currently a file, because the database is not reachable from either environment here and a decision that exists only in an unreachable database is not evidence.
- Does a decision expire? A source policy read once is not a policy forever, and the same argument applies to a dataset somebody approved a year ago.

