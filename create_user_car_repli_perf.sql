-- =============================================================================
-- SQL Script: Create user CAR_REPLI_PERF (SAP HANA)
-- Description: Creates the CAR_REPLI_PERF database user with necessary privileges
-- =============================================================================

-- Create the user with password
CREATE USER CAR_REPLI_PERF PASSWORD Car_Repli_Perf1;

-- Disable password expiration (optional, remove if policy requires rotation)
ALTER USER CAR_REPLI_PERF DISABLE PASSWORD LIFETIME;

-- Grant schema-level privileges
GRANT CREATE ANY ON SCHEMA CAR_REPLI_PERF TO CAR_REPLI_PERF;

-- Grant catalog read access for replication performance monitoring
GRANT CATALOG READ TO CAR_REPLI_PERF;
GRANT MONITORING TO CAR_REPLI_PERF;

-- Grant role for general development tasks
GRANT CONTENT_ADMIN TO CAR_REPLI_PERF;
