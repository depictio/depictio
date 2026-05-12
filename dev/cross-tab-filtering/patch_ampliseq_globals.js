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
      journeys: [
        {
          id: "journey_riverwater",
          name: "Riverwater funnel",
          description: "Single-tab funnel on the MultiQC tab — narrow from all samples down to two specific Riverwater samples.",
          icon: "tabler:droplet",
          color: "blue",
          pinned: true,
          stops: [
            {
              id: "stop_river_all",
              name: "All samples",
              anchor_tab_id: "646b0f3c1e4a2d7f8e5b8ca2",
              global_filter_state: {},
              local_filter_state: []
            },
            {
              id: "stop_river_only",
              name: "Riverwater only",
              anchor_tab_id: "646b0f3c1e4a2d7f8e5b8ca2",
              global_filter_state: { gf_habitat: ["Riverwater"] },
              local_filter_state: []
            },
            {
              id: "stop_river_two",
              name: "Two specific samples",
              anchor_tab_id: "646b0f3c1e4a2d7f8e5b8ca2",
              global_filter_state: {
                gf_habitat: ["Riverwater"],
                gf_sample_id: ["SRR10070130", "SRR10070131"]
              },
              local_filter_state: []
            }
          ]
        },
        {
          id: "journey_soil_drilldown",
          name: "Habitat → taxa drill-down",
          description: "Multi-tab journey: scope to Soil samples in QC, see their community composition, then drill into differentially abundant taxa.",
          icon: "tabler:route",
          color: "violet",
          pinned: false,
          stops: [
            {
              id: "stop_soil_qc",
              name: "QC: Soil samples",
              anchor_tab_id: "646b0f3c1e4a2d7f8e5b8ca2",
              global_filter_state: { gf_habitat: ["Soil"] },
              local_filter_state: []
            },
            {
              id: "stop_soil_community",
              name: "Community: Soil diversity",
              anchor_tab_id: "646b0f3c1e4a2d7f8e5b8cb3",
              global_filter_state: { gf_habitat: ["Soil"] },
              local_filter_state: []
            },
            {
              id: "stop_soil_differential",
              name: "Differential: Soil taxa",
              anchor_tab_id: "646b0f3c1e4a2d7f8e5b8cb4",
              global_filter_state: { gf_habitat: ["Soil"] },
              local_filter_state: []
            }
          ]
        }
      ]
    },
    // Strip the legacy `stories` field if it was written by a previous run.
    $unset: { stories: "" }
  }
);
const doc = db.dashboards.findOne(
  { dashboard_id: ObjectId("646b0f3c1e4a2d7f8e5b8ca2") },
  { global_filters: 1, journeys: 1, _id: 0 }
);
printjson({ filters: (doc.global_filters || []).length, journeys: (doc.journeys || []).length });
