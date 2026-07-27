-- viet-text2sql-agent — database-level read-only role.
--
-- This is layer 1 of the defense-in-depth model and the only layer that survives a bug in
-- the agent, the prompt, or the AST policy. Everything the application can do to this
-- database, it can do because of the grants below — nothing else.
--
-- Run as a superuser against the application database:
--   psql -d t2sql -v ro_password="'<from your secret store>'" -f db/roles.sql
--
-- The password is passed in as a psql variable; it is never written to this file.

\set ON_ERROR_STOP on

-- 1. The role itself ---------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't2sql_ro') THEN
        CREATE ROLE t2sql_ro LOGIN;
    END IF;
END
$$;

ALTER ROLE t2sql_ro PASSWORD :ro_password;

-- 2. Revoke everything first, then grant back only what is needed -------------
REVOKE ALL ON DATABASE  t2sql  FROM PUBLIC;
REVOKE ALL ON SCHEMA    public FROM t2sql_ro;
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM t2sql_ro;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM t2sql_ro;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM t2sql_ro;

GRANT CONNECT ON DATABASE  t2sql  TO t2sql_ro;
GRANT USAGE  ON SCHEMA     public TO t2sql_ro;

-- 3. SELECT-only on the allowlisted tables ------------------------------------
--    Kept in sync with src/t2sql/guardrails/policy.yaml -> allowed_tables.
GRANT SELECT ON
    regions,
    customers,
    addresses,
    categories,
    suppliers,
    products,
    inventory,
    orders,
    order_items,
    payments,
    shipments,
    reviews
TO t2sql_ro;

-- agent_traces is written by the app role, never read or written by t2sql_ro.
REVOKE ALL ON agent_traces FROM t2sql_ro;

-- 4. No future privileges leak in --------------------------------------------
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM t2sql_ro;

-- 5. Hard server-side limits --------------------------------------------------
--    statement_timeout is the backstop for a cartesian blow-up that the AST policy
--    could not statically detect.
ALTER ROLE t2sql_ro SET statement_timeout = '5s';
ALTER ROLE t2sql_ro SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE t2sql_ro SET default_transaction_read_only = on;
ALTER ROLE t2sql_ro SET search_path = 'public';

-- 6. Verification (run manually after applying) -------------------------------
--   \c t2sql t2sql_ro
--   INSERT INTO orders (order_id) VALUES (1);   -- expected: ERROR permission denied
--   SELECT count(*) FROM orders;                -- expected: succeeds
--   SELECT * FROM pg_catalog.pg_tables;         -- readable at DB level; blocked by AST policy
