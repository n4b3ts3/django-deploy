from datetime import datetime
from hashlib import md5
from pathlib import Path
from typing import Optional, TextIO
from django.core.management.base import BaseCommand, CommandError
from django.core.management.commands.check import Command as CheckCommand
from django.conf import settings
from django.apps import apps
from django.core import checks
import sys
import os

# Data of the service file
service_file = """
[Unit]
Description=Daemon for asgi server
Requires={0}_django_asgi.socket
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/{1}
ExecStart=/var/www/{1}/venv/bin/gunicorn --access-logfile {2} -k uvicorn.workers.UvicornWorker\
    --workers 3\
    --bind unix:/run/{0}_django_asgi.sock\
    {2}.asgi:application
[Install]
WantedBy=multi-user.target
"""
# Data of the socket file
socket_file = """
[Unit]
Description=Gunicorn Socket for {1} Web Server

[Socket]
ListenStream=/run/{0}_django_asgi.sock

[Install]
WantedBy=sockets.target
"""
# Data of the nginx configutation file
nginx_file = """
server {
	listen 80;
	listen [::]:80;
	#listen 443 ssl;
    #listen [::]:443 ssl;
	server_name {2};
	location = /favicon.ico { access_log off; log_not_found on; }
	location /static/ {
		root /var/www/{1};
	}
	location / {
		include proxy_params;
		proxy_pass http://unix:/run/{0}_django_asgi.sock;
	}
}
"""

