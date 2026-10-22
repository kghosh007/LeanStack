#!/usr/bin/env python3
"""Apply one tuning document to Valkey, MariaDB, Angie, and PHP."""

import argparse
import json
import os
import shutil
import subprocess
import sys

try:
    from installer.probe import HardwareProbe, TuningCalculator
except ImportError:
    from probe import HardwareProbe, TuningCalculator


def _load_profile(args):
    if args.profile:
        raw = sys.stdin.read() if args.profile == "-" else open(args.profile, encoding="utf-8").read()
        return json.loads(raw)
    probe = HardwareProbe(sim_ram_mb=args.simulate_ram, sim_cores=args.simulate_cores)
    hw = probe.probe_all()
    if args.simulate_avx2 is not None:
        hw["cpu"]["features"]["avx2"] = bool(args.simulate_avx2)
        if args.simulate_avx2 == 0:
            hw["cpu"]["features"]["sse4_2"] = False
            hw["cpu"]["features"]["neon"] = False
    return TuningCalculator(hw).to_document()


def _php_versions(values):
    versions = values or ["8.5"]
    cleaned = []
    for ver in versions:
        if ver not in cleaned:
            cleaned.append(ver)
    return cleaned


def _sysctl(profile):
    ram = profile["hardware"]["ram"]["total_mb"]
    kernel = profile["kernel"]
    if ram <= 2048:
        rmem = 4194304
    elif ram <= 4096:
        rmem = 8388608
    else:
        rmem = 16777216
    return f"""# File & Socket Limits
fs.file-max = {kernel["file_max"]}
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024

# Network Backlog & Fast Connection Recycling
net.core.somaxconn = {kernel["somaxconn"]}
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = {kernel["tcp_max_syn_backlog"]}
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# TCP Fast Open (3 = Client & Server enabled)
net.ipv4.tcp_fastopen = {kernel["tcp_fastopen"]}

# Buffer memory scaling for 10Gbps / Cloud VPS networks
net.core.rmem_default = 262144
net.core.rmem_max = {rmem}
net.core.wmem_default = 262144
net.core.wmem_max = {rmem}
net.ipv4.tcp_rmem = 4096 87380 {rmem}
net.ipv4.tcp_wmem = 4096 65536 {rmem}

# TCP Congestion Control: BBR
net.core.default_qdisc = {kernel["default_qdisc"]}
net.ipv4.tcp_congestion_control = {kernel["tcp_congestion_control"]}

# Memory & I/O management
vm.swappiness = {kernel["swappiness"]}
vm.dirty_ratio = {kernel["dirty_ratio"]}
vm.dirty_background_ratio = {kernel["dirty_background_ratio"]}
vm.vfs_cache_pressure = 50
vm.overcommit_memory = 1
"""


def _valkey_conf(profile):
    valkey = profile["valkey"]
    return f"""# LeanStack Valkey. Values come from the tuning document.
port {valkey["port"]}
unixsocket {valkey["unixsocket"]}
unixsocketperm {valkey["unixsocketperm"]}
daemonize no
supervised systemd
pidfile /run/valkey/valkey.pid
loglevel notice
logfile /var/log/valkey/valkey.log
databases 128
aclfile /etc/valkey/users.acl
rename-command FLUSHALL ""
maxmemory {valkey["maxmemory"]}
maxmemory-policy {valkey["maxmemory_policy"]}
save ""
stop-writes-on-bgsave-error no
rdbcompression no
appendonly no
jemalloc-bg-thread yes
tcp-backlog {valkey["tcp_backlog"]}
timeout 0
tcp-keepalive 0
"""


