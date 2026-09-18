-- Part of place_responder. Licensed under AGPL-3.0.
--
-- The role the responder connects as: it may read the places and the ranking spec, LISTEN,
-- and nothing else. Not the partners, not the parameters (which hold API keys and the
-- database secret), not a single write. Run once, as the database owner, in the ikiku
-- database; the password is written to /opt/ikiku/secrets/places_dsn and nowhere else.
--
--   docker compose exec -T db psql -U odoo -d ikiku -v pw="'<password>'" -f - < places_ro.sql
CREATE ROLE places_ro LOGIN PASSWORD :pw NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
    CONNECTION LIMIT 4;
ALTER ROLE places_ro SET default_transaction_read_only = on;
ALTER ROLE places_ro SET statement_timeout = '60s';
GRANT CONNECT ON DATABASE ikiku TO places_ro;
GRANT USAGE ON SCHEMA public TO places_ro;
GRANT SELECT ON place_node, place_alias, place_link, place_postcode, res_lang, place_responder_spec
    TO places_ro;
