import os
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)
from pydantic import BaseModel, BaseSettings, Extra, Field, validator

DEFAULT_INSTANCE_NAME = "_default_"
GX_IT_PROXY_MIN_VERSION = "0.0.6"


def none_to_default(cls, v, field):
    if all(
        (
            # Cater for the occasion where field.default in (0, False)
            getattr(field, "default", None) is not None,
            v is None,
        )
    ):
        return field.default
    else:
        return v


class LogLevel(str, Enum):
    debug = "DEBUG"
    info = "INFO"
    warning = "WARNING"
    error = "ERROR"


class ProcessManager(str, Enum):
    supervisor = "supervisor"
    systemd = "systemd"


class ServiceCommandStyle(str, Enum):
    gravity = "gravity"
    direct = "direct"
    exec = "_exec"


class AppServer(str, Enum):
    gunicorn = "gunicorn"
    unicornherder = "unicornherder"


class Pool(str, Enum):
    prefork = "prefork"
    eventlet = "eventlet"
    gevent = "gevent"
    solo = "solo"
    processes = "processes"
    threads = "threads"


class TusdSettings(BaseModel):
    enable: bool = Field(False, description="""
Enable tusd server.
If enabled, you also need to set up your proxy as outlined in https://docs.galaxyproject.org/en/latest/admin/nginx.html#receiving-files-via-the-tus-protocol.
""")
    tusd_path: str = Field(default="tusd", description="""Path to tusd binary""")
    host: str = Field("localhost", description="Host to bind the tusd server to")
    port: int = Field(1080, description="Port to bind the tusd server to")
    upload_dir: str = Field(description="""
Directory to store uploads in.
Must match ``tus_upload_store`` setting in ``galaxy:`` section.
""")
    hooks_enabled_events: str = Field(default="pre-create", description="""
Comma-separated string of enabled tusd hooks.

Leave at the default value to require authorization at upload creation time.
This means Galaxy's web process does not need to be running after creating the initial
upload request.

Set to empty string to disable all authorization. This means data can be uploaded (but not processed)
without the Galaxy web process being available.

You can find a list of available hooks at https://github.com/tus/tusd/blob/master/docs/hooks.md#list-of-available-hooks.
""")
    extra_args: str = Field(default="", description="Extra arguments to pass to tusd command line.")
    umask: Optional[str] = Field(None, description="umask under which service should be executed")
    start_timeout: int = Field(10, description="Value of supervisor startsecs, systemd TimeoutStartSec")
    stop_timeout: int = Field(10, description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")
    memory_limit: Optional[int] = Field(
        None,
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")
    environment: Dict[str, str] = Field(
        default={},
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")


class CelerySettings(BaseModel):
    enable: bool = Field(True, description="Enable Celery distributed task queue.")
    enable_beat: bool = Field(True, description="Enable Celery Beat periodic task runner.")
    concurrency: int = Field(2, ge=0, description="Number of Celery Workers to start.")
    loglevel: LogLevel = Field(LogLevel.debug, description="Log Level to use for Celery Worker.")
    queues: str = Field("celery,galaxy.internal,galaxy.external", description="Queues to join")
    pool: Pool = Field(Pool.threads, description="Pool implementation")
    extra_args: str = Field(default="", description="Extra arguments to pass to Celery command line.")
    umask: Optional[str] = Field(None, description="umask under which service should be executed")
    start_timeout: int = Field(10, description="Value of supervisor startsecs, systemd TimeoutStartSec")
    stop_timeout: int = Field(10, description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")
    memory_limit: Optional[int] = Field(
        None,
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")
    environment: Dict[str, str] = Field(
        default={},
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")

    class Config:
        use_enum_values = True


class GunicornSettings(BaseModel):
    enable: bool = Field(True, description="Enable Galaxy gunicorn server.")
    bind: str = Field(
        default="localhost:8080",
        description="The socket to bind. A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``, ``fd://FD``. An IP is a valid HOST.",
    )
    workers: int = Field(
        default=1,
        ge=1,
        description="""
Controls the number of Galaxy application processes Gunicorn will spawn.
Increased web performance can be attained by increasing this value.
If Gunicorn is the only application on the server, a good starting value is the number of CPUs * 2 + 1.
4-12 workers should be able to handle hundreds if not thousands of requests per second.
""")
    timeout: int = Field(
        default=300,
        ge=0,
        description="""
Gunicorn workers silent for more than this many seconds are killed and restarted.
Value is a positive number or 0. Setting it to 0 has the effect of infinite timeouts by disabling timeouts for all workers entirely.
If you disable the ``preload`` option workers need to have finished booting within the timeout.
""")
    extra_args: str = Field(default="", description="Extra arguments to pass to Gunicorn command line.")
    preload: Optional[bool] = Field(
        default=None,
        description="""
Use Gunicorn's --preload option to fork workers after loading the Galaxy Application.
Consumes less memory when multiple processes are configured. Default is ``false`` if using unicornherder, else ``true``.
""")
    umask: Optional[str] = Field(None, description="umask under which service should be executed")
    start_timeout: int = Field(15, description="Value of supervisor startsecs, systemd TimeoutStartSec")
    stop_timeout: int = Field(65, description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")
    restart_timeout: int = Field(
        default=300,
        description="""
Amount of time to wait for a server to become alive when performing rolling restarts.
""")
    memory_limit: Optional[int] = Field(
        None,
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")
    environment: Dict[str, str] = Field(
        default={},
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")


class ReportsSettings(BaseModel):
    enable: bool = Field(False, description="Enable Galaxy Reports server.")
    config_file: str = Field("reports.yml", description="Path to reports.yml, relative to galaxy.yml if not absolute")
    bind: str = Field(
        default="localhost:9001",
        description="The socket to bind. A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``, ``fd://FD``. An IP is a valid HOST.",
    )
    workers: int = Field(
        default=1,
        ge=1,
        description="""
Controls the number of Galaxy Reports application processes Gunicorn will spawn.
It is not generally necessary to increase this for the low-traffic Reports server.
""")
    timeout: int = Field(
        default=300,
        ge=0,
        description="""
Gunicorn workers silent for more than this many seconds are killed and restarted.
Value is a positive number or 0. Setting it to 0 has the effect of infinite timeouts by disabling timeouts for all workers entirely.
""")
    url_prefix: Optional[str] = Field(
        default=None,
        description="""
URL prefix to serve from.
The corresponding nginx configuration is (replace <url_prefix> and <bind> with the values from these options):

location /<url_prefix>/ {
    proxy_pass http://<bind>/;
}

If <bind> is a unix socket, you will need a ``:`` after the socket path but before the trailing slash like so:
    proxy_pass http://unix:/run/reports.sock:/;
""")
    extra_args: str = Field(default="", description="Extra arguments to pass to Gunicorn command line.")
    umask: Optional[str] = Field(None, description="umask under which service should be executed")
    start_timeout: int = Field(10, description="Value of supervisor startsecs, systemd TimeoutStartSec")
    stop_timeout: int = Field(10, description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")
    memory_limit: Optional[int] = Field(
        None,
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")
    environment: Dict[str, str] = Field(
        default={},
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")


class GxItProxySettings(BaseModel):
    enable: bool = Field(default=False, description="Set to true to start gx-it-proxy")
    version: str = Field(default=f">={GX_IT_PROXY_MIN_VERSION}", description="gx-it-proxy version")
    ip: str = Field(default="localhost", description="Public-facing IP of the proxy")
    port: int = Field(default=4002, description="Public-facing port of the proxy")
    sessions: str = Field(
        default="database/interactivetools_map.sqlite",
        description="""
Routes file to monitor.
Should be set to the same path as ``interactivetools_map`` in the ``galaxy:`` section. This is ignored if
``interactivetools_map is set``.
""")
    verbose: bool = Field(default=True, description="Include verbose messages in gx-it-proxy")
    forward_ip: Optional[str] = Field(
        default=None,
        description="""
Forward all requests to IP.
This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
""")
    forward_port: Optional[int] = Field(
        default=None,
        description="""
Forward all requests to port.
This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.""")
    reverse_proxy: Optional[bool] = Field(
        default=False,
        description="""
Rewrite location blocks with proxy port.
This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
""")
    umask: Optional[str] = Field(None, description="umask under which service should be executed")
    start_timeout: int = Field(10, description="Value of supervisor startsecs, systemd TimeoutStartSec")
    stop_timeout: int = Field(10, description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")
    memory_limit: Optional[int] = Field(
        None,
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")
    environment: Dict[str, str] = Field(
        default={},
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")


class Settings(BaseSettings):
    """
    Configuration for Gravity process manager.
    ``uwsgi:`` section will be ignored if Galaxy is started via Gravity commands (e.g ``./run.sh``, ``galaxy`` or ``galaxyctl``).
    """

    process_manager: ProcessManager = Field(
        None,
        description="""
Process manager to use.
``supervisor`` is the default process manager when Gravity is invoked as a non-root user.
``systemd`` is the default when Gravity is invoked as root.
""")

    service_command_style: ServiceCommandStyle = Field(
        ServiceCommandStyle.gravity,
        description="""
What command to write to the process manager configs
`gravity` (`galaxyctl exec <service-name>`) is the default
`direct` (each service's actual command) is also supported.
""")

    use_service_instances: bool = Field(
        True,
        description="""
Use the process manager's *service instance* functionality for services that can run multiple instances.
Presently this includes services like gunicorn and Galaxy dynamic job handlers. Service instances are only supported if
``service_command_style`` is ``gravity``, and so this option is automatically set to ``false`` if
``service_command_style`` is set to ``direct``.
""")

    umask: str = Field("022", description="""
umask under which services should be executed. Setting ``umask`` on an individual service overrides this value.
""")

    memory_limit: Optional[int] = Field(
        None,
        description="""
Memory limit (in GB), processes exceeding the limit will be killed. Default is no limit. If set, this is default value
for all services. Setting ``memory_limit`` on an individual service overrides this value. Ignored if ``process_manager``
is ``supervisor``.
""")

    galaxy_config_file: Optional[str] = Field(
        None,
        description="""
Specify Galaxy config file (galaxy.yml), if the Gravity config is separate from the Galaxy config. Assumed to be the
same file as the Gravity config if a ``galaxy`` key exists at the root level, otherwise, this option is required.
""")
    galaxy_root: Optional[str] = Field(
        None,
        description="""
Specify Galaxy's root directory.
Gravity will attempt to find the root directory, but you can set the directory explicitly with this option.
""")
    galaxy_user: Optional[str] = Field(
        None,
        description="""
User to run Galaxy as, required when using the systemd process manager as root.
Ignored if ``process_manager`` is ``supervisor`` or user-mode (non-root) ``systemd``.
""")
    galaxy_group: Optional[str] = Field(
        None,
        description="""
Group to run Galaxy as, optional when using the systemd process manager as root.
Ignored if ``process_manager`` is ``supervisor`` or user-mode (non-root) ``systemd``.
""")
    log_dir: Optional[str] = Field(
        None,
        description="""
Set to a directory that should contain log files for the processes controlled by Gravity.
If not specified defaults to ``<galaxy_data_dir>/gravity/log``.
""")
    virtualenv: Optional[str] = Field(None, description="""
Set to Galaxy's virtualenv directory.
If not specified, Gravity assumes all processes are on PATH. This option is required in most circumstances when using
the ``systemd`` process manager.
""")
    app_server: AppServer = Field(
        AppServer.gunicorn,
        description="""
Select the application server.
``gunicorn`` is the default application server.
``unicornherder`` is a production-oriented manager for (G)unicorn servers that automates zero-downtime Galaxy server restarts,
similar to uWSGI Zerg Mode used in the past.
""")
    instance_name: str = Field(default=DEFAULT_INSTANCE_NAME, description="""Override the default instance name.
this is hidden from you when running a single instance.""")
    gunicorn: Union[List[GunicornSettings], GunicornSettings] = Field(default={}, description="""
Configuration for Gunicorn. Can be a list to run multiple gunicorns for rolling restarts.
""")
    celery: CelerySettings = Field(default={}, description="Configuration for Celery Processes.")
    gx_it_proxy: GxItProxySettings = Field(default={}, description="Configuration for gx-it-proxy.")
    # The default value for tusd is a little awkward, but is a convenient way to ensure that if
    # a user enables tusd that they most also set upload_dir, and yet have the default be valid.
    tusd: TusdSettings = Field(default={'upload_dir': ''}, description="""
Configuration for tusd server (https://github.com/tus/tusd).
The ``tusd`` binary must be installed manually and made available on PATH (e.g in galaxy's .venv/bin directory).
""")
    reports: ReportsSettings = Field(default={}, description="Configuration for Galaxy Reports.")
    handlers: Dict[str, Dict[str, Any]] = Field(
        default={},
        description="""
Configure dynamic handlers in this section.
See https://docs.galaxyproject.org/en/latest/admin/scaling.html#dynamically-defined-handlers for details.
""")

    # Use validators to turn None to default value
    _normalize_gunicorn = validator("gunicorn", allow_reuse=True, pre=True)(none_to_default)
    _normalize_gx_it_proxy = validator("gx_it_proxy", allow_reuse=True, pre=True)(none_to_default)
    _normalize_celery = validator("celery", allow_reuse=True, pre=True)(none_to_default)
    _normalize_tusd = validator("tusd", allow_reuse=True, pre=True)(none_to_default)
    _normalize_reports = validator("reports", allow_reuse=True, pre=True)(none_to_default)

    # Require galaxy_user if running as root
    @validator("galaxy_user")
    def _user_required_if_root(cls, v, values):
        if os.geteuid() == 0:
            is_systemd = values["process_manager"] == ProcessManager.systemd
            if is_systemd and not v:
                raise ValueError("galaxy_user is required when running as root")
            elif not is_systemd:
                raise ValueError("Gravity cannot be run as root unless using the systemd process manager")
        return v

    # automatically set process_manager to systemd if unset and running is root
    @validator("process_manager")
    def _process_manager_systemd_if_root(cls, v, values):
        if v is None:
            if os.geteuid() == 0:
                v = ProcessManager.systemd.value
            else:
                v = ProcessManager.supervisor.value
        return v

    # disable service instances unless command style is gravity
    @validator("use_service_instances")
    def _disable_service_instances_if_direct(cls, v, values):
        if values["service_command_style"] != ServiceCommandStyle.gravity:
            v = False
        return v

    class Config:
        env_prefix = "gravity_"
        env_nested_delimiter = "."
        case_sensitive = False
        use_enum_values = True
        # Ignore extra fields so you can switch from gravity versions that recognize new fields
        # to an older version that does not specify the fields, without having to comment them out.
        extra = Extra.ignore
