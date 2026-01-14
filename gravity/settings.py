import os
from typing import (
    Any,
    Dict,
    List,
    Union,
)

import jsonref
import yaml
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    ValidationInfo,
)
from pydantic_core import PydanticUseDefault
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)
from typing_extensions import Annotated

from gravity.util import StrEnum

DEFAULT_INSTANCE_NAME = "_default_"
GX_IT_PROXY_MIN_VERSION = "0.0.6"


def none_to_default(cls, value: Any) -> Any:
    if value is None:
        raise PydanticUseDefault()
    return value


class LogLevel(StrEnum):
    debug = "DEBUG"
    info = "INFO"
    warning = "WARNING"
    error = "ERROR"


class ProcessManager(StrEnum):
    supervisor = "supervisor"
    systemd = "systemd"
    multiprocessing = "multiprocessing"


class ServiceCommandStyle(StrEnum):
    gravity = "gravity"
    direct = "direct"
    exec = "_exec"


class AppServer(StrEnum):
    gunicorn = "gunicorn"


class Pool(StrEnum):
    prefork = "prefork"
    eventlet = "eventlet"
    gevent = "gevent"
    solo = "solo"
    processes = "processes"
    threads = "threads"


class TusdSettings(BaseModel):
    enable: Annotated[bool, Field(description="""
Enable tusd server.
If enabled, you also need to set up your proxy as outlined in https://docs.galaxyproject.org/en/latest/admin/nginx.html#receiving-files-via-the-tus-protocol.
""")] = False
    tusd_path: Annotated[str, Field(description="Path to tusd binary")] = "tusd"
    host: Annotated[str, Field(description="Host to bind the tusd server to")] = "localhost"
    port: Annotated[int, Field(description="Port to bind the tusd server to")] = 1080
    upload_dir: str = Field(description="""
Directory to store uploads in.
Must match ``tus_upload_store`` setting in ``galaxy:`` section.
""")
    hooks_http: Annotated[str, Field(description="""
Value of tusd -hooks-httpd option

the default of is suitable for using tusd for Galaxy uploads and should not be changed unless you are using tusd for
other purposes such as Pulsar staging.

The value of galaxy_infrastructure_url is automatically prepended if the option starts with a `/`
""")] = "/api/upload/hooks"
    hooks_enabled_events: Annotated[str, Field(description="""
Comma-separated string of enabled tusd hooks.

Leave at the default value to require authorization at upload creation time.
This means Galaxy's web process does not need to be running after creating the initial
upload request.

Set to empty string to disable all authorization. This means data can be uploaded (but not processed)
without the Galaxy web process being available.

You can find a list of available hooks at https://github.com/tus/tusd/blob/master/docs/hooks.md#list-of-available-hooks.
""")] = "pre-create"
    extra_args: Annotated[str, Field(description="Extra arguments to pass to tusd command line.")] = ""
    umask: Annotated[Union[str, None], Field(description="umask under which service should be executed")] = None
    start_timeout: Annotated[int, Field(description="Value of supervisor startsecs, systemd TimeoutStartSec")] = 10
    stop_timeout: Annotated[int, Field(description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")] = 10
    memory_limit: Annotated[Union[float, None], Field(
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")] = None
    memory_high: Annotated[Union[float, None], Field(
        description="""
Memory usage throttle limit (in GB). If the service exceeds the limit, processes are throttled and put under heavy
reclaim pressure. Default is no limit or the value of the ``memory_high`` setting at the top level of the Gravity
configuration, if set. Ignored if ``process_manager`` is ``supervisor``.
""")] = None
    environment: Annotated[Dict[str, str], Field(
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")] = {}


class CelerySettings(BaseModel):
    enable: Annotated[bool, Field(description="Enable Celery distributed task queue.")] = True
    enable_beat: Annotated[bool, Field(description="Enable Celery Beat periodic task runner.")] = True
    concurrency: Annotated[int, Field(ge=0, description="Number of Celery Workers to start.")] = 2
    loglevel: Annotated[LogLevel, Field(description="Log Level to use for Celery Worker.")] = LogLevel.debug
    queues: Annotated[str, Field(description="Queues to join")] = "celery,galaxy.internal,galaxy.external"
    pool: Annotated[Pool, Field(description="Pool implementation")] = Pool.threads
    extra_args: Annotated[str, Field(description="Extra arguments to pass to Celery command line.")] = ""
    umask: Annotated[Union[str, None], Field(description="umask under which service should be executed")] = None
    start_timeout: Annotated[int, Field(description="Value of supervisor startsecs, systemd TimeoutStartSec")] = 10
    stop_timeout: Annotated[int, Field(description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")] = 10
    memory_limit: Annotated[Union[float, None], Field(
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")] = None
    memory_high: Annotated[Union[float, None], Field(
        description="""
Memory usage throttle limit (in GB). If the service exceeds the limit, processes are throttled and put under heavy
reclaim pressure. Default is no limit or the value of the ``memory_high`` setting at the top level of the Gravity
configuration, if set. Ignored if ``process_manager`` is ``supervisor``.
""")] = None
    environment: Annotated[Dict[str, str], Field(
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")] = {}

    class Config:
        use_enum_values = True


class GunicornSettings(BaseModel):
    enable: Annotated[bool, Field(description="Enable Galaxy gunicorn server.")] = True
    bind: Annotated[str, Field(
        description="The socket to bind. A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``, ``fd://FD``. An IP is a valid HOST.",
    )] = "localhost:8080"
    workers: Annotated[int, Field(
        ge=1,
        description="""
Controls the number of Galaxy application processes Gunicorn will spawn.
Increased web performance can be attained by increasing this value.
If Gunicorn is the only application on the server, a good starting value is the number of CPUs * 2 + 1.
4-12 workers should be able to handle hundreds if not thousands of requests per second.
""")] = 1
    timeout: Annotated[int, Field(
        ge=0,
        description="""
Gunicorn workers silent for more than this many seconds are killed and restarted.
Value is a positive number or 0. Setting it to 0 has the effect of infinite timeouts by disabling timeouts for all workers entirely.
If you disable the ``preload`` option workers need to have finished booting within the timeout.
""")] = 300
    extra_args: Annotated[str, Field(description="Extra arguments to pass to Gunicorn command line.")] = ""
    preload: Annotated[Union[bool, None], Field(
        description="""
Use Gunicorn's --preload option to fork workers after loading the Galaxy Application.
Consumes less memory when multiple processes are configured.
""")] = True
    umask: Annotated[Union[str, None], Field(description="umask under which service should be executed")] = None
    start_timeout: Annotated[int, Field(description="Value of supervisor startsecs, systemd TimeoutStartSec")] = 15
    stop_timeout: Annotated[int, Field(description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")] = 65
    restart_timeout: Annotated[int, Field(
        description="""
Amount of time to wait for a server to become alive when performing rolling restarts.
""")] = 300
    memory_limit: Annotated[Union[float, None], Field(
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")] = None
    memory_high: Annotated[Union[float, None], Field(
        description="""
Memory usage throttle limit (in GB). If the service exceeds the limit, processes are throttled and put under heavy
reclaim pressure. Default is no limit or the value of the ``memory_high`` setting at the top level of the Gravity
configuration, if set. Ignored if ``process_manager`` is ``supervisor``.
""")] = None
    environment: Annotated[Dict[str, str], Field(
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")] = {}


class ReportsSettings(BaseModel):
    enable: Annotated[bool, Field(description="Enable Galaxy Reports server.")] = False
    config_file: Annotated[str, Field(description="Path to reports.yml, relative to galaxy.yml if not absolute")] = "reports.yml"
    bind: Annotated[str, Field(
        description="The socket to bind. A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``, ``fd://FD``. An IP is a valid HOST.",
    )] = "localhost:9001"
    workers: Annotated[int, Field(
        ge=1,
        description="""
Controls the number of Galaxy Reports application processes Gunicorn will spawn.
It is not generally necessary to increase this for the low-traffic Reports server.
""")] = 1
    timeout: Annotated[int, Field(
        ge=0,
        description="""
Gunicorn workers silent for more than this many seconds are killed and restarted.
Value is a positive number or 0. Setting it to 0 has the effect of infinite timeouts by disabling timeouts for all workers entirely.
""")] = 300
    url_prefix: Annotated[Union[str, None], Field(
        description="""
URL prefix to serve from.
The corresponding nginx configuration is (replace <url_prefix> and <bind> with the values from these options):

location /<url_prefix>/ {
    proxy_pass http://<bind>/;
}

If <bind> is a unix socket, you will need a ``:`` after the socket path but before the trailing slash like so:
    proxy_pass http://unix:/run/reports.sock:/;
""")] = None
    extra_args: Annotated[str, Field(description="Extra arguments to pass to Gunicorn command line.")] = ""
    umask: Annotated[Union[str, None], Field(description="umask under which service should be executed")] = None
    start_timeout: Annotated[int, Field(description="Value of supervisor startsecs, systemd TimeoutStartSec")] = 10
    stop_timeout: Annotated[int, Field(description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")] = 10
    memory_limit: Annotated[Union[float, None], Field(
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")] = None
    memory_high: Annotated[Union[float, None], Field(
        description="""
Memory usage throttle limit (in GB). If the service exceeds the limit, processes are throttled and put under heavy
reclaim pressure. Default is no limit or the value of the ``memory_high`` setting at the top level of the Gravity
configuration, if set. Ignored if ``process_manager`` is ``supervisor``.
""")] = None
    environment: Annotated[Dict[str, str], Field(
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")] = {}


class GxItProxySettings(BaseModel):
    enable: Annotated[bool, Field(description="Set to true to start gx-it-proxy")] = False
    version: Annotated[str, Field(description="gx-it-proxy version")] = f">={GX_IT_PROXY_MIN_VERSION}"
    ip: Annotated[str, Field(description="Public-facing IP of the proxy")] = "localhost"
    port: Annotated[int, Field(description="Public-facing port of the proxy")] = 4002
    sessions: Annotated[str, Field(
        description="""
Database to monitor.
Should be set to the same value as ``interactivetools_map`` (or ``interactivetoolsproxy_map``) in the ``galaxy:`` section. This is
ignored if either ``interactivetools_map`` or ``interactivetoolsproxy_map`` are set.
""")] = "database/interactivetools_map.sqlite"
    verbose: Annotated[bool, Field(description="Include verbose messages in gx-it-proxy")] = True
    forward_ip: Annotated[Union[str, None], Field(
        description="""
Forward all requests to IP.
This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
""")] = None
    forward_port: Annotated[Union[int, None], Field(
        description="""
Forward all requests to port.
This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.""")] = None
    reverse_proxy: Annotated[Union[bool, None], Field(
        description="""
Rewrite location blocks with proxy port.
This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
""")] = False
    umask: Annotated[Union[str, None], Field(description="umask under which service should be executed")] = None
    start_timeout: Annotated[int, Field(description="Value of supervisor startsecs, systemd TimeoutStartSec")] = 10
    stop_timeout: Annotated[int, Field(description="Value of supervisor stopwaitsecs, systemd TimeoutStopSec")] = 10
    memory_limit: Annotated[Union[float, None], Field(
        description="""
Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
``supervisor``.
""")] = None
    memory_high: Annotated[Union[float, None], Field(
        description="""
Memory usage throttle limit (in GB). If the service exceeds the limit, processes are throttled and put under heavy
reclaim pressure. Default is no limit or the value of the ``memory_high`` setting at the top level of the Gravity
configuration, if set. Ignored if ``process_manager`` is ``supervisor``.
""")] = None
    environment: Annotated[Dict[str, str], Field(
        description="""
Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
names.
""")] = {}


class Settings(BaseSettings):
    """
    Configuration for Gravity process manager.
    ``uwsgi:`` section will be ignored if Galaxy is started via Gravity commands (e.g ``./run.sh``, ``galaxy`` or ``galaxyctl``).
    """
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_nested_delimiter=".",
        env_prefix="gravity_",
        # Ignore extra fields so you can switch from gravity versions that recognize new fields
        # to an older version that does not specify the fields, without having to comment them out.
        extra="ignore",
        use_enum_values=True,
    )

    process_manager: Annotated[Union[ProcessManager, None], Field(
        description="""
Process manager to use.
``supervisor`` is the default process manager when Gravity is invoked as a non-root user.
``systemd`` is the default when Gravity is invoked as root.
``multiprocessing`` is the default when Gravity is invoked as the foreground shortcut ``galaxy`` instead of ``galaxyctl``
""")] = None

    service_command_style: Annotated[ServiceCommandStyle, Field(
        description="""
What command to write to the process manager configs
`gravity` (`galaxyctl exec <service-name>`) is the default
`direct` (each service's actual command) is also supported.
""")] = ServiceCommandStyle.gravity

    use_service_instances: Annotated[bool, Field(
        description="""
Use the process manager's *service instance* functionality for services that can run multiple instances.
Presently this includes services like gunicorn and Galaxy dynamic job handlers. Service instances are only supported if
``service_command_style`` is ``gravity``, and so this option is automatically set to ``false`` if
``service_command_style`` is set to ``direct``.
""")] = True

    umask: Annotated[str, Field(description="""
umask under which services should be executed. Setting ``umask`` on an individual service overrides this value.
""")] = "022"

    memory_limit: Annotated[Union[float, None], Field(
        description="""
Memory limit (in GB), processes exceeding the limit will be killed. Default is no limit. If set, this is default value
for all services. Setting ``memory_limit`` on an individual service overrides this value. Ignored if ``process_manager``
is ``supervisor``.
""")] = None
    memory_high: Annotated[Union[float, None], Field(
        description="""
Memory usage throttle limit (in GB), processes exceeding the limit are throttled and put under heavy reclaim pressure.
If set, this is the default value for all services. Setting ``memory_high`` on an individual service overrides this
value. Ignored if ``process_manager`` is ``supervisor``.
""")] = None

    galaxy_config_file: Annotated[Union[str, None], Field(
        description="""
Specify Galaxy config file (galaxy.yml), if the Gravity config is separate from the Galaxy config. Assumed to be the
same file as the Gravity config if a ``galaxy`` key exists at the root level, otherwise, this option is required.
""")] = None
    galaxy_root: Annotated[Union[str, None], Field(
        description="""
Specify Galaxy's root directory.
Gravity will attempt to find the root directory, but you can set the directory explicitly with this option.
""")] = None
    galaxy_user: Annotated[Union[str, None], Field(
        description="""
User to run Galaxy as, required when using the systemd process manager as root.
Ignored if ``process_manager`` is ``supervisor`` or user-mode (non-root) ``systemd``.
""")] = None
    galaxy_group: Annotated[Union[str, None], Field(
        description="""
Group to run Galaxy as, optional when using the systemd process manager as root.
Ignored if ``process_manager`` is ``supervisor`` or user-mode (non-root) ``systemd``.
""")] = None
    log_dir: Annotated[Union[str, None], Field(
        description="""
Set to a directory that should contain log files for the processes controlled by Gravity.
If not specified defaults to ``<galaxy_data_dir>/gravity/log``.
""")] = None
    log_namespace: Annotated[Union[str, None], Field(
        description="""
Run Galaxy processes in the specified journal namespace (sets the value of ``LogNamespace=`` in the systemd service
units). This allows you to keep Galaxy log messages separate in the system journal from other log messages. Ignored if
``process_manager`` is not ``systemd``. See ``systemd.exec(5)`` for details.
""")] = None
    virtualenv: Annotated[Union[str, None], Field(description="""
Set to Galaxy's virtualenv directory.
If not specified, Gravity assumes all processes are on PATH. This option is required in most circumstances when using
the ``systemd`` process manager.
""")] = None
    app_server: Annotated[AppServer, Field(
        description="""
Select the application server.
``gunicorn`` is the default application server.
""")] = AppServer.gunicorn
    instance_name: Annotated[str, Field(description="""Override the default instance name.
this is hidden from you when running a single instance.""")] = DEFAULT_INSTANCE_NAME
    gunicorn: Annotated[Union[List[GunicornSettings], GunicornSettings], Field(description="""
Configuration for Gunicorn. Can be a list to run multiple gunicorns for rolling restarts.
""")] = GunicornSettings()
    celery: Annotated[CelerySettings, Field(description="Configuration for Celery Processes.")] = CelerySettings()
    gx_it_proxy: Annotated[GxItProxySettings, Field(description="Configuration for gx-it-proxy.")] = GxItProxySettings()
    # The default value for tusd is a little awkward, but is a convenient way to ensure that if
    # a user enables tusd that they most also set upload_dir, and yet have the default be valid.
    tusd: Annotated[Union[List[TusdSettings], TusdSettings], Field(description="""
Configuration for tusd server (https://github.com/tus/tusd).
The ``tusd`` binary must be installed manually and made available on PATH (e.g in galaxy's .venv/bin directory).
""")] = TusdSettings(upload_dir="")
    reports: Annotated[ReportsSettings, Field(description="Configuration for Galaxy Reports.")] = ReportsSettings()
    handlers: Annotated[Dict[str, Dict[str, Any]], Field(
        description="""
Configure dynamic handlers in this section.
See https://docs.galaxyproject.org/en/latest/admin/scaling.html#dynamically-defined-handlers for details.
""")] = {}

    # Use field_validators to turn None to default value
    _normalize_gunicorn = field_validator("gunicorn", mode="before")(none_to_default)
    _normalize_gx_it_proxy = field_validator("gx_it_proxy", mode="before")(none_to_default)
    _normalize_celery = field_validator("celery", mode="before")(none_to_default)
    _normalize_tusd = field_validator("tusd", mode="before")(none_to_default)
    _normalize_reports = field_validator("reports", mode="before")(none_to_default)

    # automatically set process_manager to systemd if unset and running as root
    @field_validator("process_manager", mode="before")
    @classmethod
    def _process_manager_systemd_if_root(cls, value: Union[ProcessManager, None]) -> Union[ProcessManager, None]:
        if value is None:
            if os.geteuid() == 0:
                value = ProcessManager.systemd
        return value

    # Require galaxy_user if running as root
    @field_validator("galaxy_user", mode="after")
    @classmethod
    def _user_required_if_root(cls, value: Union[str, None], info: ValidationInfo) -> Union[str, None]:
        if os.geteuid() == 0:
            is_systemd = info.data["process_manager"] == ProcessManager.systemd
            if is_systemd and not value:
                raise ValueError("galaxy_user is required when running as root")
            elif not is_systemd:
                raise ValueError("Gravity cannot be run as root unless using the systemd process manager")
        return value

    # disable service instances unless command style is gravity
    @field_validator("use_service_instances", mode="after")
    @classmethod
    def _disable_service_instances_if_direct(cls, value: bool, info: ValidationInfo) -> bool:
        if info.data["service_command_style"] != ServiceCommandStyle.gravity:
            value = False
        return value


def process_property(key, value, depth=0):
    extra_white_space = "  " * depth
    default = value.get("default", "")
    if isinstance(default, dict):
        # Little hack that prevents listing the default value for tusd in the sample config
        default = {}
    if default != "":
        # make values more yaml-like.
        default = yaml.dump(default)
        if default.endswith("\n...\n"):
            default = default[: -(len("\n...\n"))]
        default = default.strip()
    description = "\n".join(f"{extra_white_space}# {desc}".rstrip() for desc in value["description"].strip().split("\n"))
    combined = value.get("allOf", [])
    if not combined and value.get("anyOf"):
        # we've got a union
        combined = [c for c in value["anyOf"] if c["type"] == "object"]
    if combined and combined[0].get("properties"):
        # we've got a nested map, add key once
        description = f"{description}\n{extra_white_space}{key}:\n"
    has_child = False
    for item in combined:
        if "enum" in item:
            enum_items = [i for i in item["enum"] if not i.startswith("_")]
            description = f'{description}\n{extra_white_space}# Valid options are: {", ".join(enum_items)}'
        if "properties" in item:
            has_child = True
            for _key, _value in item["properties"].items():
                description = f"{description}\n{process_property(_key, _value, depth=depth+1)}"
    if not has_child or key == "handlers":
        comment = "# "
        if key == "gravity":
            # gravity section should not be commented
            comment = ""
        if default == "":
            value_sep = ""
        else:
            value_sep = " "
        description = f"{description}\n{extra_white_space}{comment}{key}:{value_sep}{default}\n"
    return description


def settings_to_sample():
    schema = Settings.model_json_schema()
    # expand schema for easier processing
    data = jsonref.replace_refs(schema, merge_props=True)
    strings = [process_property("gravity", data)]
    for key, value in data["properties"].items():
        strings.append(process_property(key, value, 1))
    concat = "\n".join(strings)
    return concat
