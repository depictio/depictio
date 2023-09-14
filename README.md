# Depictio

Depictio is a web platform oriented towards workflow downstream analysis for large scale studies and core facilities. Depictio is open-source and relies itself on open-source technologies, used into its different components: 
* A multiuser frontend with an authentication system: Plotly Dash ; flask-auth
* An asynchronous high-performance backend: FastAPI
* A noSQL database: mongoDB 
* A cache system: redis cache
  

## Get Started

### Steps

* Frontend
  * Create a user and get a token/key
* Backend
  * Design your configuration file # TODO: define YAML schema and doc
  * Register a workflow and its data collections using the token/key
* Frontend
  * Design your dashboard
