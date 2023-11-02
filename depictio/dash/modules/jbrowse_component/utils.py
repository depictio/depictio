my_assembly = {
    "name": "GRCh38",
    "sequence": {
        "type": "ReferenceSequenceTrack",
        "trackId": "GRCh38-ReferenceSequenceTrack",
        "adapter": {
            "type": "BgzipFastaAdapter",
            "fastaLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz",
            },
            "faiLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz.fai",
            },
            "gziLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz.gzi",
            },
        },
    },
    "aliases": ["hg38"],
    "refNameAliases": {
        "adapter": {
            "type": "RefNameAliasAdapter",
            "location": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/hg38_aliases.txt",
            },
        },
    },
}

# my_aggregate_text_search_adapters = [
#     {
#         "type": "TrixTextSearchAdapter",
#         "textSearchAdapterId": "hg38-index",
#         "ixFilePath": {
#             "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/hg38.ix"
#         },
#         "ixxFilePath": {
#             "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/hg38.ixx"
#         },
#         "metaFilePath": {
#             "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/trix/meta.json"
#         },
#         "assemblyNames": ["GRCh38"],
#     }
# ]
my_location = "17:79900000..80000000"
# # my_location = {"refName": "10", "start": 1, "end": 800}

# my_theme = {
#     "theme": {
#         "palette": {
#             "primary": {
#                 "main": "#311b92",
#             },
#             "secondary": {
#                 "main": "#0097a7",
#             },
#             "tertiary": {
#                 "main": "#f57c00",
#             },
#             "quaternary": {
#                 "main": "#d50000",
#             },
#             "bases": {
#                 "A": {"main": "#98FB98"},
#                 "C": {"main": "#87CEEB"},
#                 "G": {"main": "#DAA520"},
#                 "T": {"main": "#DC143C"},
#             },
#         },
#     },
# }

# my_tracks = [
#     {
#             "type": "MultiQuantitativeTrack",
#             "configuration": "multiwiggle_{cell}-sessionTrack".format(cell=e),
#             "displays": [
#                 {
#                     "id": "lTY7_5KzL5",
#                     "type": "MultiLinearWiggleDisplay",
#                     "height": 70,
#                     "selectedRendering": "",
#                     "rendererTypeNameState": "xyplot",
#                     "autoscale": "global",
#                     "displayCrossHatches": True,
#                     "layout": [
#                         {
#                             "name": "Watson",
#                             "type": "BigWigAdapter",
#                             "bigWigLocation": {
#                                 "uri": f"http://localhost:8090/assets/Counts_BW/{r}/{e}-W.bigWig",
#                             },
#                             "color": "rgb(244, 164, 96)",
#                         },
#                         {
#                             "name": "Crick",
#                             "type": "BigWigAdapter",
#                             "bigWigLocation": {
#                                 "uri": f"http://localhost:8090/assets/Counts_BW/{r}/{e}-C.bigWig",
#                             },
#                             "color": "rgb(102, 139, 139)",
#                         },
#                     ],
#                 },
#             ],
#         } for e, r in zip(["BM510x04_PE20301"], ["Run_X"])
# ]

my_tracks = [
    {
        "type": "FeatureTrack",
        "trackId": "ncbi_refseq_109_hg38",
        "name": "NCBI RefSeq (GFF3Tabix)",
        "assemblyNames": ["GRCh38"],
        "category": ["Annotation"],
        "adapter": {
            "type": "Gff3TabixAdapter",
            "gffGzLocation": {
                "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz"
            },
            "index": {
                "location": {
                    "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/ncbi_refseq/GCA_000001405.15_GRCh38_full_analysis_set.refseq_annotation.sorted.gff.gz.tbi"
                }
            },
        },
    }
]


# app.layout =
