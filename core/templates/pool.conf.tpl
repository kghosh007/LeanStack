; ==============================================================================
; LeanStack Dedicated PHP-FPM Pool Configuration for: {{USER_NAME}}
; Strict POSIX user isolation, sandboxed tmp, and hardened disable_functions
; ==============================================================================

[{{USER_NAME}}]
user = {{USER_NAME}}
group = {{USER_NAME}}

listen = {{SOCKET_PATH}}
listen.owner = www-data
listen.group = {{USER_NAME}}
listen.mode = 0660

; Process Management Model
pm = {{POOL_MODE}}
pm.max_children = {{MAX_CHILDREN}}
{{PM_DYNAMIC_SETTINGS}}
pm.process_idle_timeout = 10s
pm.max_requests = 1000

request_terminate_timeout = 300s
request_slowlog_timeout = 10s
slowlog = /home/{{USER_NAME}}/logs/php-slow.log
catch_workers_output = yes

; Security Hardening & Tenant Sandboxing
php_admin_value[open_basedir] = /home/{{USER_NAME}}:/var/cache/angie/sites/{{DOMAIN}}:/run/mysqld/mysqld.sock:/run/valkey/valkey.sock
php_admin_value[upload_tmp_dir] = /home/{{USER_NAME}}/tmp
php_admin_value[sys_temp_dir] = /home/{{USER_NAME}}/tmp
php_admin_value[session.save_path] = /home/{{USER_NAME}}/tmp
php_admin_value[memory_limit] = {{MEMORY_LIMIT}}
php_admin_value[max_execution_time] = 300

; Block dangerous command execution functions (Permits safe opcache_invalidate for tenant scripts while blocking opcache_reset)
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,show_source,dl,opcache_reset,opcache_flush,apcu_clear_cache,apc_clear_cache
php_admin_value[max_input_vars] = 5000
php_admin_flag[allow_url_include] = off
php_admin_flag[expose_php] = off
php_admin_flag[apc.enabled] = on
php_admin_flag[session.use_strict_mode] = on
php_admin_flag[session.cookie_httponly] = on
php_admin_flag[session.cookie_secure] = on
php_admin_value[session.cookie_samesite] = Lax

; Lightweight OS Mail Relay (Zero-daemon msmtp relay)
php_admin_value[sendmail_path] = "/usr/bin/msmtp -C /home/{{USER_NAME}}/.msmtprc -t -i"
