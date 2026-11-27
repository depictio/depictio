#!/usr/bin/env bash
# Installs the Depictio CLI as the lesson does, in ~/depictio-workshop/depictio-env,
# and opens every new terminal in that environment and folder.
set -euo pipefail

VERSION="${DEPICTIO_VERSION:-1.24.0}"
WORKSHOP="$HOME/depictio-workshop"

mkdir -p "$WORKSHOP" "$HOME/.depictio"
python3 -m venv "$WORKSHOP/depictio-env"
"$WORKSHOP/depictio-env/bin/pip" install --quiet --upgrade pip
"$WORKSHOP/depictio-env/bin/pip" install --quiet "depictio[multiqc]==${VERSION}"

for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  [ -f "$rc" ] || continue
  grep -q "depictio-workshop/depictio-env" "$rc" && continue
  cat >> "$rc" <<'RC'

# Depictio workshop: the CLI environment, in the workshop folder
source "$HOME/depictio-workshop/depictio-env/bin/activate"
cd "$HOME/depictio-workshop"
RC
done

"$WORKSHOP/depictio-env/bin/depictio" --version
