# ADR 0001: The bioimage viewer complements dedicated image viewers

- Status: accepted
- Date: 2026-09-27
- Issue: #1086

## Context

OME-Zarr (OME-NGFF) is the interchange format for pyramidal, multiplexed and
spatial imaging, and spatial-omics pipelines increasingly hand their results
over as OME-Zarr, SpatialData or pyramidal OME-TIFF. Depictio had no way to show
an image next to the tables it already serves.

Dedicated viewers already cover deep inspection of one dataset well:

- **Vitessce**: linked spatial, embedding and cell-set views from a JSON view
  config, segmentation layers, 3D.
- **MoBIE** (EMBL): TB-scale multi-modal EM and light microscopy with
  segmentations and tables.
- **napari**: desktop analysis, labels, plugins (Fractal, SpatialData).

What none of them provides is the view Depictio exists for: many runs or samples
at once, driven by a samplesheet, with QC tables, cards and filters that stay
linked across the whole project.

## Decision

Depictio adds a `bioimage` data collection type and a `bioimage_viewer`
advanced_viz kind whose job is to put an image **in the dashboard context**, not
to become an image-analysis application:

- The tile renders a pyramidal image with viv on deck.gl, with the controls a
  reviewer needs at a glance (channels, contrast, z/t, store picker).
- It participates in Depictio's own coordination: an upstream filter picks the
  sample's store, points from a table DC are drawn over the image, and a lasso
  emits a regular `scatter_selection` that tables, cards and analysis groups
  already understand.
- Deep inspection is handed off. Anything beyond that scope (segmentation label
  layers, several linked imaging views, 3D volume rendering, TB-scale EM) is
  left to the dedicated viewers, reached from the tile through a hand-off link
  that passes the store location.

## Why viv inside the tile, and not an embedded Vitessce

- **One coordination model.** Vitessce keeps its own coordination space in its
  view config. Embedding it would duplicate every selection in two stores or
  leave a closed widget inside a dashboard whose point is cross-filtering.
- **One WebGL context per tile.** The kind holds a single `useWebglSlot` and one
  deck.gl context, released when the slot is lost.
- **Bundle.** viv, deck.gl and luma.gl sit in a lazy `vendor-viv` chunk (about
  370 kB gzip), fetched only when a dashboard shows an image tile.
- **Same code in every deployment.** Keys are served by the API from S3 or from
  disk, unchanged in Docker, K8s and the Docker-free `depictio local up` stack,
  and the browser CSP stays at `connect-src 'self'`.

## Consequences

- This PR reads OME-Zarr (NGFF 0.4, zarr v2) uploaded to Depictio's bucket or
  kept on disk. Next: reading stores in place on S3 or allow-listed HTTPS hosts,
  pyramidal OME-TIFF, and the image element of a SpatialData store, all as
  `format` values of the same `bioimage` type.
- Segmentation labels, SpatialData shapes/tables as Depictio tables, coordinate
  transforms and NGFF 0.5+ are tracked as follow-ups.
- A hand-off to Vitessce, MoBIE or napari needs the store to be reachable by
  that tool (public URL, presigned URL or CORS on the API); it is designed with
  the remote-location work, not in this PR.
