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
          links: [
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca5", column_name: "habitat" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca6", column_name: "habitat" },
            { wf_id: "646b0f3c1e4a2d7f8e5b8ca3", dc_id: "646b0f3c1e4a2d7f8e5b8ca9", column_name: "habitat" }
          ]
        }
      ],
      stories: [
        {
          id: "story_sample_first",
          name: "Sample → Community → Differential",
          description: "Start from QC-clean samples, explore community composition, then drill into differentially abundant taxa.",
          icon: "tabler:route",
          color: "blue",
          tab_order: [
            "646b0f3c1e4a2d7f8e5b8ca2",
            "646b0f3c1e4a2d7f8e5b8cb3",
            "646b0f3c1e4a2d7f8e5b8cb4"
          ],
          default_global_filter_ids: [],
          pinned: true
        },
        {
          id: "story_taxon_first",
          name: "Differential → Community → Sample QC",
          description: "Start from differentially abundant taxa, see them in community context, then validate the underlying samples.",
          icon: "tabler:arrows-shuffle",
          color: "violet",
          tab_order: [
            "646b0f3c1e4a2d7f8e5b8cb4",
            "646b0f3c1e4a2d7f8e5b8cb3",
            "646b0f3c1e4a2d7f8e5b8ca2"
          ],
          default_global_filter_ids: [],
          pinned: false
        }
      ]
    }
  }
);
const doc = db.dashboards.findOne(
  { dashboard_id: ObjectId("646b0f3c1e4a2d7f8e5b8ca2") },
  { global_filters: 1, stories: 1, _id: 0 }
);
printjson({ filters: (doc.global_filters || []).length, stories: (doc.stories || []).length });