def _mariadb_cnf(profile):
    db = profile["mariadb"]
    if db["transaction_isolation"] != "READ-COMMITTED":
        raise ValueError("MariaDB profile must stay READ-COMMITTED")
    body = f"""[mysqld]
# LeanStack MariaDB High-QPS profile from the tuning document.
bind-address                   = 127.0.0.1
local-infile                   = 0
thread_handling                = one-thread-per-connection
thread_cache_size              = {db["thread_cache_size"]}
max_connections                = {db["max_connections"]}
back_log                       = {db["back_log"]}
performance_schema             = {db["performance_schema"]}
skip-log-bin
skip-name-resolve              = {db["skip_name_resolve"]}
query_cache_type               = {db["query_cache_type"]}
query_cache_size               = {db["query_cache_size"]}
transaction_isolation          = READ-COMMITTED
innodb_buffer_pool_size        = {db["innodb_buffer_pool_size"]}
innodb_buffer_pool_dump_at_shutdown = ON
innodb_buffer_pool_load_at_startup  = ON
innodb_log_file_size           = {db["innodb_log_file_size"]}
innodb_log_buffer_size         = {db["innodb_log_buffer_size"]}
innodb_flush_log_at_trx_commit = {db["innodb_flush_log_at_trx_commit"]}
innodb_autoinc_lock_mode       = 2
innodb_adaptive_hash_index     = {db["innodb_adaptive_hash_index"]}
innodb_io_capacity             = {db["innodb_io_capacity"]}
innodb_io_capacity_max         = {db["innodb_io_capacity_max"]}
innodb_read_io_threads         = {db["innodb_read_io_threads"]}
innodb_write_io_threads        = {db["innodb_write_io_threads"]}
innodb_flush_neighbors         = {db["innodb_flush_neighbors"]}
sort_buffer_size               = {db["sort_buffer_size"]}
join_buffer_size               = {db["join_buffer_size"]}
read_buffer_size               = {db["read_buffer_size"]}
read_rnd_buffer_size           = {db["read_rnd_buffer_size"]}
optimizer_switch               = {db["optimizer_switch"]}
tmp_table_size                 = {db["tmp_table_size"]}
max_heap_table_size            = {db["max_heap_table_size"]}
aria_pagecache_buffer_size     = {db["aria_pagecache_buffer_size"]}
aria_sort_buffer_size          = {db["aria_sort_buffer_size"]}
table_open_cache               = {db["table_open_cache"]}
table_open_cache_instances     = {db["table_open_cache_instances"]}
table_definition_cache         = 2048
character-set-server           = utf8mb4
collation-server               = utf8mb4_unicode_520_ci

[mariadb]
innodb_buffer_pool_size        = {db["innodb_buffer_pool_size"]}
innodb_buffer_pool_dump_at_shutdown = ON
innodb_buffer_pool_load_at_startup  = ON
transaction_isolation          = READ-COMMITTED
innodb_flush_log_at_trx_commit = {db["innodb_flush_log_at_trx_commit"]}
performance_schema             = {db["performance_schema"]}
skip-log-bin
skip-name-resolve              = {db["skip_name_resolve"]}
query_cache_type               = {db["query_cache_type"]}
query_cache_size               = {db["query_cache_size"]}
optimizer_switch               = {db["optimizer_switch"]}
tmp_table_size                 = {db["tmp_table_size"]}
max_heap_table_size            = {db["max_heap_table_size"]}
aria_pagecache_buffer_size     = {db["aria_pagecache_buffer_size"]}
aria_sort_buffer_size          = {db["aria_sort_buffer_size"]}
sort_buffer_size               = {db["sort_buffer_size"]}
join_buffer_size               = {db["join_buffer_size"]}
read_buffer_size               = {db["read_buffer_size"]}
read_rnd_buffer_size           = {db["read_rnd_buffer_size"]}
max_connections                = {db["max_connections"]}
table_open_cache               = {db["table_open_cache"]}
table_open_cache_instances     = {db["table_open_cache_instances"]}
table_definition_cache         = 2048
innodb_io_capacity             = {db["innodb_io_capacity"]}
innodb_io_capacity_max         = {db["innodb_io_capacity_max"]}
innodb_read_io_threads         = {db["innodb_read_io_threads"]}
innodb_write_io_threads        = {db["innodb_write_io_threads"]}
innodb_flush_neighbors         = {db["innodb_flush_neighbors"]}
"""
    return body


