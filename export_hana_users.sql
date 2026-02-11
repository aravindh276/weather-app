-- =============================================================================
-- SAP HANA: Export Users with All Roles and Privileges
-- =============================================================================
-- This script queries HANA system views to extract a complete picture of
-- every database user together with their granted roles and privileges.
-- Run with a user that has the CATALOG READ or DATA ADMIN privilege.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. List all database users with basic account details
-- ---------------------------------------------------------------------------
SELECT
    U.USER_NAME,
    U.USER_DEACTIVATED,
    U.DEACTIVATION_TIME,
    U.LAST_SUCCESSFUL_CONNECT,
    U.LAST_INVALID_CONNECT_ATTEMPT,
    U.INVALID_CONNECT_ATTEMPTS,
    U.PASSWORD_CHANGE_TIME,
    U.PASSWORD_CHANGE_NEEDED,
    U.USER_ID,
    U.CREATOR,
    U.CREATE_TIME
FROM
    SYS.USERS U
ORDER BY
    U.USER_NAME;


-- ---------------------------------------------------------------------------
-- 2. Roles granted to each user (direct grants)
-- ---------------------------------------------------------------------------
SELECT
    GRANTEE          AS USER_NAME,
    ROLE_NAME,
    GRANTOR,
    IS_GRANTABLE
FROM
    SYS.GRANTED_ROLES
WHERE
    GRANTEE_TYPE = 'USER'
ORDER BY
    GRANTEE,
    ROLE_NAME;


-- ---------------------------------------------------------------------------
-- 3. System privileges granted to each user
--    (e.g., CREATE SCHEMA, DATA ADMIN, USER ADMIN, etc.)
-- ---------------------------------------------------------------------------
SELECT
    GRANTEE          AS USER_NAME,
    PRIVILEGE        AS SYSTEM_PRIVILEGE,
    GRANTOR,
    IS_GRANTABLE
FROM
    SYS.GRANTED_PRIVILEGES
WHERE
    GRANTEE_TYPE = 'USER'
ORDER BY
    GRANTEE,
    PRIVILEGE;


-- ---------------------------------------------------------------------------
-- 4. Object privileges granted to each user
--    (e.g., SELECT, INSERT, EXECUTE on specific schemas/tables/procedures)
-- ---------------------------------------------------------------------------
SELECT
    GRANTEE          AS USER_NAME,
    SCHEMA_NAME,
    OBJECT_NAME,
    OBJECT_TYPE,
    PRIVILEGE,
    GRANTOR,
    IS_GRANTABLE
FROM
    SYS.GRANTED_PRIVILEGES
WHERE
    GRANTEE_TYPE = 'USER'
    AND OBJECT_NAME IS NOT NULL
ORDER BY
    GRANTEE,
    SCHEMA_NAME,
    OBJECT_NAME,
    PRIVILEGE;


-- ---------------------------------------------------------------------------
-- 5. System privileges granted to each user (excluding object-level)
-- ---------------------------------------------------------------------------
SELECT
    GRANTEE          AS USER_NAME,
    PRIVILEGE        AS SYSTEM_PRIVILEGE,
    GRANTOR,
    IS_GRANTABLE
FROM
    SYS.GRANTED_PRIVILEGES
WHERE
    GRANTEE_TYPE = 'USER'
    AND OBJECT_NAME IS NULL
ORDER BY
    GRANTEE,
    PRIVILEGE;


-- ---------------------------------------------------------------------------
-- 6. Roles granted to each user including roles inherited through other roles
--    (effective / recursive role hierarchy)
-- ---------------------------------------------------------------------------
SELECT
    USER_NAME,
    ROLE_NAME,
    ROLE_SCHEMA_NAME,
    IS_GRANTABLE
FROM
    SYS.EFFECTIVE_ROLES
ORDER BY
    USER_NAME,
    ROLE_NAME;


-- ---------------------------------------------------------------------------
-- 7. Effective privileges per user (all privileges including those inherited
--    through roles — the complete resolved picture)
-- ---------------------------------------------------------------------------
SELECT
    USER_NAME,
    SCHEMA_NAME,
    OBJECT_NAME,
    OBJECT_TYPE,
    PRIVILEGE,
    IS_GRANTABLE
FROM
    SYS.EFFECTIVE_PRIVILEGES
ORDER BY
    USER_NAME,
    SCHEMA_NAME,
    OBJECT_NAME,
    PRIVILEGE;


