# Changelog

Generating changelog from v0.0.5-beta2 to main
## Docker Images


## Changes

### New Features

* fix: allow publishing on workflow dispatch in addition to tags [691e379]
* fix: add package installation and import verification steps in CI workflow [64288fe]
* fix: enhance artifact upload conditions and add dry run for publishing [02fb80c]
* fix: enhance issue templates for bug reports and feature requests [a0fa509]
* fix: add netcat-openbsd to Dockerfile dependencies for improved functionality [ccdf0b6]
* feat: enhance release name generation to ensure DNS compliance [86d5fea]
* feat: consolidate CI workflows by adding test, lint, build, and publish steps for depictio-cli [83abfc6]
* feat: add Docker Buildx setup step in CI workflow [bb90dd9]
* feat: update CI workflows and add initial CLI structure; remove setup.py and adjust pyproject.toml for dependencies [2915d3d]
* feat: update CI workflows and add initial CLI structure; remove setup.py and adjust pyproject.toml for dependencies [185031e]
* refactor: replace add_token function with _add_token for token creation in create_default_token [82e0a94]
* feat: add refresh token support across token management; enhance tests for token creation, validation, and expiration [6a198be]
* feat: enhance token management with refresh token support; update token validity checks and add refresh token endpoint [ae25380]
* feat: improve authentication process by optimizing token validity checks and adding debug logging; add minimal Dash app for testing [479b093]
* feat: update _create_user_in_db to allow optional user ID and group parameters; enhance user existence check [66d6aec]
* feat: enhance token validity checks with detailed logging and add callback for clearing expired tokens [f82641e]
* feat: update _create_user_in_db to accept ObjectId; enhance user creation tests [1790de3]
* feat: enhance initialization process with atomic checks and cleanup; update user creation to include ID [800be10]
* feat: add Flask security assessment scanner for comprehensive application security checks [caa5476]
* feat: add blocking for debug endpoints in Flask server [db8fb6b]
* fix: add missing API packages to the project configuration [13aeaab]
* fix: update Helm chart version and appVersion in Chart.yaml; add step to pull Depictio image in CI workflow [62e6615]
* fix: update Helm chart version and appVersion in Chart.yaml; add step to pull Depictio image in CI workflow [e596fd7]
* feat: add GitHub Actions workflow for testing, linting, and building depictio-cli and clean up pyproject.toml [46503f3]
* fix: add logging step for depictio-backend in deployment workflow [71a6916]
* fix: add visibility to backend and MinIO ports in Gitpod configuration [d091cfc]
* fix: update URL handling logic in ServiceConfig to use internal URL for server context and add debug print statement [e6ff705]
* feat: update environment configuration for Gitpod setup and adjust logging verbosity [6b74b5f]
* feat: update Gitpod setup for zsh and Docker permissions [6b3bc25]
* feat: enhance Gitpod setup with zsh and starship configuration [a1e50c0]
* Add Gitpod workspace setup [e47b0c2]
* feat: enhance Gitpod setup with zsh and starship configuration [8b29d27]
* Add Gitpod workspace setup [e556573]
* feat: enhance Iris integration verification in CI workflow ; add checks for project, deltatable, and dashboard [9a8a6b0]
* fix: update e2e-tests job dependencies to remove unnecessary integration jobs ; add fixture to set DEPICTIO_CONTEXT for test modules [cb64d18]
* feat: rename docker-setup job to docker-system-init and update dependencies in CI workflow ; add fixture to set DEPICTIO_CONTEXT environment variable in test suite (test_scan_utils) [596395e]
* feat: refactor deploy workflow to split CI jobs, enhance logging, and streamline Docker setup and integration tests [1d605c8]
* test: add test suite for File model validation, including various validation scenarios [9957daa]
* feat: add run and standalone commands to CLI, enhance logging, and remove installation test script [0bad484]
* feat: add logging step for depictio-frontend in deployment workflow [223cbcc]
* fix: add missing files for CI [84f84bd]
* feat: enhance S3 configuration handling and logging in storage options conversion [54fec27]
* feat: add backend log retrieval steps to Iris CLI workflow [96a0630]

### Bug Fixes