def _angie_conf(profile):
    angie = profile["angie"]
    return f"""user www-data;
pid /run/angie.pid;
worker_processes {angie["worker_processes"]};
worker_cpu_affinity {angie["worker_cpu_affinity"]};
worker_rlimit_nofile {angie["worker_rlimit_nofile"]};

include /etc/angie/modules.d/*.conf;

events {{
    worker_connections {angie["worker_connections"]};
    multi_accept on;
    use epoll;
}}

http {{
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;

    include /etc/angie/mime.types;
    default_type application/octet-stream;

    access_log /var/log/angie/access.log combined buffer=64k flush=5m;
    error_log /var/log/angie/error.log warn;

    fastcgi_cache_path /var/cache/angie/fastcgi levels=1:2 keys_zone=WORDPRESS:100m inactive=60m max_size={angie["fastcgi_cache_max_size"]};
    fastcgi_cache_key "$scheme$request_method$host$request_uri";
    fastcgi_cache_use_stale error timeout updating invalid_header http_500 http_503;
    fastcgi_ignore_headers Cache-Control Expires Set-Cookie;

    limit_req_zone $binary_remote_addr zone=perip:20m rate=20r/s;
    limit_req_zone $server_name zone=persite:20m rate=150r/s;
    limit_req_zone $binary_remote_addr zone=wplogin:10m rate=2r/s;
    limit_req_status 429;

    client_max_body_size 128M;
    client_body_buffer_size 128k;

    include /etc/angie/snippets/brotli.conf*;

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript application/wasm;

    map $http_cf_visitor $cf_proto_https {{
        default 0;
        '~*"scheme":"https"' 1;
    }}

    map $http_x_forwarded_proto $x_forwarded_https {{
        default 0;
        'https' 1;
    }}

    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_session_tickets off;
    ssl_session_ticket_key /etc/angie/tls_session_ticket.key;

    ssl_protocols {angie["ssl_protocols"]};
    ssl_ciphers {angie["ssl_ciphers"]};
    ssl_prefer_server_ciphers on;

    ssl_ecdh_curve {angie["pqc_curve"]};

    http2 on;
    quic_gso on;
    quic_retry on;

    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    include /etc/angie/snippets/cloudflare-realip.conf;
    include /etc/angie/cache-zones/*.conf;

    server {{
        listen 80 default_server;
        listen [::]:80 default_server;
        listen 443 ssl default_server reuseport;
        listen [::]:443 ssl default_server reuseport;
        listen 443 quic default_server reuseport;
        listen [::]:443 quic default_server reuseport;
        server_name _;

        ssl_certificate /etc/angie/ssl/default.crt;
        ssl_certificate_key /etc/angie/ssl/default.key;

        return 444;
    }}

    include /etc/angie/http.d/*.conf;
}}
"""


def _opcache_ini(profile):
    php = profile["php"]
    return f"""; LeanStack OPcache and JIT from the tuning document.
opcache.enable = 1
opcache.enable_cli = 0
opcache.memory_consumption = {php["opcache_memory_consumption"]}
opcache.interned_strings_buffer = {php["opcache_interned_strings_buffer"]}
opcache.max_accelerated_files = {php["opcache_max_accelerated_files"]}
opcache.revalidate_freq = 60
opcache.validate_timestamps = 1
opcache.save_comments = 1
opcache.fast_shutdown = 1
opcache.validate_permission = 1
opcache.validate_root = 1
opcache.jit = {php["opcache_jit"]}
opcache.jit_buffer_size = {php["opcache_jit_buffer_size"]}
opcache.jit_max_root_traces = 5000
opcache.jit_max_side_traces = 5000
opcache.jit_hot_loop = 1
"""


def _php_runtime_ini():
    return """expose_php = Off
memory_limit = 256M
upload_max_filesize = 128M
post_max_size = 128M
max_execution_time = 300
max_input_vars = 5000
date.timezone = UTC
session.use_strict_mode = 1
session.cookie_httponly = 1
session.cookie_secure = 1
session.cookie_samesite = Lax
disable_functions = exec,passthru,shell_exec,system,proc_open,popen,dl,show_source,opcache_reset,opcache_flush,apcu_clear_cache,apc_clear_cache
"""


