web: python manage.py collectstatic --noinput && gunicorn runwithbroto.wsgi:application --log-file - --workers 3 --threads 2 --timeout 200
