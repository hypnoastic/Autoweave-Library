# Troubleshooting

Common issues and their resolutions when operating AutoWeave.

## Database Locks (SQLite)
If you see "database is locked" errors, it usually means the Celery worker and the UI server are competing for database writes. 
**Solution:** Stop both processes and restart them cleanly using `autoweave start`.

## Missing OpenHands Runtime
If `autoweave doctor` reports a missing OpenHands bootstrap path, ensure you have correctly installed the required Docker dependencies or pulled the latest OpenHands image.

## Stale Runs Showing in Dashboard
If the UI dashboard is showing stale runs or incomplete executions that are no longer active in the Celery queue:
**Solution:** Run the cleanup command to purge stale state:
```bash
autoweave cleanup-local-state
```

## UI Fails to Bind Port
If starting the UI throws an "Address already in use" error for port 8766:
**Solution:** Kill any existing processes bound to that port:
```bash
kill -9 $(lsof -t -i :8766)
```