-- ---------------------------------------------------------------------------
-- 8. Analytic privileges granted to each user
-- ---------------------------------------------------------------------------
SELECT
    GRANTEE          AS USER_NAME,
    ANALYTIC_PRIVILEGE_NAME,
    GRANTOR,
    IS_GRANTABLE
FROM
    SYS.EFFECTIVE_PRIVILEGE_GRANTEES
WHERE
    GRANTEE_TYPE = 'USER'
ORDER BY
    GRANTEE,
    ANALYTIC_PRIVILEGE_NAME;


-- ---------------------------------------------------------------------------
-- 9. Combined summary: one row per user with comma-separated role list
--    (useful for a quick overview / export to CSV)
-- ---------------------------------------------------------------------------
SELECT
    U.USER_NAME,
    U.USER_DEACTIVATED,
    U.LAST_SUCCESSFUL_CONNECT,
    STRING_AGG(GR.ROLE_NAME, ', ' ORDER BY GR.ROLE_NAME) AS GRANTED_ROLES
FROM
    SYS.USERS U
LEFT JOIN
    SYS.GRANTED_ROLES GR
    ON U.USER_NAME = GR.GRANTEE
   AND GR.GRANTEE_TYPE = 'USER'
GROUP BY
    U.USER_NAME,
    U.USER_DEACTIVATED,
    U.LAST_SUCCESSFUL_CONNECT
ORDER BY
    U.USER_NAME;


-- ---------------------------------------------------------------------------
-- 10. Generate CREATE USER + GRANT statements for migration / re-creation
--     (passwords are not extractable; placeholders are used)
-- ---------------------------------------------------------------------------

-- 10a. CREATE USER statements
SELECT
    'CREATE USER "' || USER_NAME || '" PASSWORD "ChangeMe123!" NO FORCE_FIRST_PASSWORD_CHANGE;'
        AS DDL_STATEMENT
FROM
    SYS.USERS
WHERE
    USER_NAME NOT LIKE '_SYS%'
    AND USER_NAME NOT IN ('SYSTEM', 'SYS')
ORDER BY
    USER_NAME;

-- 10b. GRANT ROLE statements
SELECT
    'GRANT "' || ROLE_NAME || '" TO "' || GRANTEE || '"'
    || CASE WHEN IS_GRANTABLE = 'TRUE' THEN ' WITH ADMIN OPTION' ELSE '' END
    || ';'
        AS DDL_STATEMENT
FROM
    SYS.GRANTED_ROLES
WHERE
    GRANTEE_TYPE = 'USER'
    AND GRANTEE NOT LIKE '_SYS%'
    AND GRANTEE NOT IN ('SYSTEM', 'SYS')
ORDER BY
    GRANTEE,
    ROLE_NAME;

-- 10c. GRANT system privilege statements
SELECT
    'GRANT ' || PRIVILEGE || ' TO "' || GRANTEE || '"'
    || CASE WHEN IS_GRANTABLE = 'TRUE' THEN ' WITH ADMIN OPTION' ELSE '' END
    || ';'
        AS DDL_STATEMENT
FROM
    SYS.GRANTED_PRIVILEGES
WHERE
    GRANTEE_TYPE = 'USER'
    AND OBJECT_NAME IS NULL
    AND GRANTEE NOT LIKE '_SYS%'
    AND GRANTEE NOT IN ('SYSTEM', 'SYS')
ORDER BY
    GRANTEE,
    PRIVILEGE;

-- 10d. GRANT object privilege statements
SELECT
    'GRANT ' || PRIVILEGE || ' ON '
    || CASE
         WHEN OBJECT_TYPE = 'SCHEMA' THEN 'SCHEMA "' || OBJECT_NAME || '"'
         ELSE '"' || SCHEMA_NAME || '"."' || OBJECT_NAME || '"'
       END
    || ' TO "' || GRANTEE || '"'
    || CASE WHEN IS_GRANTABLE = 'TRUE' THEN ' WITH GRANT OPTION' ELSE '' END
    || ';'
        AS DDL_STATEMENT
FROM
    SYS.GRANTED_PRIVILEGES
WHERE
    GRANTEE_TYPE = 'USER'
    AND OBJECT_NAME IS NOT NULL
    AND GRANTEE NOT LIKE '_SYS%'
    AND GRANTEE NOT IN ('SYSTEM', 'SYS')
ORDER BY
    GRANTEE,
    SCHEMA_NAME,
    OBJECT_NAME,
    PRIVILEGE;
