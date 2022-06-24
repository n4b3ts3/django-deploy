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
wsgi_part = ""
asgi_part = "-k uvicorn.workers.UvicornWorker --workers 3"
asgi = "asgi"
wsgi = "wsgi"

service_file = """
[Unit]
Description=Daemon for {4} server
Requires={0}_django_{4}.socket
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/{1}
ExecStart=/var/www/{1}/venv/bin/gunicorn --access-logfile {3} {5} --bind unix:/run/{0}_django_{4}.sock {2}.{4}:application
[Install]
WantedBy=multi-user.target
"""
# Data of the socket file
socket_file = """
[Unit]
Description=Gunicorn Socket for {1} Web Server

[Socket]
ListenStream=/run/{0}_django_{2}.sock

[Install]
WantedBy=sockets.target
"""
# Data of the nginx configutation file
nginx_file = """
server {
	listen 80;
	listen [::]:80;
    #ssl listen 443 ssl;
    #ssl listen [::]:443 ssl;
    #ssl ssl_certificate /etc/letsencrypt/live/vpn.expresscuba.com/cert.pem;
	#ssl ssl_certificate_key /etc/letsencrypt/live/vpn.expresscuba.com/privkey.pem;
	server_name {2};
	location = /favicon.ico { access_log off; log_not_found on; }
	location /static/ {
		root /var/www/{1};
	}
    location /media/ {
		root /var/www/{1};
	}
	location / {
		include proxy_params;
		proxy_pass http://unix:/run/{0}_django_{3}.sock;
        client_max_body_size 10M;
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
    """
        This commands allows django programmers to quickly deploy a django app for asgi web servers
    """
    app_name = ""
    etc_path = "/etc/systemd/"
    nginx_path = "/etc/nginx/"
    help = "Deploy a django project to nginx using asgi"

    def __init__(self, stdout: Optional[TextIO] = ..., stderr: Optional[TextIO] = ..., no_color: bool = ..., force_color: bool = ...) -> None:
        assert hasattr(settings, "DEPLOY_NAME"), "Configuration exception, settings must have declared DEPLOY_NAME before using this command"
        self.app_name = settings.DEPLOY_NAME
        settings.DEPLOY_NAME = settings.DEPLOY_NAME.lower()
        super().__init__()

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
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Use symbolics links instead of really copying the file..",
        )
        parser.add_argument(
            "--wsgi",
            action="store_true",
            help="Use wsgi instead of asgi",
        )

    def install_services(self, args, options):
        global service_file, socket_file, nginx_file, wsgi, asgi, asgi_part, wsgi_part
        mode = wsgi if options.get("wsgi", False) else asgi
        service_file = service_file.format(settings.DEPLOY_NAME, self.app_name, 
            options.get("name", False) or settings.BASE_DIR.name, 
            options.get("log", None) or "/tmp/" + settings.DEPLOY_NAME + "_django_" + mode, 
            mode, wsgi_part if options.get("wsgi", False) else asgi_part)
        socket_file = socket_file.format(settings.DEPLOY_NAME, settings.BASE_DIR.name, mode)
        nginx_file = nginx_file.replace("{0}", settings.DEPLOY_NAME).replace("{1}", 
            self.app_name).replace("{2}", options["host"].lower()).replace("{3}", mode)
        path = "system/{0}_django_"+ mode
        service_path = os.path.join(self.etc_path, path.format(settings.DEPLOY_NAME) + ".service")
        socket_path = os.path.join(self.etc_path, path.format(settings.DEPLOY_NAME) + ".socket")
        nginx_enabled_path = os.path.join(self.nginx_path, "sites-enabled", settings.DEPLOY_NAME + "_django_" + mode)
        nginx_path = os.path.join(self.nginx_path, "sites-available", settings.DEPLOY_NAME + "_django_" + mode)
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
        
        # Now saving configuration files
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
        exists = os.path.exists(httpd_path) and round(os.path.getsize(httpd_path)/10) == round(os.path.getsize(settings.BASE_DIR)/10)
        if options.get("dry_run", False):
            if not exists:
                if os.system("ln -s {0} {1}".format(settings.BASE_DIR, httpd_path)) == 0:
                    self.stdout.write("Link created successfully...", self.style.SUCCESS)
                else:
                    raise CommandError("Cannot successfully create link at {}".format(httpd_path))
            else:
                self.stdout.write("Cannot use dry-run because path does exists, skipping instead...", self.style.WARNING)
        elif (options.get("fresh", False) or not exists ):
            if options.get("fresh", False) and exists:
                if os.path.islink(httpd_path) or os.path.isfile(httpd_path):
                    os.remove(httpd_path)
                elif os.path.isdir(httpd_path):
                    raise CommandError("{0} is not empty for security reasons and a little bit of paranoid please delete it manually".format(httpd_path))
                else:
                    raise CommandError("{0} is not either a file a link or a folder... please check this manually".format(httpd_path))
            os.system("cp -r {0} {1}".format(settings.BASE_DIR, httpd_path)) == 0
            self.stdout.write("Project copied to {}".format(httpd_path), self.style.SUCCESS)
        elif exists:
            self.stdout.write("Project already exists skipping moving to /var/www/...", self.style.WARNING)
        else:
            self.stderr.write("Cannot successfully copy content of project into {}".format(httpd_path))
        
        self.stdout.write("Starting {0} with service name {1}_django_{2}".format(self.app_name, settings.DEPLOY_NAME, mode))
        if os.system("systemctl start {0}_django_{1}".format(settings.DEPLOY_NAME, mode)) == 0:
            self.stdout.write("Django {1} server service started, use 'systemctl stop {0}_django_asgi' for stop it"
                .format(settings.DEPLOY_NAME, mode.upper()), 
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
