# Update Docs

Comprehensive documentation update workflow for both public documentation (depictio-docs) and internal technical notes (Obsidian via MCP).

## Usage

After completing a PR with significant changes, update both public and internal documentation.

## Documentation Targets

### 1. Public Documentation (depictio-docs)

**Location**: depictio-docs repository (separate repo in VS Code workspace)

**Content**:
- User-facing documentation
- Installation guides
- API reference
- Configuration examples
- Tutorials and how-tos
- Changelog

**Access**: Direct file editing in the depictio-docs repository

### 2. Internal Documentation (Obsidian Notes)

**Location**: Obsidian vault accessible via MCP integration

**Content**:
- Technical implementation details
- Architecture decisions and trade-offs
- Internal APIs and developer patterns
- Performance considerations
- Debugging strategies
- Database schema notes
- Security implementation details
- Testing strategies
- Future refactoring opportunities
- Technical debt tracking

**Access**: MCP tools (`mcp__mcp-obsidian__*`)

## Process

### Phase 1: Assess Documentation Needs

1. **Review changes in PR**:
   - What features were added?
   - What APIs changed?
   - What configuration options are new?
   - What breaking changes occurred?

2. **Determine documentation scope**:
   - Public docs: User-facing changes
   - Internal docs: Technical implementation details
   - Both: Major architectural changes

### Phase 2: Update Public Documentation

1. **Check current documentation**:
   - Navigate to depictio-docs workspace
   - Find relevant documentation files
   - Review existing content

2. **Update user-facing docs**:
   - Installation guides (if dependencies changed)
   - Configuration docs (if new options added)
   - API reference (if endpoints changed)
   - Tutorials (if workflows changed)
   - CHANGELOG.md (version history)

3. **Add examples**:
   - Code snippets
   - Configuration examples
   - Usage patterns
   - Integration guides

4. **Review and commit**:
   - Check for clarity and completeness
   - Verify links and references
   - Commit to depictio-docs repo
   - Push to remote

### Phase 3: Update Internal Documentation (Obsidian)

1. **Access Obsidian vault via MCP**:
   ```
   Use MCP tools to read/write Obsidian notes
   ```

2. **Identify relevant notes**:
   - Search existing notes related to changes
   - Create new notes if needed
   - Link to related documentation

3. **Document technical details**:
   - Implementation specifics
   - Architecture decisions (why this approach?)
   - Performance benchmarks
   - Edge cases and gotchas
   - Integration challenges
   - Monitoring and observability
   - Development environment quirks

4. **Update interconnected notes**:
   - Link to related technical notes
   - Update index/overview notes
   - Add to relevant categories

## Documentation Templates

### Public Docs Template

For new features in depictio-docs:

```markdown
# Feature Name

Brief description of what this feature does.

## Overview

Detailed explanation of the feature and its purpose.

## Installation

Any additional installation steps required.

## Configuration

Configuration options and examples:

\`\`\`yaml
# Example configuration
feature:
  option1: value1
  option2: value2
\`\`\`

## Usage

How to use this feature:

\`\`\`python
# Example code
from depictio import Feature
feature = Feature(option1="value")
\`\`\`

## Examples

Complete examples showing common use cases.

## API Reference

Detailed API documentation if applicable.

## Troubleshooting

Common issues and solutions.
```

### Internal Docs Template (Obsidian)

For technical notes:

```markdown
# Feature Name - Technical Details

## Overview
- Implementation approach
- Related PRs: #123, #456
- Related files: `path/to/file.py`

## Architecture Decisions
- Why this approach vs alternatives
- Trade-offs considered
- Performance implications

## Implementation Details
- Key components
- Data flow
- Integration points
- Edge cases handled

## Performance Notes
- Benchmarks
- Optimization opportunities
- Resource usage

## Security Considerations
- Authentication/authorization
- Data validation
- Security boundaries

## Testing Strategy
- Unit test coverage
- Integration tests
- E2E test scenarios
- Coverage gaps

## Known Issues
- Edge cases to watch
- Technical debt
- Future improvements

## Monitoring
- Metrics to track
- Logging strategy
- Debugging approaches

## Related Notes
- [[Related Note 1]]
- [[Related Note 2]]

## Tags
#feature #architecture #api #performance
```

