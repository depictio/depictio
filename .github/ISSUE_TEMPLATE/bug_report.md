---
name: Bug Report
about: Report a bug or issue with Depictio
title: "[BUG] Brief description of the issue"
labels: bug, needs-triage
assignees: ''

---

## Bug Description

**What happened?**
<!-- A clear description of what the bug is and how it affects your Depictio workflow -->

**What did you expect to happen?**
<!-- A clear description of what you expected to happen instead -->

## Affected Component

**Which Depictio component is affected?**

- [ ] Dashboard creation/editing
- [ ] Data visualization (charts, tables, cards)
- [ ] Interactive components (sliders, filters, dropdowns)
- [ ] Data upload through depictio-cli
- [ ] User authentication/management
- [ ] Data collections joins
- [ ] Dashboard sharing functionality
- [ ] Other: ___________

## Reproduction Steps

<details>
<summary>How to reproduce this issue</summary>

**Steps to reproduce:**

<!-- Provide a step-by-step guide to reproduce the issue
1. Navigate to '...' (e.g., Dashboard Builder, Data Upload, etc.)
2. Upload/select data '...'
3. Create/modify component '...'
4. Configure settings '...'
5. Observe error
-->

**Is this reproducible?**

- [ ] Always
- [ ] Sometimes
- [ ] Rarely
- [ ] Unable to reproduce

**Sample data & Project configuration:**
<!-- Give an example of the data and project configuration that triggers the issue if applicable
- Data file: [attach a sample data file if possible or provide a link]
- Project configuration: [attach or describe relevant project settings] -->

</details>

## Error Details

<details>
<summary>Error messages and logs</summary>

**Error message or unexpected behavior:**

```log
Paste any error messages, stack traces, or unexpected output here
```

**Dash Debug UI or Browser console logs (if frontend issue):**

```log
Paste relevant browser developer tools console output
```

**Server logs (if backend issue):**

```log
Paste relevant backend/API logs if accessible
```

</details>

## Environment Information

<details>
<summary>Deployment and system details</summary>

**Deployment Method and Environment:**

- [ ] Docker Compose: Version : ___________
- [ ] Kubernetes/Helm : Version : ___________
- [ ] Development (local): Version : ___________

**Depictio Version:**

- Version/Tag: [e.g., v0.0.3, latest, edge]
- Commit hash (if applicable): [e.g., abc123def]

**System Information:**

- OS: [e.g. Windows 11, macOS 14.1, Ubuntu 22.04]
- Browser: [e.g. Chrome 120, Firefox 121, Safari 17]

**Depictio Services Status:**

- [ ] Frontend (Dash) accessible on port 5080
- [ ] Backend (FastAPI) accessible on port 8058
- [ ] MongoDB accessible
- [ ] MinIO accessible on port 9000/9001
- [ ] Not sure/Unable to check

</details>

## Data Context

<details>
<summary>Data and workflow information</summary>

**Data Information:**

- Data type: [e.g. CSV, genomic data, time series, etc.]
- Data size: [e.g. 100 rows, 1GB file, etc.]
- Number of columns/features: [if applicable]
- Data source: [e.g. file upload, API, database]

</details>

## Additional Context

<details>
<summary>Screenshots, workarounds, and related issues</summary>

**Screenshots/Videos**
<!-- Add screenshots of the Depictio interface, error dialogs, or screen recordings -->

**Configuration Files**
<!-- Attach or paste relevant configuration snippets:
- Docker Compose configuration
- Kubernetes/Helm values
- Environment variables
- Dashboard JSON exports -->

**Workarounds**
<!-- Have you found any temporary workarounds for this issue? -->

**Related Issues**
<!-- Are there any related issues or discussions? Please link them here -->

**Additional Information**
<!-- Add any other context such as:
- Network connectivity issues
- Resource constraints (CPU, memory)
- Dashboard complexity (number of components) -->

</details>
