# Initialization Race Condition Fix

## Problem Summary

The initialization system had a critical race condition where multiple workers would ALL wipe and reinitialize the database, causing:

1. **Empty database**: Projects were created but then deleted by subsequent workers
2. **Authorization errors**: Data collection registration failed because projects didn't exist
3. **Dashboard loading failures**: Components had wrong DC IDs due to initialization chaos

## Root Cause

Multiple workers were acquiring the initialization lock and wiping the database simultaneously:

**Sequence of events** (before fix):
1. Worker 1 acquires lock
2. Worker 1 wipes database → **Deletes the lock document!**
3. Worker 2 starts, finds no lock (because it was deleted), acquires lock
4. Worker 2 wipes database → **Destroys Worker 1's work!**
5. Worker 3 starts, finds no lock, acquires lock...
6. Repeat indefinitely

**Evidence from logs**:
```
21:44:00 - Worker 84: Acquired initialization lock
21:44:09 - Worker 99: Acquired initialization lock   ← 9s later!
21:44:22 - Worker 150: Acquired initialization lock  ← 13s later!
21:44:37 - Worker 202: Acquired initialization lock  ← 15s later!
```

Each worker wiped the database:
```
21:44:09 - Wipe is enabled. Deleting the database...
21:44:22 - Wipe is enabled. Deleting the database...
21:44:37 - Wipe is enabled. Deleting the database...
```

## Solution Applied

**Modified**: `depictio/api/v1/db_init.py` (lines 384-402)

**Before**:
```python
async def initialize_db(wipe: bool = False) -> UserBeanie | None:
    _ensure_mongodb_connection()

    if wipe:
        logger.info("Wipe is enabled. Deleting the database...")
        client.drop_database(settings.mongodb.db_name)
        logger.info("Database deleted successfully.")
```

**After**:
```python
async def initialize_db(wipe: bool = False) -> UserBeanie | None:
    _ensure_mongodb_connection()

    if wipe:
        logger.info("Wipe is enabled. Deleting the database...")
        # Preserve the init_lock before wiping to prevent other workers from acquiring lock
        init_lock = initialization_collection.find_one({"_id": "init_lock"})

        client.drop_database(settings.mongodb.db_name)
        logger.info("Database deleted successfully.")

        # Restore the init_lock to prevent race conditions with other workers
        if init_lock:
            initialization_collection.insert_one(init_lock)
            logger.info("Restored initialization lock after database wipe")
```

## Verification

### 1. Lock Preservation Working
```
21:50:20 - Worker 262: Acquired initialization lock
21:50:20 - Wipe is enabled. Deleting the database...
21:50:20 - Restored initialization lock after database wipe  ✅
```

**Only Worker 262 is active** - no other workers acquired the lock.

### 2. Projects Created and Persisted
```
21:50:21 - ✅ Created iris project
21:50:21 - ✅ Created penguins project
21:50:21 - ✅ Created ampliseq project
```

**Database verification**:
```javascript
db.projects.find({}, {name: 1})
// Results:
// - Iris Dataset Project Data Analysis (646b0f3c1e4a2d7f8e5b8c9a)
// - Palmer Penguins Species Comparison (646b0f3c1e4a2d7f8e5b8c9d)
// - Ampliseq Microbial Community Analysis (646b0f3c1e4a2d7f8e5b8ca2)
```

### 3. Dashboard Components Have Correct DC IDs
```javascript
db.dashboards.findOne({_id: ObjectId('646b0f3c1e4a2d7f8e5b8ca2')})
// Component Type | DC ID
// multiqc        | 646b0f3c1e4a2d7f8e5b8ca4 (multiqc_data) ✅
// interactive    | 646b0f3c1e4a2d7f8e5b8ca5 (metadata) ✅
// figure         | 646b0f3c1e4a2d7f8e5b8ca8 (alpha_rarefaction) ✅
// figure         | 646b0f3c1e4a2d7f8e5b8ca9 (taxonomy_composition) ✅
// figure         | 646b0f3c1e4a2d7f8e5b8caa (ancom_volcano) ✅
// table          | 646b0f3c1e4a2d7f8e5b8ca5 (metadata) ✅
```

### 4. No Authorization Errors
```
21:50:32 - Successfully processed 1 MultiQC files
21:50:34 - ✅ Successfully processed ampliseq
```

**No more errors** like:
```
❌ Error upserting Delta table metadata: {"detail":"No projects containing Data Collection id X found for the current user."}
```

### 5. No Frontend Errors
```bash
docker logs depictio-frontend 2>&1 | grep -i "error.*column"
# No output - no errors! ✅
```

## Summary

**Single Fix**: Preserve initialization lock during database wipe

**Result**:
- ✅ Only one worker initializes the database
- ✅ Projects persist in the database
- ✅ Dashboard components have correct DC IDs (multi-DC support working)
- ✅ Deltatables registered for all data collections
- ✅ No authorization errors during background processing
- ✅ No column errors in frontend

**Files Modified**:
- `depictio/api/v1/db_init.py` - Added lock preservation during database wipe

**No Configuration Changes Required**: The issue was purely in the initialization code, not in project.yaml or dashboard.json.
