# DB Operations

Database operations using the Depictio CLI backup commands for MongoDB management.

## Usage

When the user needs database operations (backup, restore, list backups, validate), use the Depictio CLI wrapper.

## CLI Access

The Depictio CLI is accessed via:
```bash
/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio-venv-dash-v3/bin/python -c "from depictio.cli.depictio_cli import app; app()" backup COMMAND
```

Or create an alias for convenience:
```bash
alias depictio-cli="/Users/tweber/Gits/workspaces/depictio-workspace/depictio/depictio-venv-dash-v3/bin/python -c 'from depictio.cli.depictio_cli import app; app()'"
```

## Available Database Commands

### 1. Create Backup

Create a backup of the Depictio database.

```bash
depictio-cli backup create
```

**What it does**:
- Exports all MongoDB collections
- Saves backup with timestamp
- Validates data against Pydantic models
- Stores backup file on server

**Options**:
- Use `--verbose` for detailed output
- Backup includes: users, groups, projects, workflows, data_collections

### 2. List Backups

List all available backup files on the server.

```bash
depictio-cli backup list
```

**Output**:
- Backup file names
- Creation timestamps
- File sizes
- Location paths

### 3. Validate Backup

Validate a backup file against Pydantic models to ensure data integrity.

```bash
depictio-cli backup validate --backup-file FILENAME
```

**What it does**:
- Loads backup file
- Validates each collection against models
- Reports validation errors
- Confirms data integrity

**Use cases**:
- Before restoring a backup
- After creating a backup
- Verifying old backups are still valid

### 4. Check Coverage

Check validation coverage for all MongoDB collections.

```bash
depictio-cli backup check-coverage
```

**What it does**:
- Scans all collections
- Reports which have Pydantic models
- Shows coverage percentage
- Identifies unvalidated collections

### 5. Restore Backup

Restore data from a backup file.

```bash
depictio-cli backup restore --backup-file FILENAME
```

**WARNING**: This will overwrite existing data!

**What it does**:
- Loads backup file
- Validates data
- Restores to MongoDB
- Confirms restoration

**Options**:
- May require confirmation
- Should validate backup first

## Complete Workflow Examples

### Regular Backup Workflow

1. **Create backup**:
   ```bash
   depictio-cli backup create --verbose
   ```

2. **Verify backup**:
   ```bash
   depictio-cli backup list
   depictio-cli backup validate --backup-file backup_YYYYMMDD_HHMMSS.json
   ```

### Restore from Backup

1. **List available backups**:
   ```bash
   depictio-cli backup list
   ```

2. **Validate backup before restore**:
   ```bash
   depictio-cli backup validate --backup-file backup_YYYYMMDD_HHMMSS.json
   ```

3. **Restore**:
   ```bash
   depictio-cli backup restore --backup-file backup_YYYYMMDD_HHMMSS.json
   ```

4. **Verify restoration**:
   - Check application is working
   - Verify data is present
   - Test critical workflows

### Development Workflow

1. **Before major changes**:
   ```bash
   depictio-cli backup create --verbose
   ```

2. **Make changes** (migrations, schema updates, etc.)

3. **If something breaks**:
   ```bash
   depictio-cli backup restore --backup-file backup_YYYYMMDD_HHMMSS.json
   ```

## Process for Using This Skill

1. **Determine operation needed**:
   - Backup: Creating a new backup
   - Restore: Recovering from backup
   - List: Viewing available backups
   - Validate: Checking backup integrity

2. **Check prerequisites**:
   - MongoDB running (localhost:27018)
   - Sufficient disk space for backups
   - Permissions to access MongoDB

3. **Execute CLI command**:
   - Use full Python path
   - Add `--verbose` for detailed output
   - Provide required options (e.g., backup filename)

4. **Handle results**:
   - Success: Show confirmation
   - Errors: Help debug (connection, permissions, validation)
   - Validate: Show coverage and errors

## Common Use Cases

**Pre-deployment backup**:
```bash
depictio-cli backup create --verbose
```

**Emergency restore**:
```bash
depictio-cli backup list
depictio-cli backup restore --backup-file latest_backup.json
```

**Data integrity check**:
```bash
depictio-cli backup check-coverage
depictio-cli backup validate --backup-file backup.json
```

**Migration safety**:
```bash
# Before migration
depictio-cli backup create --verbose

# Run migration
# ...

# If migration fails, restore
depictio-cli backup restore --backup-file pre_migration_backup.json
```

## Error Handling

**MongoDB connection errors**:
- Check MongoDB is running: `docker ps` or `pixi run status-infra`
- Verify connection string in config
- Check network connectivity

**Validation errors**:
- Review Pydantic model changes
- Check for schema migrations needed
- Validate data format

**Backup file not found**:
- List available backups: `depictio-cli backup list`
- Check file path and permissions
- Verify backup directory exists

**Insufficient disk space**:
- Check available space: `df -h`
- Clean up old backups
- Compress backup files

## Backup Best Practices

1. **Regular backups**: Schedule daily/weekly backups
2. **Pre-change backups**: Always backup before major changes
3. **Validate backups**: Regularly validate backup integrity
4. **Offsite storage**: Copy critical backups to external storage
5. **Retention policy**: Keep backups for defined periods
6. **Test restores**: Periodically test restoration process

## Integration with Other Skills

- Use before `/bump-version` for major releases
- Use before database migrations
- Use in `/create-pr` workflow for data model changes
- Integrate with deployment workflows

## Automation Ideas

**Pre-commit hook for model changes**:
- Detect changes in `depictio/models/`
- Automatically create backup
- Validate against new models

**CI/CD integration**:
- Backup before deployment
- Restore on deployment failure
- Validate backup in CI pipeline

**Scheduled backups**:
- Cron job for daily backups
- Automatic cleanup of old backups
- Email notifications on backup failure
