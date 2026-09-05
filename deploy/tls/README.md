# TLS material

Empty on purpose. Certificates and private keys are mounted here at deploy
time and are never committed - `.gitignore` excludes everything in this
directory except this file, and `.dockerignore` keeps the directory out of
every build context.

## Staging

Mount a real certificate and key issued for the staging hostname:

    deploy/tls/server.crt
    deploy/tls/server.key

`docker-compose.wp24.yml` mounts this directory read-only into the proxy.

## Local rehearsal

A locally generated internal CA is permitted for a rehearsal, under three
conditions that `pgx-deploy` enforces rather than suggests:

1. the result is labelled `LOCAL_STAGING_REHEARSAL` in every artifact;
2. verification is performed **against the generated CA** - the CA
   certificate is passed to the client explicitly;
3. `curl -k` is never used as evidence. Disabling verification does not
   demonstrate TLS, it demonstrates that verification was switched off, and a
   report containing it would be describing an experiment that did not test
   what it claims.

A rehearsal is never reported as staging TLS, and
`https_termination_observed` stays false until a real certificate is verified
against a chain the client did not generate.