def _system_pool(ver):
    return f"""[system]
user = www-data
group = www-data
listen = /run/php/php{ver}-fpm-system.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
pm = ondemand
pm.max_children = 2
pm.process_idle_timeout = 10s
"""


def _whitelists():
    return """name: leanstack/whitelists
description: "LeanStack Trusted Whitelist (SSH Session, Local Subnets, Cloudflare)"
filter: "evt.Meta.service == 'sshd' || evt.Meta.service == 'http'"
whitelist:
  reason: "LeanStack Administrator and Infrastructure Protection"
  ip:
    - "127.0.0.1"
    - "::1"
  cidr:
    - "10.0.0.0/8"
    - "172.16.0.0/12"
    - "192.168.0.0/16"
"""


def render_files(profile, php_versions):
    """Return relative path to file body for one profile and the selected PHP versions."""
    kernel = profile["kernel"]
    angie = profile["angie"]
    files = {
        "etc/sysctl.d/99-leanstack.conf": _sysctl(profile),
        "etc/security/limits.d/99-leanstack.conf": (
            "* soft nofile 65535\n* hard nofile 65535\n"
            "root soft nofile 65535\nroot hard nofile 65535\n"
            "www-data soft nofile 65535\nwww-data hard nofile 65535\n"
        ),
        "etc/apt/preferences.d/nosnap.pref": "Package: snapd\nPin: release *\nPin-Priority: -10\n",
        "etc/apt/apt.conf.d/20auto-upgrades": (
            'APT::Periodic::Update-Package-Lists "1";\n'
            'APT::Periodic::Unattended-Upgrade "1";\n'
        ),
        "etc/apt/apt.conf.d/50unattended-upgrades": (
            "Unattended-Upgrade::Allowed-Origins {\n"
            '    "${distro_id}:${distro_codename}-security";\n'
            "};\n"
            "Unattended-Upgrade::Package-Blacklist {\n"
            "};\n"
            'Unattended-Upgrade::Automatic-Reboot "false";\n'
        ),
        "etc/systemd/system/disable-thp.service": (
            "[Unit]\n"
            "Description=Disable Transparent Huge Pages (THP) for MariaDB & Valkey Performance\n"
            "DefaultDependencies=no\n"
            "After=sysinit.target local-fs.target\n"
            "Before=mongod.service mariadb.service mysql.service valkey.service\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled "
            "&& echo never > /sys/kernel/mm/transparent_hugepage/defrag'\n\n"
            "[Install]\n"
            "WantedBy=basic.target\n"
        ),
        "etc/default/zramswap": (
            f"ALGO={kernel['zram_comp_algo']}\nPERCENT=50\nPRIORITY=100\n"
        ),
        "etc/systemd/journald.conf.d/99-limit.conf": (
            "[Journal]\nSystemMaxUse=100M\nRuntimeMaxUse=50M\n"
        ),
        "etc/valkey/valkey.conf": _valkey_conf(profile),
        "etc/valkey/users.acl": "user default on nopass ~* &* +@all\n",
        "etc/systemd/system/valkey.service": (
            "[Unit]\n"
            "Description=Valkey High-Performance In-Memory Data Store\n"
            "After=network.target disable-thp.service\n\n"
            "[Service]\n"
            "Type=notify\n"
            "User=valkey\n"
            "Group=valkey\n"
            "SupplementaryGroups=tenants\n"
            "ExecStart=/usr/bin/valkey-server /etc/valkey/valkey.conf\n"
            "ExecStop=/bin/kill -s TERM $MAINPID\n"
            "Restart=always\n"
            "RestartSec=3\n"
            "LimitNOFILE=65535\n"
            "RuntimeDirectory=valkey\n"
            "RuntimeDirectoryMode=0775\n"
            "UMask=007\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
            "Alias=valkey-server.service\n"
        ),
        "etc/mysql/mariadb.conf.d/99-leanstack-highqps.cnf": _mariadb_cnf(profile),
        "etc/mysql/conf.d/99-leanstack-highqps.cnf": _mariadb_cnf(profile),
        "etc/angie/angie.conf": _angie_conf(profile),
        "etc/angie/snippets/brotli.conf": (
            "brotli on;\n"
            f"brotli_comp_level {angie['brotli_comp_level']};\n"
            "brotli_static on;\n"
            "brotli_types text/plain text/css application/javascript application/json "
            "application/xml image/svg+xml application/wasm;\n"
        ),
        "etc/angie/modules.d/cache-purge.conf": "load_module modules/ngx_http_cache_purge_module.so;\n",
        "etc/crowdsec/parsers/s02-enrich/whitelists.yaml": _whitelists(),
    }
    for ver in php_versions:
        base = f"etc/php/{ver}"
        files[f"{base}/fpm/conf.d/99-leanstack-opcache.ini"] = _opcache_ini(profile)
        files[f"{base}/cli/conf.d/99-leanstack-opcache.ini"] = _opcache_ini(profile)
        files[f"{base}/fpm/conf.d/98-leanstack-runtime.ini"] = _php_runtime_ini()
        files[f"{base}/cli/conf.d/98-leanstack-runtime.ini"] = _php_runtime_ini()
        files[f"{base}/fpm/pool.d/system.conf"] = _system_pool(ver)
    return files


