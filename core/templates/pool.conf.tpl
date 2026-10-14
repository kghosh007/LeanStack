; ==============================================================================
; LeanStack Dedicated PHP-FPM Pool Configuration for: {{USER_NAME}}
; Strict POSIX user isolation, sandboxed tmp, and hardened disable_functions
; ==============================================================================

[{{USER_NAME}}]
user = {{USER_NAME}}
group = {{USER_NAME}}

listen = {{SOCKET_PATH}}
listen.owner = www-data
listen.group = www-data
listen.mode = 0660

; Process Management Model
pm = {{POOL_MODE}}
pm.max_children = {{MAX_CHILDREN}}
{{PM_DYNAMIC_SETTINGS}}
pm.process_idle_timeout = 10s
pm.max_requests = 1000

; Performance & Worker Recycling
request_terminate_timeout = 120s
request_slowlog_timeout = 10s
slowlog = /home/{{USER_NAME}}/logs/php-slow.log
catch_workers_output = yes

; Security Hardening & Tenant Sandboxing
php_admin_value[open_basedir] = {{WEB_ROOT}}:/home/{{USER_NAME}}/nginx:/home/{{USER_NAME}}/tmp:/var/cache/angie/sites:/proc
php_admin_value[upload_tmp_dir] = /home/{{USER_NAME}}/tmp
php_admin_value[sys_temp_dir] = /home/{{USER_NAME}}/tmp
php_admin_value[session.save_path] = /home/{{USER_NAME}}/tmp
php_admin_value[memory_limit] = {{MEMORY_LIMIT}}

; Block dangerous command execution functions (Permits safe opcache_invalidate for tenant scripts while blocking opcache_reset)
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,symlink,link,opcache_reset
php_admin_flag[allow_url_include] = off
php_admin_flag[expose_php] = off