## Using MCP Tools for Obsidian

### List Files in Obsidian Vault

```
Use: mcp__mcp-obsidian__obsidian_list_files_in_vault
```

### Search Obsidian Notes

```
Use: mcp__mcp-obsidian__obsidian_simple_search
Parameters: query="search term"
```

### Read Obsidian Note

```
Use: mcp__mcp-obsidian__obsidian_get_file_contents
Parameters: filepath="path/to/note.md"
```

### Update Obsidian Note

```
Use: mcp__mcp-obsidian__obsidian_append_content
Parameters:
  filepath="path/to/note.md"
  content="new content to append"
```

### Create New Obsidian Note

```
Use: mcp__mcp-obsidian__obsidian_append_content
Parameters:
  filepath="path/to/new-note.md"
  content="# Note Title\n\nContent..."
```

## Documentation Workflow Examples

### New Feature Documentation

1. **Public docs** (depictio-docs):
   - Add feature page in `docs/features/`
   - Update main README if major feature
   - Add to navigation/index
   - Update CHANGELOG

2. **Internal docs** (Obsidian):
   - Create technical note in `Features/` folder
   - Document architecture decisions
   - Add performance notes
   - Link to related implementation notes

### API Change Documentation

1. **Public docs**:
   - Update API reference
   - Update examples using the API
   - Add migration guide if breaking change
   - Update CHANGELOG with breaking changes

2. **Internal docs**:
   - Document why API changed
   - Note backward compatibility considerations
   - Add performance implications
   - Update integration notes

### Configuration Change Documentation

1. **Public docs**:
   - Update configuration reference
   - Add configuration examples
   - Document default values
   - Update environment variable docs

2. **Internal docs**:
   - Document configuration validation
   - Note configuration dependencies
   - Add security considerations
   - Document configuration migration

## Documentation Quality Checklist

### Public Documentation
- [ ] Clear and concise explanations
- [ ] Working code examples
- [ ] Proper formatting and structure
- [ ] Links to related documentation
- [ ] Screenshots/diagrams if helpful
- [ ] Updated CHANGELOG
- [ ] Version compatibility notes

### Internal Documentation
- [ ] Technical accuracy
- [ ] Architecture context
- [ ] Implementation rationale
- [ ] Performance considerations
- [ ] Security notes
- [ ] Testing coverage
- [ ] Known limitations
- [ ] Links to related notes
- [ ] Proper tags for discoverability

## Integration with Other Skills

- Use after `/create-pr` for significant changes
- Update docs before `/bump-version` for releases
- Cross-reference with `/release-workflow` documentation
- Coordinate with `/db-operations` for data model changes

## Best Practices

1. **Update docs concurrently with code**: Don't defer documentation
2. **Be specific**: Include concrete examples and use cases
3. **Think about the audience**:
   - Public docs: End users and integrators
   - Internal docs: Developers and maintainers
4. **Keep it current**: Remove outdated information
5. **Link extensively**: Connect related documentation
6. **Use proper formatting**: Make docs scannable and readable
7. **Include troubleshooting**: Document common issues
8. **Version documentation**: Note which version features appeared in

## Documentation Review Process

Before finalizing documentation:

1. **Self-review**:
   - Read as if you're a new user/developer
   - Check all examples work
   - Verify all links are valid

2. **Technical review**:
   - Ensure technical accuracy
   - Verify implementation details
   - Check architecture descriptions

3. **User perspective**:
   - Is it clear and understandable?
   - Are there gaps in explanation?
   - Do examples cover common use cases?

## Quick Reference

**Update public docs**:
- Navigate to depictio-docs repo
- Edit relevant markdown files
- Add examples and screenshots
- Commit and push

**Update Obsidian notes**:
- Use MCP search to find relevant notes
- Read existing content
- Append/update technical details
- Create new notes for new topics
- Link related notes together
