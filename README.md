# ایکیکو — iKiKu

A cooperative that records, verifies and stands behind hospitality
professionals in Iran — and matches them to the cafés and restaurants that
need them, a quarter ahead.

**آیکی** (Yazdi) is the one you don't necessarily know. **کو** is Dehkhoda's
"where is he" — reserved, he notes, for the absent third person. Both halves of
the name describe the same figure: someone absent, and unknown. Turning that
person into someone you know, and know the whereabouts of, is the whole product.

## Read first

| document | what it is |
|---|---|
| `docs/MANIFEST.fa.md` | **مرام‌نامه** — the eleven articles and the five prohibitions. Law. |
| `CHARTER.fa.md` | the co-op's structure, and why the licence alone was not enough. |
| `docs/design.html` | the build map: reuse, data model, phases. |
| `LICENSE` | AGPL-3.0, for all code. |

## Modules

| module | holds |
|---|---|
| `ikiku_base` | spec tree + overlays + candidates, Jalali, provinces, seasons, visibility policy, assertion/verification/dispute ledger, identity on `res.partner` |
| `ikiku_supply` | resource profile, skills, résumé, availability windows |
| `ikiku_demand` | business, positions as overlays, declared demand |
| `ikiku_match` | proposals with readable scores, bookings, public register, pre-shift re-checks |
| `ikiku_coop` | periodic cost, shared by person-days |
| `ikiku_portal` | the Persian RTL portal and the public pages |

Everything depends only on LGPL-3 Odoo modules. Planning, Helpdesk, Appointment,
Sign and Documents are `OEEL-1` and are **not** used — the call centre runs on
`project`, and shift scheduling is ours, built on Community's `resource`.

## Install

```sh
git clone <remote> ikiku && cd ikiku
sh tools/fetch_fonts.sh          # once, from a machine that can reach GitHub
odoo-bin -d ikiku --addons-path=<odoo>/addons,addons -i ikiku_portal
```

`ikiku_portal` pulls in every other module. Then set the identity salt, without
which no national ID can be hashed and the portal will refuse to store one:

```sh
# Settings > Technical > System Parameters
ikiku.nid_salt = <a long random string, backed up separately>
```

## Three rules that are not negotiable in code

1. **Dates are stored Gregorian/UTC and converted at the boundary.** A Jalali
   string in a column is a bug. `ikiku_base/models/jalali.py` is vendored so a
   filtered network cannot break a build.
2. **Visibility is data.** `ikiku.visibility.policy` decides what the public
   sees. A field with no row is restricted — fail closed.
3. **The score is readable.** Weights are constants in
   `ikiku_match/models/ikiku_proposal.py`, every component is stored on the
   proposal, and the explanation is generated from the same numbers as the
   total. A learned ranker cannot satisfy بند ۸ and must not be added.

## Deployment, specifically for Iran

- **Not Odoo.sh, not GCP.** Measured: every Odoo.sh build host resolves to
  `35.241.236.166` and times out on 22 and 443 from here. Self-host.
- **No CDN in production.** Fonts are self-hosted; audit any theme that reaches
  for `fonts.googleapis.com` or Google Maps.
- **Video is not YouTube.** `website_slides` embeds YouTube and Drive by
  default; use self-hosted files or Aparat.
- **OTP via an Iranian SMS gateway** — phone is the establishing anchor, so this
  is on the signup critical path.
