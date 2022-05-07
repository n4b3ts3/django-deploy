[![StandWithUkraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/badges/StandWithUkraine.svg)](https://github.com/vshymanskyy/StandWithUkraine/blob/main/docs/README.md)
[![Stand With Ukraine](https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner2-direct.svg)](https://vshymanskyy.github.io/StandWithUkraine/)
# IMPORTANT
This package adds a new command to manage.py for your django project, it does requires root access for deployment and also requires you to have nginx and systemctl 
installed on your system. All this project is free and open source, you can see its code inside of https://github.com/n4b3ts3/django-deploy, DO NOT COPY THIS CODE 
FROM OTHERS SOURCES THAN PIP OR GITHUB IT MAY BE A MALWARE
# WARNINGS
When you runs this commands some warnings may appears, please do not ignore those warnings cause may means potentialy dangerous leaks in your django project 
# INSTALATION
pip3 install django-deploy-asgi
# USAGE
Make deployment and run it into your default browser if there is any ;)
* sudo path_to_venv/bin/python3 manage.py deploy 
Show help
* sudo path_to_venv/bin/python3 manage.py deploy -h 
# WHY ROOT?
We need sudo permissions in order to create a service in /etc/systemd/system so you can create a consistent service that you manually later will enable for persistency
We create files only in the nexts directories using md5 hashes of the DEPLOY_NAME set by the user in settings.py:
* /etc/systemd/system/*_django_asgi.service|socket
* /etc/nginx/sites-enabled/*_django_asgi