* fix: update beta release tag pattern and change release action to softprops/action-gh-release [6c4bc50]
* fix: update changelog generation script invocation and change GitHub token reference [8c99139]
* fix: allow publishing on workflow dispatch in addition to tags [691e379]
* fix: update dry run publish condition to include main branch [8026bb0]
* fix: add package installation and import verification steps in CI workflow [64288fe]
* fix: standardize quotes in workflow configuration and update publish conditions [cab8e4b]
* fix: enhance artifact upload conditions and add dry run for publishing [02fb80c]
* fix: update workflow triggers and artifact upload conditions [7e79897]
* fix: update paths for artifact handling in CI workflow [b6bd7d8]
* fix: enhance issue templates for bug reports and feature requests [a0fa509]
* fix: remove direct MinIO connectivity tests from CI workflow [9ffe00d]
* fix: remove obsolete MinIO Console connectivity test from workflow [6ee1d30]
* fix: enhance inter-service connectivity tests with readiness checks and improved error handling [ea147c5]
* fix: add netcat-openbsd to Dockerfile dependencies for improved functionality [ccdf0b6]
* fix: improve database and storage functionality tests in CI workflow [0ef1c93]
* fix: update paths in workflow triggers for Dockerfile and workflow file [f157857]
* fix: update tag pattern in amd64-build.yaml for beta releases [45e6c03]
* fix: update package-dir mapping in pyproject.toml and adjust test-lint workflow [9147327]
* feat: improve authentication process by optimizing token validity checks and adding debug logging; add minimal Dash app for testing [479b093]
* fix: gunicorn single worker issue fix ; some timeout optimisations [16d3a92]
* fix: set DEV_MODE environment variable to false in docker-compose for consistency [9fa61ee]
* fix: enable DEV_MODE environment variable in docker-compose and run_dash script [a987739]
* feat: add blocking for debug endpoints in Flask server [db8fb6b]
* fix: uncomment DEPICTIO_DASH_SERVICE_NAME in backend ConfigMap > should fix screenshots generation due to service name issue [965ca53]
* fix: comment out helm chart version update and git push commands [0b75833]
* fix: log MongoDB URL after its initialization [01b29fa]
* fix: update appVersion and backend/frontend image tags to 0.0.6-beta1 [812cf3c]
* fix: add missing API packages to the project configuration [13aeaab]
* fix: update license format and improve package directory mapping in pyproject.toml [af37c92]
* fix: harmonize CLI YAML file locations [14683c2]
* fix: update public URLs in ConfigMaps and set DEV_MODE to false in values files [b93ee6c]
* fix: update service port variables and improve initContainers in Helm charts [959ee2e]
* fix: comment out initContainers for MongoDB, MinIO, and backend in deployments.yaml [b310ed0]
* fix: update MongoDB connection logic and improve MinIO configuration in Helm charts [dce087f]
* fix: reduce storage sizes for MongoDB, MinIO, screenshots, and keys in Helm chart [cd1de3f]
* fix: update Helm chart version and clean up ingress annotations for better functionality [7e0180b]
* fix: simplify CI workflow by removing redundant build strategy and enhancing image handling [7fd96fb]
* fix: refactor CI workflow to streamline Helm chart deployment and Docker image handling [e8f1bbf]
* fix: update default host configurations with correct service names for frontend and backend [48e8fd6]
* fix: update CI workflow to build Docker image instead of pulling it [40bbded]
* fix: update Helm chart version and appVersion in Chart.yaml; add step to pull Depictio image in CI workflow [62e6615]
* fix: comment out Docker image build step in CI workflow [78ca7bd]
* fix: update service names in ingress configuration for frontend and backend [770d8e5]
* fix: enhance ingress configuration with default annotations and timeout settings [4d75fb1]
* fix: update ingress host for API documentation testing [2c5d673]
* fix: reduce storage sizes for MongoDB, MinIO, screenshots, and keys in Helm chart [8a5725f]
* fix: update Helm chart version and clean up ingress annotations for better functionality [4f3a50c]
* fix: simplify CI workflow by removing redundant build strategy and enhancing image handling [a112150]
* fix: refactor CI workflow to streamline Helm chart deployment and Docker image handling [af50891]
* fix: update default host configurations with correct service names for frontend and backend [ce1a6eb]
* fix: update CI workflow to build Docker image instead of pulling it [4d58614]
* fix: update Helm chart version and appVersion in Chart.yaml; add step to pull Depictio image in CI workflow [e596fd7]
* fix: comment out Docker image build step in CI workflow [3b65efe]
* fix: update service names in ingress configuration for frontend and backend [acee3d3]
* fix: enhance ingress configuration with default annotations and timeout settings [59b9f92]
* fix: update ingress host for API documentation testing [d856c8a]
* fix: refine package inclusion pattern in pyproject.toml for improved module discovery [e9d4ff8]
* fix: update package inclusion pattern in pyproject.toml for broader API coverage [65e3fed]
* fix: update run command documentation and remove unused status command [b3d6a8a]
* fix: adjust column spans and wrapping in design_header for responsive layout [85bd2c5]
* fix: update .env.example with MinIO credentials and adjust docker-compose for script paths and DEV_MODE variable [3feb886]
* fix: add logging step for depictio-backend in deployment workflow [71a6916]
* fix: add visibility to backend and MinIO ports in Gitpod configuration [d091cfc]
* fix: uncomment .env file copy command in deployment workflow to ensure environment variables are set correctly [fd2849d]
* fix: update URL handling logic in ServiceConfig to use internal URL for server context and add debug print statement [e6ff705]
* fix: comment out .env file copy command in deployment workflow to prevent overwriting [55a273f]
* fix: clean up Gitpod environment script by removing hardcoded URL and adjusting formatting [f206a10]
* fix: update service configuration to include external_service flag and adjust URL handling logic ; solve scenario where public url needs to be defined when using internal service (e.g: gitpod) [4aac1bd]
* fix: correct version format in bumpversion configuration and update push command in bump script [815214a]
* fix: update Iris integration verification in CI workflow to reflect project name change [f89f2b5]
* fix: update e2e-tests job dependencies to remove docker-system-init requirement [de58bbb]
* fix: update e2e-tests job dependencies to remove unnecessary integration jobs ; add fixture to set DEPICTIO_CONTEXT for test modules [cb64d18]
* fix: update e2e-tests job dependencies to include docker-system-init ; refactor test fixture for DEPICTIO_CONTEXT environment variable [2c5ac43]
* feat: rename docker-setup job to docker-system-init and update dependencies in CI workflow ; add fixture to set DEPICTIO_CONTEXT environment variable in test suite (test_scan_utils) [596395e]
* fix: add missing files for CI [84f84bd]
* fix: remove unnecessary blank line in deploy workflow [9542c00]

