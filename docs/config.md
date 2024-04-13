# MosaiCatcher Pipeline Configuration Documentation

## General Overview
This document guides users on customizing the YAML configuration for the MosaiCatcher pipeline, detailing workflows and data collections.

## Contents
- [Version Specification](#version-specification)
- [Defining Workflows](#defining-workflows)
  - [Workflow Engine](#workflow-engine)
  - [Workflow Details](#workflow-details)
  - [Workflow Data Configuration](#workflow-data-configuration)
- [Data Collections](#data-collections)
  - [Table Type Collections](#table-type-collections)
  - [JBrowse2 Type Collections](#jbrowse2-type-collections)

## Version Specification
- `depictio_version`: "0.1.0"

## Defining Workflows
### Workflow Engine
- `engine`: Workflow engine used (e.g., "snakemake").

### Workflow Details
- `name`: Name of the workflow.
- `description`: Description of the workflow.
- `repository_url`: URL of the workflow repository.

### Workflow Data Configuration
- `config`:
  - `parent_runs_location`: Location of runs.
  - `runs_regex`: Regex to match runs.

## Data Collections
### Table Type Collections
- `data_collection_tag`: Identifier for the data collection.
- `config`:
  - `type`: "Table"
  - `regex`: Pattern for matching files.

### JBrowse2 Type Collections
- `data_collection_tag`: Identifier for the data collection.
- `config`:
  - `type`: "JBrowse2"
  - `regex`: Pattern for matching files, including wildcards.

### Joining Data Collections
- `join`:
  - `on_columns`: Columns for joining.
  - `how`: Type of join (e.g., "inner").
  - `with_dc`: Data collections to join.

