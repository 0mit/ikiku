{
    'name': "iKiKu — نیرو",
    'summary': "پروندهٔ نیروی حرفه‌ای: مهارت، سابقه و بازهٔ در دسترس بودن.",
    'author': "شرکت تعاونی ایکیکو",
    'website': "https://ikiku.ir",
    'category': 'Human Resources',
    'version': '19.0.0.1.1',
    'license': 'AGPL-3',
    # hr_skills is used ONLY for its skill catalogue and the individual-skill
    # mixin. No hr.employee is created for a resource: iKiKu is not their
    # employer -- the business they are placed with is.
    'depends': ['ikiku_base', 'hr_skills'],
    'data': [
        'security/ir.model.access.csv',
        'security/ikiku_supply_rules.xml',
        'data/ikiku_supply_data.xml',
        'views/ikiku_resource_views.xml',
        'views/ikiku_supply_menus.xml',
    ],
    'installable': True,
}
