<!--
DRAFT NOTE (remove before publishing):
- Publishes to depictio-docs blog; move/PR across. `authors:` slug must exist in .authors.yml.
- Fully shipped topic, no readiness gates: docker-compose, helm-charts/, kubernetes/, Gateway API
  (#882), Celery workers, MinIO/S3 + Delta Lake all present on main (v1.1.4).
- Confirm exact compose file names / Helm values keys against the deployment docs before publishing.
-->
---
date: 2026-07-15
authors:
  - thomas-weber
categories:
  - Tutorials
  - Features
---

# 🔒 Self-hosting Depictio: from Docker Compose to Kubernetes

The fastest way to turn your data into a dashboard is to upload it to someone
else's cloud. For a lot of us — patient genomes, unpublished results, data under
a DUA — that's simply off the table. Depictio is self-hosted by design, so you
get interactive dashboards without your data ever leaving your infrastructure.

<!-- more -->

## 🔒 Why self-host

Self-hosting isn't only about privacy, though that's the headline. It also means:
no vendor account, no per-seat billing, no usage tracking, and no "we changed our
terms" email. You run the software, you own the data, and because it's
open-source you can audit exactly what it does.

Depictio is built to run the same way from a laptop to a production cluster. Pick
the path that matches your stage.

## 🐳 The quickest path: Docker Compose

For a single machine — your laptop, a lab workstation, a VM — Docker Compose
brings up the whole stack (the API, the viewer, the database, object storage, and
the worker) with one command. Clone the repository, point it at an environment
file, and start it. This is the right choice for evaluating Depictio, for a small
team, or for a demo.

## 🔧 Configuration and environment

Depictio is configured through environment variables, with the settings model as
the single source of truth. That covers the essentials: where the database
lives, the object-storage endpoint and credentials, the public URL, and
authentication. Keeping configuration in the environment (not baked into images)
is what lets the same containers run unchanged from Compose to Kubernetes.

## ☸️ Production: Helm and Kubernetes

When you outgrow a single host, the provided **Helm chart** deploys Depictio to
Kubernetes: separate deployments for the API, viewer, and workers, each scalable
on its own, with ingress and configuration expressed as values. This is the path
for a core facility or institute serving many users, where you want rolling
updates, resource limits, and horizontal scaling.

## 🗄️ Storage: object store + Delta Lake

Depictio keeps tabular data in **Delta Lake** format on **S3-compatible object
storage** — MinIO when you self-host everything, or a managed bucket (e.g. AWS
S3) in the cloud. Delta gives you columnar, versioned tables that Polars reads
efficiently; the object store keeps large data off the application containers.

## 🔑 Authentication and the Gateway API

Depictio uses token-based auth with role-based access across users, groups, and
projects. For deployments that sit behind institutional ingress, a **Gateway API**
option provides a clean front door to the backend, so you can put Depictio behind
your own routing and TLS without contorting the app.

## 💾 Backups

Because state lives in well-defined places — the database and the object store —
backups are conventional: snapshot the database, and back up (or version) the
bucket. There are also backward-compatibility guards so a backup taken on one
version can be restored on another with confidence.

## ⚙️ Scaling the workers

Heavy work — ingestion, and compute-intensive steps behind some advanced
visualisations — runs on **Celery** workers, separate from the request path. That
separation means a long job never blocks the UI, and you can scale workers
independently (and, on Kubernetes, put long-running jobs on their own queue).

## 🚀 Get started

- **Evaluate:** bring it up with Docker Compose in a few minutes.
- **Go to production:** deploy the Helm chart to your cluster.
- **Read the deployment docs** for exact commands, values, and storage options.

Interactive dashboards and data sovereignty shouldn't be a trade-off. Self-host
Depictio and they aren't.
