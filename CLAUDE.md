# Working in this repository

## Commit convention

**No agent attribution in commit messages.** No `Co-Authored-By:` naming an AI,
no `Claude-Session:`, no "Generated with Claude Code", no 🤖. This is enforced by
`tools/hooks/commit-msg`, not left to memory — run `sh tools/install-hooks.sh`
after cloning, because `.git/hooks` is not cloned and a fresh clone has no gate.

A human co-author is legitimate and passes the hook.

Message shape follows the daftar convention: `<id>: <what> (<why>)`, one logical
change per commit, and the *why* is the half that is worth writing — the *what*
is in the diff already.

## What must not drift

- **Dates are stored Gregorian/UTC and converted at the boundary.** A Jalali
  string in a column is a bug. `ikiku_base/models/jalali.py` is vendored so a
  filtered network cannot break a build; it is verified against known dates.
- **Visibility is data, and fails closed.** `ikiku.visibility.policy` decides
  what the public sees. A field with no row is restricted. Never special-case a
  field in a template or serializer — add a row, with its reason.
- **The ranking stays readable.** Weights are module constants in
  `ikiku_match/models/ikiku_proposal.py`, every component is stored on the
  proposal, and the explanation is built from the same numbers as the total.
  Article 8 of the مرام‌نامه forbids a hidden formula, which forecloses a learned
  ranker until that article changes.
- **iKiKu is not an employer.** Resources are employed by the businesses they
  are placed with. Do not create `hr.employee` records for them and do not reach
  for `hr.resume.line`, whose `employee_id` is required on `hr.employee`.
- **LGPL-3 dependencies only.** Planning, Helpdesk, Appointment, Sign and
  Documents are `OEEL-1`. Check `__manifest__.py` `license` before depending on
  any Odoo module.

## Before committing

    python3 tools/validate.py     # must print 0 error(s)

It is a static check, not an install: it verifies manifests, ACLs, view fields
and model coverage. It cannot replace booting Odoo, and says so.

## The law

`docs/MANIFEST.fa.md` is the مرام‌نامه and it is binding on this code. Several of
its articles are enforced in code rather than described — see the list above and
the module docstrings. Changing one of those behaviours is a change to the law,
not a refactor: raise it, do not enact it.
