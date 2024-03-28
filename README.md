# Depictio

## Project Overview

Depictio is an innovative web-based platform currently under development, aimed at facilitating downstream analysis in bioinformatics. It provides a dynamic and interactive dashboard experience for quality control (QC) metrics monitoring and result exploration in omics. The platform is tailored towards large-scale studies and research facilities, offering support for various data formats and interactive data visualization tools.

## Features

* Dynamic Dashboards: Real-time data interaction, customizable views, and user-driven exploration features.
* Diverse Data Format Support: Handles standard formats like CSV, TSV, XLSX, Parquet, and omics files like BED, BigBed, BigWig, BAM/CRAM, VCF.
* Robust Backend Technologies: Utilizes FastAPI, MongoDB, and Redis cache for high-performance data management and processing.
* Intuitive Frontend: Built on Plotly Dash, a ReactJS-based framework

## Current Status

Depictio is currently in the development phase and is not yet available for general use. The platform is being built with an emphasis on versatility and adaptability to various biological research needs.

## Architecture

![Depictio architecture](./docs/images/main.png "Depictio architecture")

Depictio architecture is currently composed of two main aspects: a microservices architecture (to be executed into a docker-compose and late on in a kubernetes cluster) and a CLI client to be installed locally on-premise where the data to be scanned is located. 
There are currently 6 main microservices running:
- 1. FastAPI instance
- 2. mongoDB database
- 3. redis cache system
- 4. JBrowse on-premise genome browser
- 5. MinIO S3 bucket management instance
- 6. Plotly Dash server


## Installation

Depictio microservices architecture aims to be deployed on a Kubernetes instance. Before transitioning to kubernetes, the current reproduces a similar setup using a docker-compose layer that encapsulates the different services that will be deployed on K8S. A Command Line Interface (CLI) was developed to interact with the API running on K8S in order to register workflows and data collections, scan files, aggregate data over time and so on. 

### Docker


Clone the repo:

```
git clone https://github.com/weber8thomas/depictio.git
```


```
docker-compose up -d
```



### Kubernetes

Ongoing 




## Depictio data YAML config setup

#TODO: YAML schema 

## Get started

- Prepare data
- Prepare YAML
- CLI commands


## Modularity

## General design

![alt text](docs/images/schema.png)


### API

### Frontend components

## Jbrowse config 

## Validation and models


## Others


- config_backend.yaml


## Biological Use-Cases

Depictio is currently being developed with two primary workflows employed as use-cases :

* Single-cell Structural Variations from Strand-seq data: Focus on cancer subclonal characterisation and genome phasing.
* Diatom Interactions and Climate Change Studies: Analysis of diatom symbioses in marine biology, in collaboration with the Vincent group and TREC.

## Contributing

While Depictio is not yet operational, we welcome ideas, suggestions, and feedback from the community. If you have insights or want to contribute to the project, please feel free to open an issue or submit a pull request.


