"""Google Cloud Storage, natively: ``gs://`` locations, no HMAC key (#1358).

Credentials, in order: a service-account key file (``DEPICTIO_GCS_SERVICE_ACCOUNT_PATH``),
else Application Default Credentials, which is how Workload Identity reaches a
pod (the GKE metadata server) and how ``gcloud auth application-default login``
reaches a laptop. External-account Workload Identity Federation is not
supported by ``object_store`` yet.

Delta commits use GCS's own preconditions, so no ``AWS_S3_ALLOW_UNSAFE_RENAME``.
Signed URLs come from the key file, or from IAM ``signBlob`` without one (the
service account needs ``iam.serviceAccounts.signBlob`` on itself).

``endpoint_url`` points at an emulator (fake-gcs-server, the XML-API build that
``object_store`` tests against): requests go there unauthenticated.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from depictio.models.storage.obstore_backend import ObstoreBackend
from depictio.models.storage.registry import register_backend


def _emulator_key(endpoint_url: str) -> str:
    """A service-account key ``object_store`` reads as "this base URL, no OAuth"."""
    return json.dumps(
        {
            "gcs_base_url": endpoint_url.rstrip("/"),
            "disable_oauth": True,
            "client_email": "",
            "private_key": "",
            "private_key_id": "",
        }
    )


@register_backend
class GCSBackend(ObstoreBackend):
    """The instance bucket on Google Cloud Storage."""

    name: ClassVar[str] = "gcs"
    scheme: ClassVar[str] = "gs"
    fsspec_protocol: ClassVar[str] = "gs"

    def _store_config(self) -> dict[str, Any]:
        cfg = self.config
        config: dict[str, Any] = {"bucket": self.bucket}
        if cfg.endpoint_url:
            config["service_account_key"] = _emulator_key(cfg.endpoint_url)
        elif cfg.service_account_path:
            config["service_account"] = cfg.service_account_path
        elif cfg.anonymous:
            config["skip_signature"] = True
        return config

    def _client_options(self) -> dict[str, Any]:
        options = super()._client_options()
        if self.config.endpoint_url and self.config.endpoint_url.startswith("http://"):
            options["allow_http"] = True
        return options

    def _make_store(self) -> Any:
        from obstore.store import GCSStore

        config = self._store_config()
        config.pop("bucket")
        return GCSStore(
            self.bucket,
            config=config,
            client_options=self._client_options() or None,
            retry_config=self._retry_config(),
        )

    def storage_options(self) -> dict[str, str]:
        """The same store for Polars and delta-rs, in their ``google_*`` spelling.

        Empty under ADC: both read the same environment ``obstore`` does.
        """
        options: dict[str, str] = {}
        for key, value in self._store_config().items():
            if key == "bucket":
                continue
            options[f"google_{key}"] = "true" if value is True else str(value)
        if self._client_options().get("allow_http"):
            options["allow_http"] = "true"
        return options