### Improvements

* fix: update beta release tag pattern and change release action to softprops/action-gh-release [6c4bc50]
* fix: update changelog generation script invocation and change GitHub token reference [8c99139]
* fix: update dry run publish condition to include main branch [8026bb0]
* fix: standardize quotes in workflow configuration and update publish conditions [cab8e4b]
* fix: enhance artifact upload conditions and add dry run for publishing [02fb80c]
* fix: update workflow triggers and artifact upload conditions [7e79897]
* fix: update paths for artifact handling in CI workflow [b6bd7d8]
* Update CHANGELOG.md for v0.0.6 [62ac118]
* fix: enhance issue templates for bug reports and feature requests [a0fa509]
* fix: enhance inter-service connectivity tests with readiness checks and improved error handling [ea147c5]
* fix: add netcat-openbsd to Dockerfile dependencies for improved functionality [ccdf0b6]
* fix: improve database and storage functionality tests in CI workflow [0ef1c93]
* feat: enhance release name generation to ensure DNS compliance [86d5fea]
* fix: update paths in workflow triggers for Dockerfile and workflow file [f157857]
* chore: CI cleaning, helm CI refactoring and extension [636d839]
* fix: update tag pattern in amd64-build.yaml for beta releases [45e6c03]
* fix: update package-dir mapping in pyproject.toml and adjust test-lint workflow [9147327]
* feat: update CI workflows and add initial CLI structure; remove setup.py and adjust pyproject.toml for dependencies [2915d3d]
* feat: update CI workflows and add initial CLI structure; remove setup.py and adjust pyproject.toml for dependencies [185031e]
* refactor: replace add_token function with _add_token for token creation in create_default_token [82e0a94]
* feat: add refresh token support across token management; enhance tests for token creation, validation, and expiration [6a198be]
* feat: enhance token management with refresh token support; update token validity checks and add refresh token endpoint [ae25380]
* feat: improve authentication process by optimizing token validity checks and adding debug logging; add minimal Dash app for testing [479b093]
* refactor: simplify token validity tests by removing logger patching [ed4d3c0]
* feat: update _create_user_in_db to allow optional user ID and group parameters; enhance user existence check [66d6aec]
* feat: enhance token validity checks with detailed logging and add callback for clearing expired tokens [f82641e]
* feat: update _create_user_in_db to accept ObjectId; enhance user creation tests [1790de3]
* feat: enhance initialization process with atomic checks and cleanup; update user creation to include ID [800be10]
* chore: update screenshot functionality to use 'domcontentloaded' for page navigation [6e6c945]
* Update CHANGELOG.md for v0.0.6-beta3 [7ea90b1]
* refactor: clean up app.py and enhance run scripts for development mode [2e0d789]
* Update CHANGELOG.md for v0.0.6-beta2 [8ac43f7]
* fix: comment out helm chart version update and git push commands [0b75833]
* refactor: remove commented-out code and clean up MongoDB initialization [070ae10]
* fix: update appVersion and backend/frontend image tags to 0.0.6-beta1 [812cf3c]
* fix: update license format and improve package directory mapping in pyproject.toml [af37c92]
* Update CHANGELOG.md for v0.0.6-beta1 [196086a]
* fix: update public URLs in ConfigMaps and set DEV_MODE to false in values files [b93ee6c]
* fix: update service port variables and improve initContainers in Helm charts [959ee2e]
* fix: update MongoDB connection logic and improve MinIO configuration in Helm charts [dce087f]
* fix: update Helm chart version and clean up ingress annotations for better functionality [7e0180b]
* fix: refactor CI workflow to streamline Helm chart deployment and Docker image handling [e8f1bbf]
* fix: update default host configurations with correct service names for frontend and backend [48e8fd6]
* fix: update CI workflow to build Docker image instead of pulling it [40bbded]
* fix: update Helm chart version and appVersion in Chart.yaml; add step to pull Depictio image in CI workflow [62e6615]
* fix: update service names in ingress configuration for frontend and backend [770d8e5]
* fix: enhance ingress configuration with default annotations and timeout settings [4d75fb1]
* fix: update ingress host for API documentation testing [2c5d673]
* chore(ci): enhance ingress connectivity checks [3bbbe18]
* Revert values updates and adjust ingress [8c2c7d2]
* fix: update Helm chart version and clean up ingress annotations for better functionality [4f3a50c]
* fix: refactor CI workflow to streamline Helm chart deployment and Docker image handling [af50891]
* fix: update default host configurations with correct service names for frontend and backend [ce1a6eb]
* fix: update CI workflow to build Docker image instead of pulling it [4d58614]
* fix: update Helm chart version and appVersion in Chart.yaml; add step to pull Depictio image in CI workflow [e596fd7]
* fix: update service names in ingress configuration for frontend and backend [acee3d3]
* fix: enhance ingress configuration with default annotations and timeout settings [59b9f92]
* fix: update ingress host for API documentation testing [d856c8a]
* chore(ci): enhance ingress connectivity checks [d00b14d]
* fix: refine package inclusion pattern in pyproject.toml for improved module discovery [e9d4ff8]
* fix: update package inclusion pattern in pyproject.toml for broader API coverage [65e3fed]
* refactor: update GitHub Actions workflow for testing and linting, streamline steps and dependencies [64d7c83]
* Revert values updates and adjust ingress [cd793a7]
* refactor: update publish workflow and dependencies in pyproject.toml [300b4a3]
* Improve CLI build for Poetry [569c89d]
* fix: update run command documentation and remove unused status command [b3d6a8a]
* fix: update .env.example with MinIO credentials and adjust docker-compose for script paths and DEV_MODE variable [3feb886]
* fix: update URL handling logic in ServiceConfig to use internal URL for server context and add debug print statement [e6ff705]
* fix: update service configuration to include external_service flag and adjust URL handling logic ; solve scenario where public url needs to be defined when using internal service (e.g: gitpod) [4aac1bd]
* feat: update environment configuration for Gitpod setup and adjust logging verbosity [6b74b5f]
* feat: update Gitpod setup for zsh and Docker permissions [6b3bc25]
* feat: enhance Gitpod setup with zsh and starship configuration [a1e50c0]
* feat: enhance Gitpod setup with zsh and starship configuration [8b29d27]
* Update CHANGELOG.md for v0.0.5 [ddf5db8]
* fix: correct version format in bumpversion configuration and update push command in bump script [815214a]
* fix: update Iris integration verification in CI workflow to reflect project name change [f89f2b5]
* feat: enhance Iris integration verification in CI workflow ; add checks for project, deltatable, and dashboard [9a8a6b0]
* fix: update e2e-tests job dependencies to remove docker-system-init requirement [de58bbb]
* fix: update e2e-tests job dependencies to remove unnecessary integration jobs ; add fixture to set DEPICTIO_CONTEXT for test modules [cb64d18]
* fix: update e2e-tests job dependencies to include docker-system-init ; refactor test fixture for DEPICTIO_CONTEXT environment variable [2c5ac43]
* feat: rename docker-setup job to docker-system-init and update dependencies in CI workflow ; add fixture to set DEPICTIO_CONTEXT environment variable in test suite (test_scan_utils) [596395e]
* feat: refactor deploy workflow to split CI jobs, enhance logging, and streamline Docker setup and integration tests [1d605c8]
* chore: refactor scan/processing to improve logging, implement run fonction to have a full execution of the steps [c3335e4]
* feat: add run and standalone commands to CLI, enhance logging, and remove installation test script [0bad484]
* refactor: update workflow steps and improve S3 configuration handling in tests [3e50e0a]
* refactor: streamline S3 configuration handling [af316de]
* feat: enhance S3 configuration handling and logging in storage options conversion [54fec27]
* Update CHANGELOG.md for v0.0.5-beta2 [23744a6]