def dry_run_lines(php_versions, files):
    lines = [f"php{ver}" for ver in php_versions]
    lines.extend(sorted(files))
    return lines


def write_files(root, files):
    for rel, content in sorted(files.items()):
        dest = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as handle:
            handle.write(content)
        if rel.endswith("users.acl") or rel.endswith("valkey.conf"):
            os.chmod(dest, 0o640)


def _run(cmd):
    subprocess.run(cmd, check=False)


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def heal_grubenv():
    """Recreate a missing grubenv so grub2-common.service can leave the failed state."""
    unit_present = (
        os.path.exists("/usr/lib/systemd/system/grub2-common.service")
        or os.path.exists("/lib/systemd/system/grub2-common.service")
    )
    if not unit_present:
        return
    os.makedirs("/boot/grub", exist_ok=True)
    if shutil.which("grub-editenv") and not os.path.exists("/boot/grub/grubenv"):
        _run(["grub-editenv", "/boot/grub/grubenv", "create"])
        _run(["grub-editenv", "/boot/grub/grubenv", "unset", "recordfail"])
    _run(["systemctl", "reset-failed", "grub2-common.service"])


def _module_present(names):
    return any(os.path.exists(path) for path in names)


def adjust_angie_modules(root):
    """Drop module loaders whose shared objects are absent. Fall back the PQC curve when OpenSSL lacks it."""
    purge_so = _module_present([
        "/usr/lib/angie/modules/ngx_http_cache_purge_module.so",
        "/etc/angie/modules/ngx_http_cache_purge_module.so",
    ])
    purge_conf = os.path.join(root, "etc/angie/modules.d/cache-purge.conf")
    if not purge_so and os.path.exists(purge_conf):
        os.remove(purge_conf)
    brotli_so = "/usr/lib/angie/modules/ngx_http_brotli_filter_module.so"
    if not os.path.exists(brotli_so):
        for rel in ("etc/angie/modules.d/brotli.conf", "etc/angie/snippets/brotli.conf"):
            path = os.path.join(root, rel)
            if os.path.exists(path):
                os.remove(path)
    angie_conf = os.path.join(root, "etc/angie/angie.conf")
    if not os.path.exists(angie_conf):
        return
    with open(angie_conf, encoding="utf-8") as handle:
        text = handle.read()
    fallback = "ssl_ecdh_curve x25519:prime256v1:secp384r1;"
    primary = "ssl_ecdh_curve X25519MLKEM768:x25519:prime256v1:secp384r1;"
    probe = subprocess.run(
        ["openssl", "list", "-kem-algorithms"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if "ML-KEM-768" not in probe.stdout and "X25519MLKEM768" not in probe.stdout:
        text = text.replace(primary, fallback)
        with open(angie_conf, "w", encoding="utf-8") as handle:
            handle.write(text)


def install_packages(php_versions):
    """Install host packages. Runs only when applying onto / as root."""
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    base = [
        "curl", "ca-certificates", "gnupg", "lsb-release", "sqlite3", "git",
        "msmtp", "msmtp-mta", "mysqltuner", "zram-tools", "cpufrequtils",
        "htop", "iotop", "iftop", "net-tools", "unattended-upgrades",
    ]
    _run(["apt-get", "update", "-qq"])
    subprocess.run(["apt-get", "install", "-y", "-qq", *base], env=env, check=False)
    if not shutil.which("valkey-server") and not shutil.which("redis-server"):
        subprocess.run(["apt-get", "install", "-y", "-qq", "valkey-server", "valkey-tools"], env=env, check=False)
    if not shutil.which("mariadb"):
        subprocess.run(["apt-get", "install", "-y", "-qq", "mariadb-server", "mariadb-client"], env=env, check=False)
    if not shutil.which("angie"):
        subprocess.run(
            ["apt-get", "install", "-y", "-qq", "angie", "angie-module-brotli", "angie-module-cache-purge"],
            env=env,
            check=False,
        )
    for ver in php_versions:
        pkgs = [f"php{ver}-fpm", f"php{ver}-mysql", f"php{ver}-curl", f"php{ver}-mbstring", f"php{ver}-xml", f"php{ver}-zip"]
        subprocess.run(["apt-get", "install", "-y", "-qq", *pkgs, "msmtp", "msmtp-mta"], env=env, check=False)
    if not shutil.which("wp"):
        dest = "/usr/local/bin/wp"
        subprocess.run(
            ["curl", "-fsSL", "--connect-timeout", "10", "--retry", "3",
             "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar",
             "-o", dest],
            check=False,
        )
        if os.path.exists(dest):
            os.chmod(dest, 0o755)


def host_services(php_versions):
    _run(["sysctl", "--system"])
    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", "--now", "disable-thp.service"])
    heal_grubenv()
    _run(["systemctl", "enable", "valkey.service"])
    _run(["systemctl", "restart", "valkey.service"])
    _run(["systemctl", "restart", "mariadb"])
    snippets = os.path.join(_repo_root(), "core", "snippets")
    if os.path.isdir(snippets):
        os.makedirs("/etc/angie/snippets", exist_ok=True)
        for name in os.listdir(snippets):
            if name.endswith(".conf"):
                shutil.copy2(os.path.join(snippets, name), os.path.join("/etc/angie/snippets", name))
    adjust_angie_modules("/")
    if shutil.which("angie"):
        _run(["angie", "-t"])
        _run(["systemctl", "enable", "angie"])
        _run(["systemctl", "restart", "angie"])
    for ver in php_versions:
        _run(["systemctl", "enable", f"php{ver}-fpm"])
        _run(["systemctl", "restart", f"php{ver}-fpm"])


def apply_document(profile, php_versions, root, dry_run):
    files = render_files(profile, php_versions)
    lines = dry_run_lines(php_versions, files)
    if dry_run:
        print("\n".join(lines))
        return lines
    write_files(root, files)
    if os.path.abspath(root) == "/" and os.geteuid() == 0:
        install_packages(php_versions)
        host_services(php_versions)
    else:
        adjust_angie_modules(root)
    print("\n".join(lines))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply the LeanStack tuning document")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--php", action="append", default=None)
    parser.add_argument("--root", default=os.environ.get("LEANSTACK_ROOT", "/"))
    parser.add_argument("--profile", default=None, help="Profile JSON path, or - for stdin")
    parser.add_argument("--simulate-ram", type=int, default=None)
    parser.add_argument("--simulate-cores", type=int, default=None)
    parser.add_argument("--simulate-avx2", type=int, choices=(0, 1), default=None)
    args = parser.parse_args(argv)
    versions = _php_versions(args.php)
    for ver in versions:
        if len(ver.split(".")) != 2 or not all(part.isdigit() for part in ver.split(".")):
            print(f"invalid php version {ver}", file=sys.stderr)
            return 2
    profile = _load_profile(args)
    apply_document(profile, versions, args.root, args.dry_run or os.environ.get("LEANSTACK_DRY_RUN") == "1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
