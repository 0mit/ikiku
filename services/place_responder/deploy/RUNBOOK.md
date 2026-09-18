# Deploying the place responder, and the bundle loader it rides on

Written 2026-09-18 for the production host (one core, about 8 GiB shared with Odoo and Postgres,
docker compose at /opt/ikiku). Every step can be undone on its own, and the site works
at every point in between: with no responder, the «کجا؟» box asks Odoo as it does today.

## 0. Before

    # on the production host, as always before a deploy
    docker compose exec -T db pg_dump -U odoo ikiku | gzip > /opt/ikiku/backups/ikiku-db-<date>-pre-responder.sql.gz

## 1. The Odoo side (code only; nothing is switched on yet)

    rsync -a --delete -e "ssh -p $PROD_SSH_PORT" ~/ikiku/ root@$PROD_HOST:/opt/ikiku/src/
    docker compose run --rm --no-deps -T odoo odoo -c /etc/odoo/odoo.conf -d ikiku \
        -u place_graph,search_suggest --stop-after-init --workers=0 </dev/null
    docker compose restart odoo

`-u place_graph` reaches place_ir, ikiku_base and everything above them. What it does, in
order, and as measured on a copy built the old way:

- adds `origin`, `kept_fields` and `bundle_key`; the 19.0.1.1.0 migration marks every row the
  OSM import wrote as `origin='bundle'` and keys it, so nothing is duplicated;
- installs the NOTIFY triggers on the four place tables, publishes the ranking spec, and
  creates the view `place_responder_spec`;
- place_ir's first sync against the existing rows finds 2 changed places (the two with no
  point, whose 0.0 becomes NULL) and re-derives 568 search indexes. That took 4.4 s on
  a workstation; expect under a minute on one core;
- adds «پیشنهادها» (Places → Suggestions) for place editors.

## 2. The read-only role

    openssl rand -base64 24 | tr -d '/+=' > /tmp/pw && chmod 600 /tmp/pw
    docker compose exec -T db psql -U odoo -d ikiku -v pw="'$(cat /tmp/pw)'" \
        -f - < /opt/ikiku/src/services/place_responder/deploy/places_ro.sql
    printf 'postgres://places_ro:%s@db:5432/ikiku?sslmode=disable\n' "$(cat /tmp/pw)" \
        > /opt/ikiku/secrets/places_dsn && chmod 600 /opt/ikiku/secrets/places_dsn && rm /tmp/pw

The role may read the four place tables, `res_lang` and the spec view, and may LISTEN. It
cannot read partners, and it cannot read `ir_config_parameter`, which holds the SMS keys and
the database secret.

## 3. The image (built on the build machine, shipped by hand)

    cd ~/ikiku/services/place_responder/deploy && make test && make save
    scp -P $PROD_SSH_PORT place-responder-<version>.tar.gz root@$PROD_HOST:/opt/ikiku/
    # on the host
    gunzip -c /opt/ikiku/place-responder-<version>.tar.gz | docker load
    cp /opt/ikiku/src/services/place_responder/deploy/compose.places.yml /opt/ikiku/
    cd /opt/ikiku && PLACES_VERSION=<version> docker compose -f docker-compose.yml -f compose.places.yml up -d places
    curl -s 127.0.0.1:8071/healthz      # ready, 103415 places, "spec": "from the source"

## 4. nginx

Add `limit_req_zone` in the http block and the `location = /places/q` block from
`nginx-places.conf` to the ikiku.ir server block. Then:

    nginx -t && systemctl reload nginx
    curl -s 'https://ikiku.ir/places/q?q=%DA%A9%D8%A7%D8%AE&kinds=all' | head -c 300

## 5. Switch it on

    # Odoo → Settings → Technical → System Parameters, or:
    docker compose exec -T odoo odoo shell -c /etc/odoo/odoo.conf -d ikiku --no-http <<'EOF'
    env['ir.config_parameter'].set_param('place_graph.responder_url', '/places/q'); env.cr.commit()
    EOF

To switch it off, clear the parameter. Pages go back to Odoo's `/places/suggest` on the
next load, and the responder can then be stopped at leisure.

## 6. After

- Walk `/join/where` and `/business/need/where` on a phone. The box should answer as you
  type, and «کو» should turn only when the network is slow.
- In `/healthz`, `generation` should rise a few seconds after a place is edited in Odoo.
- Record the deploy in daftar (`ikiku-prod`) and draft the announcement
  (`tools/announce.py preview`). It is posted only after it has been read and approved.