### Other Changes

* Bump version: 0.0.6-b4 → 0.0.6 [9798a3f]
* chore: remove obsolete CI workflows for testing, linting, and building depictio-cli [4554169]
* Bump version: 0.0.6-beta3 → 0.0.6-b4 [d6dbb20]
* Bump version: 0.0.6-beta2 → 0.0.6-beta3 [e846f37]
* Bump version: 0.0.6-beta1 → 0.0.6-beta2 [49c1720]
* Bump version: 0.0.5 → 0.0.6-beta1 [5009a56]
* Use minikube IP for ingress checks [5f45a0f]
* test: check FastAPI docs endpoint [a337cc6]
* Switch to host-based ingress [5be94a3]
* Use minikube IP for ingress checks [72aed78]
* test: check FastAPI docs endpoint [309427b]
* chore: remove conditional setup call in setup.py and clean up README.md [0ac74b5]
* Bump version: 0.0.5-beta2 → 0.0.5 [6c68f48]
* Bump version: v0.0.5-beta2 → v0.0.5 [12e9741]
* Switch to host-based ingress [c674751]


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

# Changelog

Generating changelog from v0.0.5-beta2 to v0.0.6
## Docker Images


## Changes


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

# Changelog

Generating changelog from v0.0.5-beta2 to v0.0.6-beta3
## Docker Images


## Changes


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

# Changelog

Generating changelog from v0.0.5-beta2 to v0.0.6-beta2
## Docker Images


## Changes


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

# Changelog

Generating changelog from v0.0.5-beta2 to v0.0.6-beta1
## Docker Images


## Changes


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

# Changelog

Generating changelog from v0.0.5-beta2 to v0.0.5
## Docker Images


## Changes


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

# Changelog

Generating changelog from v0.0.4 to v0.0.5-beta2
## Docker Images


## Changes


## Documentation
Full documentation: https://depictio.github.io/depictio-docs/

ecessary dependency on build-image in create-release job
* fix: update tag patterns for Docker workflows in release and build configurations

### Improvements

* fix: update workflow triggers and improve changelog handling in release process
* fix: update tag patterns for Docker workflows in release and build configurations

# Changelog
