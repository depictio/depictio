// Mongosh patch script — sync the ampliseq parent dashboard's
// global_filters and journeys to the latest pin-based funnel schema for
// deployments that won't be wiped + reseeded from JSON.
//
// Run from the host (port 27101 maps to the dev compose's depictio mongo):
//   mongosh --quiet --port 27101 depictioDB dev/cross-tab-filtering/patch_ampliseq_globals.js
//
// Idempotent. Also $unsets legacy fields from prior iterations.

db.dashboards.updateOne(
  { dashboard_id: ObjectId("646b0f3c1e4a2d7f8e5b8ca2") },
  {
    $set: {
      global_filters: [
        {
          id: "gf_sample_id",
          label: "Sample ID",
          source_component_index: "multiqc-sample-filter",
          source_tab_id: "646b0f3c1e4a2d7f8e5b8ca2",
          interactive_component_type: "MultiSelect",
          column_type: "object",
          default_state: null,
          display: {
            title: "Sample ID",
            custom_color: "#45B8AC",
            icon_name: "mdi:flask",
            title_size: "md"
          },
          links: [
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca5", column_name: "sample" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca6", column_name: "sample" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca7", column_name: "sample" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca9", column_name: "sample" }
          ]
        },
        {
          id: "gf_habitat",
          label: "Habitat",
          source_component_index: "multiqc-habitat-filter",
          source_tab_id: "646b0f3c1e4a2d7f8e5b8ca2",
          interactive_component_type: "MultiSelect",
          column_type: "object",
          default_state: null,
          display: {
            title: "Habitat Type",
            custom_color: "#984EA3",
            icon_name: "mdi:earth",
            title_size: "md"
          },
          links: [
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca5", column_name: "habitat" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca6", column_name: "habitat" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca9", column_name: "habitat" }
          ]
        }
      ],
      journeys: []
    },
    // Strip legacy fields written by prior iterations on this branch:
    //   stories                   — pre-Journey rename
    //   journeys.*.stops          — pre-pin-based-funnel snapshot model
    //   last_active_journey_stop  — per-stop resume bookkeeping
    $unset: { stories: "" }
  }
);

// Clean legacy per-user state fields on the user_dashboard_state docs that
// pointed at this dashboard. Inert with the new model, but kept tidy.
db.user_dashboard_state.updateMany(
  { parent_dashboard_id: ObjectId("646b0f3c1e4a2d7f8e5b8ca2") },
  { $unset: { last_active_journey_stop_id: "", journey_stops: "" } }
);

const doc = db.dashboards.findOne(
  { dashboard_id: ObjectId("646b0f3c1e4a2d7f8e5b8ca2") },
  { global_filters: 1, journeys: 1, _id: 0 }
);
printjson({
  filters: (doc.global_filters || []).length,
  journeys: (doc.journeys || []).length,
  steps_per_journey: (doc.journeys || []).map((j) => (j.steps || []).length)
});
