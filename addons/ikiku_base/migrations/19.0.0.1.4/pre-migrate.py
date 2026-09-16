# Part of iKiKu. Licensed under AGPL-3.0.
"""The standard moves from noupdate XML to CSV files that load on every update.

The families and skills the XML created carry noupdate, which would keep the CSV from
writing their new kinds and names; they are released so the files decide.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data SET noupdate = false
         WHERE module = 'ikiku_base' AND model = 'ikiku.spec.node'
           AND name NOT IN ('spec_hygiene', 'spec_handwash', 'spec_coldchain', 'spec_crosscontam',
                            'spec_shift', 'spec_shift_morning', 'spec_shift_evening', 'spec_shift_night')
    """)
