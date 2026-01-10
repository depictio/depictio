# AI Tools Configuration in Devcontainer

## Overview

This devcontainer is configured to work with Claude Code, Gemini CLI, and Qwen Code CLI tools. Gemini and Qwen share credentials from your host, while Claude Code requires one-time authentication in the container.

## Important: Mac/Linux Credential Incompatibility

**Claude Code on macOS** stores credentials in the system Keychain, while **Claude Code on Linux** (containers) uses `~/.claude/.credentials.json`. These are incompatible, so you need to authenticate once inside the container.

## How It Works

### Storage Strategy

**Gemini & Qwen**: Direct bind mounts from host
```yaml
- ~/.gemini:/home/vscode/.gemini  # Shared with host
- ~/.qwen:/home/vscode/.qwen      # Shared with host
```

**Claude Code**: Docker volume (persists across rebuilds)
```yaml
- claude-code-config:/home/vscode/.claude  # Container-specific, persistent
```

Why different? macOS and Linux handle Claude Code credentials differently (Keychain vs file-based).

### 4. CLI Tools

The following CLI tools are pre-installed in the container:

- `claude` - Claude Code CLI (@anthropic-ai/claude-code)
- `gemini` - Gemini CLI (@google/gemini-cli)
- `qwen` - Qwen Code CLI (@qwen-code/qwen-code)

All binaries are in `/home/vscode/.local/bin` and added to PATH.

## First-Time Setup

### Step 1: Authenticate Gemini & Qwen on Host (One-time)

On your **macOS host**:
```bash
gemini        # Opens browser for authentication
qwen          # Opens browser for authentication
```

Verify:
```bash
ls ~/.gemini/oauth_creds.json
ls ~/.qwen/oauth_creds.json
```

### Step 2: Start the Devcontainer

1. Open VS Code in this directory
2. Command Palette (Cmd+Shift+P): **"Dev Containers: Rebuild Container"**
3. Wait for container to build and start

### Step 3: Authenticate Claude Code INSIDE Container (One-time)

Once inside the devcontainer terminal:
```bash
# This opens your browser for authentication
claude
```

After authentication:
- Credentials saved to Docker volume `claude-code-config`
- **Persists across container rebuilds!**
- Never have to authenticate again (unless you delete the volume)

### Step 4: Verify Everything Works

Inside the container:
```bash
# Check if commands are available
which claude && echo "✓ Claude Code installed"
which gemini && echo "✓ Gemini installed"
which qwen && echo "✓ Qwen installed"

# Test authentication
claude --version
gemini --help
qwen --version
```

## Verifying Inside the Container

Once inside the devcontainer:

```bash
# Check if commands are available
which claude
which gemini
which qwen

# Check if ANTHROPIC_API_KEY is set
echo $ANTHROPIC_API_KEY

# Test Claude Code
claude --version

# Test Gemini
gemini --help

# Test Qwen
qwen --version
```

## Container Cleanup

### Automatic Cleanup Script

**Safe cleanup** (recommended - removes only dead containers and networks):
```bash
./.devcontainer/cleanup-containers.sh
```

**Deep cleanup** (also removes dangling images - slower rebuilds):
```bash
./.devcontainer/cleanup-containers.sh --deep
```

**Nuclear option** (removes volumes too - deletes Claude Code credentials!):
```bash
./.devcontainer/cleanup-containers.sh --volumes
```

**Why skip images by default?**
- Your devcontainer image is reused across rebuilds
- Removing it forces a full rebuild next time (slower)
- Only use `--deep` if you need to reclaim disk space

**Why skip volumes by default?**
- Volumes store your Claude Code authentication
- Removing them requires re-authenticating
- Only use `--volumes` if you want to start fresh

### Manual Volume Management

List volumes:
```bash
docker volume ls | grep claude-code-config
```

Remove Claude Code volume (forces re-authentication):
```bash
docker volume rm <project>_claude-code-config
```

## Troubleshooting

### Claude Code Authentication Issues

**Problem**: `claude` asks for authentication after rebuild

**Solution**: This is normal on first run! Just authenticate once:
```bash
# Inside container
claude
```
Credentials persist in the `claude-code-config` Docker volume.

**Problem**: Want to re-authenticate / switch accounts

**Solution**: Delete the volume and rebuild:
```bash
# On host
docker volume rm depictio-unknown_claude-code-config
# Then rebuild container in VS Code
```

### Gemini/Qwen Authentication Issues

**Problem**: `gemini` or `qwen` fails with authentication error

**Solutions**:

1. Check OAuth files exist on host:
   ```bash
   ls -la ~/.gemini/oauth_creds.json
   ls -la ~/.qwen/oauth_creds.json
   ```

2. Re-authenticate on host:
   ```bash
   gemini    # or qwen
   ```

3. Check volume mounts in container:
   ```bash
   ls -la ~/.gemini/
   ls -la ~/.qwen/
   ```

### Permission Issues

If you get permission denied errors:

```bash
# Inside container
sudo chown -R vscode:vscode ~/.claude ~/.gemini ~/.qwen
```

## File Structure

```
.devcontainer/
├── .env.claude              # Generated: Claude API key (gitignored)
├── .gitignore              # Contains .env.claude
├── Dockerfile              # Installs AI tool CLIs
├── docker-compose.devcontainer.yaml  # Volume mounts & env_file
├── pre_create_setup.sh     # Extracts credentials from keychain
└── README-AI-TOOLS.md      # This file

~/.claude/
├── .credentials.json       # OAuth tokens (generated)
├── history.jsonl          # Command history (mounted)
├── settings.json          # User settings (mounted)
└── ...

~/.gemini/
├── oauth_creds.json       # OAuth tokens (mounted)
├── settings.json          # Settings (mounted)
└── ...

~/.qwen/
├── oauth_creds.json       # OAuth tokens (mounted)
├── settings.json          # Settings (mounted)
└── ...
```

## Security Notes

- `.devcontainer/.env.claude` is gitignored (contains credentials)
- OAuth tokens are short-lived and auto-refresh
- Keychain extraction only happens on host (never in container)
- All credential files have 600 permissions (owner read/write only)

## References

- [Claude Code Documentation](https://code.claude.com/docs)
- [Gemini CLI](https://www.npmjs.com/package/@google/gemini-cli)
- [Qwen Code](https://www.npmjs.com/package/@qwen-code/qwen-code)
