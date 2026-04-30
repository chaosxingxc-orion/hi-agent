// PM2 process descriptor for hi-agent.
//
// Reference deployment template for the operator-shape gate (Rule 8).
// Adjust paths, env values, and credentials before use.
//
// Usage:
//   pm2 start deploy/pm2/ecosystem.config.js
//   pm2 logs hi-agent
//   pm2 stop hi-agent
//   pm2 reload deploy/pm2/ecosystem.config.js   # zero-downtime reload

module.exports = {
  apps: [
    {
      name: "hi-agent",

      // --- Process command ---------------------------------------------------
      // Use the system python3 by default. Override with `interpreter` if you
      // are running inside a virtualenv (e.g. /opt/hi-agent/venv/bin/python).
      script: "python",
      args: "-m hi_agent serve --port 8080",
      interpreter: "none", // `script` is the interpreter itself

      // --- Lifecycle ---------------------------------------------------------
      instances: 1,             // hi-agent server is a single-process daemon
      exec_mode: "fork",        // do NOT use cluster mode (SQLite + in-memory state)
      autorestart: true,
      restart_delay: 5000,      // 5s back-off between restarts
      max_restarts: 10,         // give up after 10 consecutive crashes inside min_uptime
      min_uptime: "30s",
      max_memory_restart: "1G", // restart if RSS exceeds 1 GiB
      kill_timeout: 30000,      // give the server 30s to drain on SIGTERM

      // --- Logs --------------------------------------------------------------
      // Relative paths resolve against PM2's cwd. Mount a volume here in
      // containerized deployments so logs survive container restarts.
      error_file: "./logs/hi-agent.err.log",
      out_file: "./logs/hi-agent.out.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",

      // --- Environment -------------------------------------------------------
      // Uncomment and set values for your deployment. Secrets (API keys) MUST
      // come from a secrets manager or per-host env file — never commit them.
      env: {
        NODE_ENV: "production",
        // HI_AGENT_POSTURE: "prod",                // dev | research | prod (Rule 11)
        // HI_AGENT_ENV: "prod",                    // legacy alias for posture; required by gateway readiness check
        // HI_AGENT_HOME: "/var/lib/hi-agent",      // durable state root
        // HI_AGENT_CONFIG_DIR: "/etc/hi-agent",    // config overlay directory
        // HI_AGENT_KERNEL_BASE_URL: "http://127.0.0.1:8400",
        // HI_AGENT_KERNEL_MODE: "http",
        // HI_AGENT_LLM_MODE: "real",
        // HI_AGENT_LLM_DEFAULT_PROVIDER: "openai",
        // HI_AGENT_OPENAI_BASE_URL: "https://api.modelarts-maas.com/v2",
        // HI_AGENT_DEFAULT_MODEL: "glm-5.1",
        // HI_AGENT_LLM_TIMEOUT_SECONDS: "180",
        // OPENAI_API_KEY: "<set-from-secret-store>",
        // ARK_API_KEY: "<set-from-secret-store>",       // Volces/ARK provider key
        // HI_AGENT_JWT_SECRET: "<set-from-secret-store>",
      },

      // Per-environment overrides — invoke with `pm2 start ... --env research`.
      env_research: {
        // HI_AGENT_POSTURE: "research",
        // HI_AGENT_ENV: "research",
      },

      env_dev: {
        // HI_AGENT_POSTURE: "dev",
        // HI_AGENT_ENV: "dev",
      },
    },
  ],
};
