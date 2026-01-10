# Quick Start: AI Tools in Devcontainer

## 🚀 One-Time Setup (5 minutes)

### 1️⃣ Authenticate Gemini & Qwen on Host

On your **macOS terminal**:
```bash
gemini    # Opens browser → authenticate
qwen      # Opens browser → authenticate
```

### 2️⃣ Build Devcontainer

In **VS Code**:
- Press `Cmd+Shift+P`
- Select: **"Dev Containers: Rebuild Container"**
- Wait for build to complete

### 3️⃣ Authenticate Claude Code in Container

In the **devcontainer terminal**:
```bash
claude    # Opens browser → authenticate
```

✅ **Done!** All tools are now authenticated and will persist across rebuilds.

---

## 📝 What You Get

- **`claude`** - Claude Code CLI (authenticated, persistent)
- **`gemini`** - Gemini CLI (shared from host)
- **`qwen`** - Qwen Code CLI (shared from host)

## 🔄 After Rebuilds

- **Gemini & Qwen**: Automatically authenticated (shared from host)
- **Claude Code**: Automatically authenticated (saved in Docker volume)

**No re-authentication needed!**

## 🧹 Cleanup Dead Containers

**Safe cleanup** (recommended):
```bash
./.devcontainer/cleanup-containers.sh
```

**Options**:
- `--deep`: Also remove dangling images (slower rebuilds)
- `--volumes`: Also remove volumes (deletes credentials!)
- `--help`: Show all options

## ❓ Troubleshooting

**Claude asks for auth after rebuild?**
- This is normal on **first** run only
- Just run `claude` once and authenticate
- Credentials persist in Docker volume `claude-code-config`

**Want to switch Claude accounts?**
```bash
# On host
docker volume rm depictio-unknown_claude-code-config
# Rebuild container, then re-authenticate
```

**Gemini/Qwen not working?**
- Make sure you authenticated on your **macOS host** first
- Check files exist: `ls ~/.gemini/oauth_creds.json`

---

📖 **Full documentation**: See [README-AI-TOOLS.md](./README-AI-TOOLS.md)