config_file = {
    "database":{
        "username": None,
        "password": None,
        "host": None,
        "port": None,
    },
    "integrity": "",
    "date":"", 
}
class Command(BaseCommand):
    app_name = ""
    def __init__(self, stdout: Optional[TextIO] = ..., stderr: Optional[TextIO] = ..., no_color: bool = ..., force_color: bool = ...) -> None:
        self.app_name = settings.DEPLOY_NAME
        settings.DEPLOY_NAME = md5(str(settings.DEPLOY_NAME).lower().encode()).hexdigest()
        super().__init__()
    etc_path = "/etc/systemd/"
    nginx_path = "/etc/nginx/"
    help = "Deploy a django project to nginx using asgi"
    def check_deployment(self, args, options):
        self.stdout.write("Doing deployment checks... Please fix any issues before continuing...", style_func=self.style.SQL_TABLE, )
        if args:
            app_configs = [apps.get_app_config(app_label) for app_label in args]
        else:
            app_configs = None
        CheckCommand().check(
            app_configs=app_configs,
            tags=None,
            display_num_errors=True,
            include_deployment_checks=True,
            fail_level=getattr(checks, options["fail_level"]),
            databases=None,
        )
        if not options["yes"] and input("Do you want to continue? yes|no: ").lower() == "no":
            self.stdout.write("Quiting now")
            sys.exit(0)

    def check_permissions(self):
        if os.geteuid() == 0:
            self.stdout.write("Checking for systemd")
            if os.path.exists(self.etc_path):
                self.stdout.write("Systemd configuration path found...", style_func=self.style.SUCCESS)
                return True
        else:
            self.stderr.write("Please run as root")
            sys.exit(1)

    def add_arguments(self, parser):
        parser.allow_abbrev = True
        parser.add_argument('--nginx', action="store_true",
            help="Make deploy to nginx (DEFAULT)")
        parser.add_argument(
            "--fail-level",
            default="ERROR",
            choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
            help=(
                "Message level that will cause the command to exit with a "
                "non-zero status. Default is ERROR."
            ),
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Assume yes and run smoothly",
        )
        parser.add_argument(
            "--fresh",
            "-f",
            action="store_true",
            help="Delete previous existing file (This is like forcing so use with caution)",
        )
        parser.add_argument(
            "--host",
            "-H",
            default="{}.localhost".format(self.app_name),
            help="Host serving this production server (DEFAULT: {}.localhost)".format(self.app_name.lower()),
        )
        parser.add_argument(
            "--ssl",
            action="store_true",
            help="Deploy this project with ssl enabled",
        )

    def install_services(self, args, options):
        global service_file, socket_file, nginx_file
        service_file = service_file.format(settings.DEPLOY_NAME, self.app_name, options["name"] or settings.BASE_DIR.name, 
                options["log"] or "/tmp/" + settings.DEPLOY_NAME + "_django_asgi")
        socket_file = socket_file.format(settings.DEPLOY_NAME, settings.BASE_DIR.name)
        nginx_file = nginx_file.replace("{0}", settings.DEPLOY_NAME).replace("{1}", 
            self.app_name).replace("{2}", options["host"])
        path = "system/{0}_django_asgi"
        service_path = os.path.join(self.etc_path, path.format(settings.DEPLOY_NAME) + ".service")
        socket_path = os.path.join(self.etc_path, path.format(settings.DEPLOY_NAME) + ".socket")
        nginx_enabled_path = os.path.join(self.nginx_path, "sites-enabled", settings.DEPLOY_NAME + "_django_asgi")
        nginx_path = os.path.join(self.nginx_path, "sites-available", settings.DEPLOY_NAME + "_django_asgi")
        httpd_path = os.path.join("/var/www/", self.app_name)
        if os.path.exists(service_path) or os.path.exists(socket_path) or os.path.exists(nginx_path):
            if options["fresh"]:
                if os.path.exists(service_path):
                    os.remove(service_path)
                if os.path.exists(socket_path):
                    os.remove(socket_path)
                if os.path.exists(nginx_path):
                    os.remove(nginx_path)
                if os.path.exists(nginx_enabled_path):
                    os.remove(nginx_enabled_path)
            else:
                self.stderr.write("Service or Socket already exists please use a different name, current name: {}"
                    .format(settings.DEPLOY_NAME.lower()))
                self.stdout.write("path of service is: {}".format(service_path), style_func=self.style.WARNING)
                sys.exit(2)
        with open(service_path, "x") as service:
            service.write(service_file)
            self.stdout.write("Service was created successfully at path: " + service_path, style_func=self.style.SUCCESS)

        with open(socket_path, "x") as socket:
            socket.write(socket_file)
            self.stdout.write("Socket was created successfully at path: " + socket_path, style_func=self.style.SUCCESS)

        with open(nginx_path, "x") as nginx:
            nginx.write(nginx_file)
            with open(nginx_enabled_path, "x") as nginx_enabled:
                nginx_enabled.write(nginx_file)
            self.stdout.write("Nginx configuration file was created successfully at path: " + nginx_path, style_func=self.style.SUCCESS)
        if not os.system("systemctl daemon-reload") == 0:
            self.stderr.write("Something ocurred while loading the configurations files... \
                please report this at https://github.com/n4b3ts3/django-deploy")
            sys.exit(6)
        self.stdout.write("All configurations files were successfully created and loaded... now passing to action!!!", style_func=self.style.SUCCESS)
        
        if os.path.exists(httpd_path) and round(os.path.getsize(httpd_path)/10) == round(os.path.getsize(settings.BASE_DIR)/10):
            self.stdout.write("Project already exists skipping moving to /var/www/...", self.style.WARNING)
        elif os.system("cp -r {0} {1}".format(settings.BASE_DIR, httpd_path)) == 0:
            self.stdout.write("Project copied to {}".format(httpd_path), self.style.SUCCESS)
        else:
            self.stderr.write("Cannot successfully copy content of project into {}".format(httpd_path))
        self.stdout.write("Starting {0} with service name {1}_django_asgi".format(self.app_name, settings.DEPLOY_NAME))
        if os.system("systemctl start {}_django_asgi".format(settings.DEPLOY_NAME)) == 0:
            self.stdout.write("Django ASGI server service started, use 'systemctl stop {0}_django_asgi' for stop it"
                .format(settings.DEPLOY_NAME), 
                style_func=self.style.SUCCESS)
        else:
            self.stderr.write("Cannot successfully initiate the django asgi service try again later...")
            sys.exit(5)
        self.stdout.write("Restarting nginx")
        if os.system("nginx -t") == 0 and os.system("systemctl restart nginx") == 0: # Nginx is ready to use
            self.stdout.write("Nginx is now running ", style_func=self.style.SUCCESS)
        else:
            self.stderr.write("There are errors in nginx configurations files, this may be because some \
                incompatibility issues in the conf file, please report this in github \
                    https://github.com/n4b3ts3/django-deploy")
            sys.exit(3)
        self.stdout.write("All configurations are done and applied now launching browser for testing: ", self.style.SUCCESS)
        os.system("open http://localhost")

    def handle(self, *args, **options):
        self.check_deployment(args, options)
        self.check_permissions()
        self.install_services(args, options)
