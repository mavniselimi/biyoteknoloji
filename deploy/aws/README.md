# AWS Lightsail / EC2 deployment

This directory publishes the PGx candidate demonstration from one AWS host.
Caddy is the only public container: it listens on **80/tcp** and **443/tcp**,
redirects HTTP to HTTPS, and automatically obtains and renews the certificate.
The application and PostgreSQL ports are private to the Compose network.
No domain is required: Caddy requests a short-lived, publicly trusted Let's
Encrypt certificate for the Lightsail static IPv4 address. A DNS name remains
supported when one is available.

The deployed release is explicitly `CANDIDATE`. It is a research/prototype
demonstration and is not externally reviewed, clinically validated, or a
governed production release.

## 1. Prepare Lightsail

1. Create an Ubuntu 24.04 Lightsail instance with at least 2 vCPU, 4 GiB RAM,
   and 20 GiB disk. Attach a Lightsail static IP so the address does not
   change.
2. Under the instance's **Networking > IPv4 Firewall**, add HTTP/TCP 80 and
   HTTPS/TCP 443 for all IPv4 addresses. Restrict SSH 22 to your own IP when
   you do not need the Lightsail browser SSH client.
3. A domain is optional. If you have one, point its DNS `A` record to the
   static IP before deployment. Otherwise use the static IP directly.

With an authenticated AWS CLI, the two Lightsail rules can instead be added
with:

```bash
./deploy/aws/open-lightsail-ports.sh INSTANCE_NAME eu-central-1
```

The script touches only ports 80 and 443; it never widens SSH access.

For EC2 rather than Lightsail, associate an Elastic IP and run the Security
Group version instead:

```bash
./deploy/aws/open-ports.sh sg-0123456789abcdef0 eu-central-1
```

## 2. Prepare the instance

Clone this repository onto the Lightsail/EC2 instance, then run:

```bash
sudo ./deploy/aws/install-docker-ubuntu.sh
```

Log out and back in once after the installer adds your user to the `docker`
group. Then initialize deployment-local configuration and secrets:

```bash
./deploy/aws/deploy.sh init
nano deploy/aws/.env
```

Replace the example with the Lightsail static public IPv4 address (no
`https://`, port, or path):

```dotenv
DOMAIN=18.194.123.45
```

You may put a DNS hostname there instead if you later add one. `init` generates
a random PostgreSQL password and writes the three secret files with mode
`0600` (the application DSN is group-readable at `0640`). These files and
`deploy/aws/.env` are ignored by Git and excluded from Docker builds.
It also makes only the explicitly mounted, non-secret candidate runtime inputs
readable by the image's unprivileged UID; `check` rejects unreadable inputs.
On Linux, `deploy.sh` grants the container only the current user's primary
group so the DSN never needs to become world-readable.

## 3. Publish

Once the static IP is attached (and optional DNS resolves to it):

```bash
./deploy/aws/deploy.sh check
./deploy/aws/deploy.sh deploy
./deploy/aws/deploy.sh bootstrap
./deploy/aws/deploy.sh status
```

`deploy` builds the locked application image, starts PostgreSQL, applies the
Alembic migration once as an explicit operation, and starts the application
and Caddy. It never performs migrations from a container startup command.

`bootstrap` creates the `DEMO_USER` named in `.env`. Its generated password is
written only to `.deploy-out/aws/demo-credentials.txt` with restrictive file
permissions. Read it on the AWS host, sign in, then remove that file when it
is no longer needed.

Open `https://YOUR_STATIC_IP/` (or the configured DNS name). Certificate
issuance can take a minute after the first start; inspect it with:

```bash
./deploy/aws/deploy.sh logs
```

## Operations

```bash
./deploy/aws/deploy.sh status   # containers plus public liveness probe
./deploy/aws/deploy.sh restart  # restart app/proxy, preserve PostgreSQL
./deploy/aws/deploy.sh logs     # follow app and Caddy logs
./deploy/aws/deploy.sh stop     # stop containers, preserve every named volume
```

Back up the Docker volume before instance replacement or destructive
maintenance.
For a multi-instance or production clinical architecture, move PostgreSQL to
RDS, store images in ECR, put an ALB in front, and complete the project's human
and scientific approval gates; this single-host layout intentionally does not
claim those properties.
