# Dev stack

Start Depictio in this sandbox and publish it, so the user can open it in their own browser instead of pulling the branch.

`/dev-stack` — build if needed, start the server, open the tunnel, verify, print the URL.

$ARGUMENTS

## Steps

1. **Build the viewer** only if the frontend changed: `cd depictio/viewer && pnpm run build` (`pnpm run icons` first if `tsc` complains about `generated/iconSubset`). `depictio local up` also rebuilds a stale bundle by itself, slowly.
2. **Start the server** in the background: `uv run --extra local depictio local up --no-open` (port 8058, examples iris and penguins; first run builds the viewer and installs mongo/redis/seaweedfs, about 3 min). Wait with an `until curl -fs localhost:8058/dashboards` loop, never `sleep`. No docker, ever.
3. **Open the tunnel**: `scripts/dev_tunnel.sh up`. It prints the URL (`https://<node>.<tailnet>.ts.net/`). It needs `TS_AUTHKEY` (reusable + ephemeral) in the environment; without it the script prints a login link for the user to open once.
4. **Verify before reporting**: a Playwright screenshot of the changed screen, in light and dark, with realistic data (`depictio/projects/init/iris_versioned/` for anything touching versioning). Say which commit and worktree you ran from.
5. **Hand over**: the URL, what to look at, and what you checked versus did not check.

## Things to know

- The sandbox restarts when it sits idle, which kills the server and `tailscaled`. The Tailscale login survives in `/tmp`, so `/dev-stack` again brings everything back; say so when the URL stops answering.
- `DEV_TUNNEL_PUBLIC=1` (default) uses Funnel: a public URL, and `depictio local up` has no login. Throwaway stacks only; set `DEV_TUNNEL_PUBLIC=0` for a tailnet-only URL.
- Funnel needs enabling once on the tailnet, and the HTTPS certificate needs a state dir (the script handles it).
- When done: `scripts/dev_tunnel.sh down`, and `depictio local down`.
