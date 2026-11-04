# SAML configuration before the move to OIDC

These files are the Helm configuration as it was before SAML was removed in favour of
OpenID Connect (issue #1336). They are kept for reference only, so that the previous
service-provider settings (attribute mappings, labels, IdP registration notes) can be
looked up when configuring the OIDC provider.

The removal happens on branch `feat/oidc-sso-1336`, in commit a6998b1 ("feat(auth): replace SAML and Google OAuth with generic OIDC SSO (API core)").

Contents:

- `values-embl-internal-dev.yaml`, `values-embl-internal-prod.yaml`, `values-embl-demo-base.yaml`:
  values files as they were before the migration.
- `configmaps.yaml.txt`: the chart's `templates/configmaps.yaml` including its SAML block
  (renamed so Helm never renders it).

They are reference only and never deployed. The folder is excluded from chart packaging
through `.helmignore`.
