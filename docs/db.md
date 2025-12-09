Canonical DB: supertl2.db

Key tables:

activity – one row per real workout

activity_source – one row per source per workout

source ∈ ('strava','sporttracks')

source_activity_id == StravaActivity.activityId when source='strava'

StravaActivity – clone of stats-for-strava’s Activity

TrainingLogData – extra metadata keyed by Strava activityId, with optional canonical_activity_id → activity.id

Important invariants we now have:

Every row in StravaActivity has a corresponding activity_source row except the ones you explicitly haven’t imported (currently 0).

Every canonical activity row that originated from Strava has a corresponding activity_source row with:

source = 'strava'

source_activity_id = StravaActivity.activityId


## Utils

### Check for any unmapped Strava rows

```sql
SELECT COUNT(*) AS unmapped_strava
FROM StravaActivity s
LEFT JOIN activity_source src
  ON src.source = 'strava'
 AND src.source_activity_id = s.activityId
WHERE src.activity_id IS NULL;
```

### Check for any canonical activities with no source

```sql
SELECT COUNT(*) AS sourceless_activities
FROM activity a
LEFT JOIN activity_source src
  ON src.activity_id = a.id
WHERE src.id IS NULL;
```

### Spot TrainingLogData entries not yet linked to canonical

```sql
SELECT COUNT(*) AS tld_unlinked
FROM TrainingLogData t
LEFT JOIN activity_source src
  ON src.source = 'strava'
 AND src.source_activity_id = t.activityId
LEFT JOIN activity a
  ON a.id = src.activity_id
WHERE t.canonical_activity_id IS NULL
  AND a.id IS NOT NULL;
```

if that is >0, optionallly run:

```sql
UPDATE TrainingLogData
   SET canonical_activity_id = (
     SELECT a.id
     FROM activity_source src
     JOIN activity a ON a.id = src.activity_id
     WHERE src.source = 'strava'
       AND src.source_activity_id = TrainingLogData.activityId
   )
 WHERE canonical_activity_id IS NULL
   AND EXISTS (
     SELECT 1
     FROM activity_source src
     JOIN activity a ON a.id = src.activity_id
     WHERE src.source = 'strava'
       AND src.source_activity_id = TrainingLogData.activityId
   );
```