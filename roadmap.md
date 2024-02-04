# 2024/02/04 - merge StrandScape architecture and depictio

- Simplify and make Strand-Scape more generic => one platform with run monitoring (workflow agnostic and without control) and dashboarding
  - Run monitoring similar to depictio YAML config (multiple location ...) and MosaiWatcher
  - Standard interface for run monitoring 
  - Provide a way to indicate status (complete, error, to process ...)
    - Agnostic system
  - 
- Communication/synergy between landing page that can point to information at the run level and dashboard page
  - System to do back and forth between dashboard and individual page
- Retrieve information from LabID to feed metadata 


- Final design
  - One space per workflow/project

# Backup

* Pages #TODO
  * Landing page
  * Dataset listing
  * Pivot table + customise file
  * Dashboard
  * Genome browsing
* Ideas
  * Where to set templates?
* Idea = universal pivot table / dataframe aggregation
  * Use case: DADA2 Flora / Ashleys labels
  * Examples: pygwalker
  * Pygwalker:
    * Table: 
      * Ideas: type, quant/ordinal/temporal/nominal, dimension/measure 
    * Vizu: nice but not easily integrable
  * Focus on own plotly solution 
  * Ag grid
  * Requirement: people need to come with standardised format 
  * Second upstream platform to preprocess & reformat tables?
* Idea = genome browser
  * Use case: strand seq
  
* Backend
  * YAML config 
    * Parsing based on CLI/YAML files/pattern provided (no module)
  * Watcher
    * mimetype
    * typing
    * pandas
    * File types
      * Tab based
      * Genome browser based
      * JSON
  * Check what techno/methods are available

* Others to check:
  * Graph 
  * Image 
  

# Draft

## Modules

