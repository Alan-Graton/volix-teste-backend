import os

ENV = os.environ.get('DJANGO_ENV', 'dev')

if ENV == 'prod':
    from .prod import *
else:
    from .dev import *