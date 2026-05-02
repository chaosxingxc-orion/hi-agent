// deploy/ecosystem.config.js
// PM2 process definition for hi-agent operator-shape gate (Rule 8)
// Usage: VOLCES_API_KEY=<key> pm2 start deploy/ecosystem.config.js
// Never commit VOLCES_API_KEY to this file — inject via environment
module.exports = {
  apps: [{
    name: "hi-agent",
    script: "python",
    args: "-m agent_server.cli.main serve --host 127.0.0.1 --port 8000",
    cwd: ".",
    env: {
      HI_AGENT_LLM_MODE: "real",
      HI_AGENT_POSTURE: "research",
      // VOLCES_API_KEY: injected by operator before pm2 start, never hardcoded
    },
    max_memory_restart: "1G",
    out_file: "./logs/hi-agent.out",
    error_file: "./logs/hi-agent.err",
    merge_logs: true,
    time: true,
    restart_delay: 3000,
    max_restarts: 5,
  }]
};
