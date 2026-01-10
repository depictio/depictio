# Database Helper

MongoDB database operations and queries for depictio.

## Instructions

Help with MongoDB operations:

1. **Connection info**:
   - MongoDB URL: `localhost:27018`
   - Database: `depictioDB`
   - Use mongosh for queries

2. **Available collections**:
   - `users` - User accounts
   - `groups` - User groups
   - `projects` - Projects
   - `workflows` - Workflow definitions
   - `data_collections` - Data collection metadata
   - `dashboards` - Dashboard configurations
   - `files` - File metadata
   - `tokens` - API tokens
   - `analytics` - Usage analytics

3. **Common operations**:

   ```bash
   # Connect to MongoDB
   mongosh mongodb://localhost:27018/depictioDB

   # List collections
   mongosh mongodb://localhost:27018/depictioDB --eval "db.getCollectionNames()"

   # Count documents
   mongosh mongodb://localhost:27018/depictioDB --eval "db.users.countDocuments()"

   # Find documents
   mongosh mongodb://localhost:27018/depictioDB --eval "db.users.find().limit(5).toArray()"
   ```

4. **Safety rules**:
   - NEVER drop collections without explicit confirmation
   - NEVER delete data without backup
   - Always use `--eval` for non-interactive queries
   - Show query before executing

## Usage

`/db collections` - List all collections with counts
`/db query <collection> <query>` - Run a find query
`/db count <collection>` - Count documents in collection
`/db indexes <collection>` - Show indexes for collection

$ARGUMENTS
