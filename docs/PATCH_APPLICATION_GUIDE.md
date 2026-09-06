# PATCH APPLICATION GUIDE

## Overview
This directory contains 6 patch files to fix critical and high-priority bugs in the cloudrun repository.

## Patches Included

### 1. 001-favicon-status-code.patch
**Fixes:** Bug #1 - HTTP 204 with body violation
**File:** server/main.py
**Impact:** HIGH
**Apply with:** `git apply 001-favicon-status-code.patch`

### 2. 002-race-condition-eviction.patch
**Fixes:** Bug #2 - Race condition in user manager eviction
**File:** server/api_routes.py
**Impact:** CRITICAL
**Apply with:** `git apply 002-race-condition-eviction.patch`

### 3. 003-missing-import.patch
**Fixes:** Bug #3 - Missing DownloadStage import
**File:** server/api_routes.py
**Impact:** HIGH
**Apply with:** `git apply 003-missing-import.patch`

### 4. 004-convert-m3u8-error-handling.patch
**Fixes:** Bug #5 - Undefined process variable in error handling
**File:** server/api_routes.py
**Impact:** MEDIUM
**Apply with:** `git apply 004-convert-m3u8-error-handling.patch`

### 5. 005-dockerfile-n-m3u8-fallback.patch
**Fixes:** Bug #6 - Hardcoded release URL with no fallback
**File:** Dockerfile
**Impact:** MEDIUM
**Apply with:** `git apply 005-dockerfile-n-m3u8-fallback.patch`

### 6. 006-wrapper-watchdog-logging.patch
**Fixes:** Bug #7 - Silent wrapper binary skip without logging
**File:** server/main.py
**Impact:** MEDIUM
**Apply with:** `git apply 006-wrapper-watchdog-logging.patch`

## Application Instructions

### Option 1: Apply All Patches at Once
```bash
cd /path/to/cloudrun
git apply 001-favicon-status-code.patch
git apply 002-race-condition-eviction.patch
git apply 003-missing-import.patch
git apply 004-convert-m3u8-error-handling.patch
git apply 005-dockerfile-n-m3u8-fallback.patch
git apply 006-wrapper-watchdog-logging.patch
```

### Option 2: Apply Patches by Priority
```bash
# CRITICAL fixes first
git apply 002-race-condition-eviction.patch

# HIGH priority
git apply 001-favicon-status-code.patch
git apply 003-missing-import.patch

# MEDIUM priority
git apply 004-convert-m3u8-error-handling.patch
git apply 005-dockerfile-n-m3u8-fallback.patch
git apply 006-wrapper-watchdog-logging.patch
```

### Option 3: Manual Application
If `git apply` fails, you can manually apply the changes by:
1. Opening the patch file
2. Reading the diff
3. Manually editing the target file with the changes shown

## Testing After Patches

### Unit Tests
```bash
# Test user manager eviction logic
pytest tests/test_api_routes.py::test_user_manager_eviction

# Test favicon endpoint
pytest tests/test_main.py::test_favicon_404

# Test convert_m3u8 error handling
pytest tests/test_api_routes.py::test_convert_m3u8_timeout
```

### Integration Tests
```bash
# Full integration test suite
pytest tests/integration/

# Docker build test
docker build -t cloudrun:test .
```

### Manual Testing
1. **Favicon:** Visit http://localhost:8000/favicon.ico (should return 404)
2. **User Manager:** Monitor logs for user manager eviction messages
3. **Wrapper Watchdog:** Check logs for wrapper binary detection on startup
4. **M3U8 Conversion:** Test with timeout scenarios

## Rollback Instructions

If you need to revert a patch:
```bash
git apply -R 001-favicon-status-code.patch
```

Or revert all:
```bash
git checkout -- server/main.py server/api_routes.py Dockerfile
```

## Verification Checklist

After applying patches:
- [ ] All patches applied without conflicts
- [ ] Code compiles/imports without errors
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Docker build succeeds
- [ ] Server starts without errors
- [ ] Favicon endpoint returns 404
- [ ] User manager logs show proper eviction
- [ ] Wrapper watchdog logs show binary detection

## Support

For issues applying patches:
1. Check the BUG_REPORT.md for detailed explanations
2. Verify you're in the correct directory
3. Check git status for conflicts
4. Review the patch file content manually
5. Apply changes manually if needed

## Additional Recommendations

1. **Add unit tests** for user manager eviction logic
2. **Add integration tests** for timeout scenarios
3. **Add logging** for all error paths
4. **Consider adding** a pre-commit hook to catch similar issues
5. **Review** other async code for similar race conditions
