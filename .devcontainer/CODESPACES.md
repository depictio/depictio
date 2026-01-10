# GitHub Codespaces Setup

This devcontainer is configured to work seamlessly in both **local development** and **GitHub Codespaces**.

## Key Differences: Local vs Codespaces

### Local Development
- **Credentials**: Automatically extracted from macOS Keychain
- **AI Tools**: Bind-mounted from host (`~/.gemini`, `~/.qwen`, `~/.claude`)
- **Configuration**: Shared between host and container
- **Persistence**: Credentials persist on host machine

### GitHub Codespaces
- **Credentials**: Stored in Docker volumes (persistent across rebuilds)
- **AI Tools**: Use dedicated Docker volumes for each tool
- **Configuration**: Independent from host (no bind mounts)
- **Persistence**: Docker volumes persist until explicitly deleted

## First-Time Setup in Codespaces

When you first open the project in GitHub Codespaces, you'll need to authenticate each AI tool once:

### Claude Code
```bash
claude
# Follow the OAuth authentication flow in your browser
# Credentials will be saved in Docker volume
```

### Gemini CLI
```bash
gemini
# Follow the OAuth authentication flow
# Credentials will be saved in Docker volume
```

### Qwen Code CLI
```bash
qwen
# Follow the OAuth authentication flow
# Credentials will be saved in Docker volume
```

## Verification

After authenticating, verify the tools are working:

```bash
# Test Claude Code
claude --version
claude chat "Hello"

# Test Gemini
gemini --version

# Test Qwen
qwen --version
```

## Credential Persistence

**Important**: Your AI tool credentials in Codespaces are stored in Docker volumes:
- `claude-code-config` - Claude Code settings and credentials
- `gemini-config` - Gemini CLI credentials
- `qwen-config` - Qwen Code credentials

These volumes persist across:
- ✅ Codespace rebuilds
- ✅ Container restarts
- ✅ Devcontainer configuration changes

But are lost when:
- ❌ You delete the Codespace
- ❌ You manually delete the Docker volumes

## Rebuilding the Devcontainer

If you need to rebuild the devcontainer in Codespaces:

1. **Open Command Palette**: `Cmd/Ctrl + Shift + P`
2. **Select**: `Codespaces: Rebuild Container`
3. **Wait**: Build completes (credentials will be preserved in volumes)

## Troubleshooting

### Authentication Issues
If you encounter authentication errors:

1. **Check if tools are installed**:
   ```bash
   which claude gemini qwen
   npm list -g --depth=0
   ```

2. **Check PATH**:
   ```bash
   echo $PATH
   # Should include: /home/vscode/.local/bin
   ```

3. **Re-authenticate**:
   ```bash
   # For Claude Code
   rm -rf ~/.claude/*
   claude  # Re-authenticate
   ```

### Permission Issues
If you get permission denied errors:

```bash
# Fix permissions
sudo chown -R vscode:vscode ~/.claude ~/.gemini ~/.qwen
```

### Build Hanging
If the Codespace build hangs:

1. **Check build logs** in the Terminal output
2. **Look for errors** in initializeCommand or postCreateCommand
3. **Try rebuilding** from scratch (delete and recreate Codespace)

## Architecture Notes

### Configuration Files

**Local Development**:
- Uses `.devcontainer/devcontainer.json`
- Includes bind mounts for AI tools
- Runs `pre_create_setup.sh` to extract credentials from macOS Keychain

**GitHub Codespaces**:
- Uses `.devcontainer.json` (root level, takes precedence)
- Includes `docker-compose.codespaces.yaml` with Docker volumes
- Skips credential extraction in `pre_create_setup.sh` (detects `$CODESPACES` env var)

### Docker Compose Overrides

```
Local:
  docker-compose.dev.yaml
  ↓
  docker-compose.minio.yaml
  ↓
  docker-compose.devcontainer.yaml  (bind mounts for AI tools)
  ↓
  docker-compose.git-mount.yaml     (worktree support)

Codespaces:
  docker-compose.dev.yaml
  ↓
  docker-compose.minio.yaml
  ↓
  docker-compose.devcontainer.yaml  (bind mounts for AI tools)
  ↓
  docker-compose.codespaces.yaml    (OVERRIDES bind mounts with volumes)
  ↓
  docker-compose.git-mount.yaml     (empty in Codespaces)
```

## Benefits of This Approach

✅ **Single codebase**: Same devcontainer works locally and in Codespaces
✅ **Automatic detection**: Detects environment and adjusts behavior
✅ **Credential persistence**: Docker volumes preserve auth state
✅ **No manual config**: Just authenticate once per Codespace
✅ **Clean separation**: Local credentials never pushed to cloud

## Security Considerations

- **Credentials are stored in Codespace Docker volumes** (never in git)
- **Volumes are private** to your Codespace (not shared)
- **Credentials don't leak** to repository or other users
- **OAuth tokens** can be revoked from the respective AI tool dashboards

## FAQ

**Q: Do I need to re-authenticate every time I open the Codespace?**
A: No, credentials persist in Docker volumes across Codespace sessions.

**Q: Can I share my authenticated Codespace with someone?**
A: No, credentials are personal. Each developer needs their own Codespace.

**Q: What happens if I delete my Codespace?**
A: You'll need to re-authenticate AI tools in a new Codespace.

**Q: Can I use my local credentials in Codespaces?**
A: No, local credentials (from macOS Keychain) are not transferred to Codespaces for security reasons.

**Q: How do I update AI tool versions?**
A: Rebuild the devcontainer. The Dockerfile installs the latest versions via npm.
