-- =============================================================================
-- SQL Script: Create user CAR_REPLI_PERF
-- Description: Creates the CAR_REPLI_PERF database user with necessary privileges
-- =============================================================================

-- Create the user with a default tablespace and temporary tablespace
CREATE USER CAR_REPLI_PERF
  IDENTIFIED BY CAR_REPLI_PERF
  DEFAULT TABLESPACE USERS
  TEMPORARY TABLESPACE TEMP
  QUOTA UNLIMITED ON USERS;

-- Grant basic connection and session privileges
GRANT CREATE SESSION TO CAR_REPLI_PERF;
GRANT CONNECT TO CAR_REPLI_PERF;

-- Grant resource privileges for creating schema objects
GRANT RESOURCE TO CAR_REPLI_PERF;

-- Grant privileges required for replication performance monitoring
GRANT CREATE TABLE TO CAR_REPLI_PERF;
GRANT CREATE VIEW TO CAR_REPLI_PERF;
GRANT CREATE SEQUENCE TO CAR_REPLI_PERF;
GRANT CREATE PROCEDURE TO CAR_REPLI_PERF;
GRANT CREATE TRIGGER TO CAR_REPLI_PERF;
GRANT CREATE SYNONYM TO CAR_REPLI_PERF;
