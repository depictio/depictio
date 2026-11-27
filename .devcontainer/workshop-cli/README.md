# Depictio workshop: command line

This codespace has the Depictio CLI installed, in `~/depictio-workshop/depictio-env`.
Every new terminal (**Terminal → New Terminal**) opens in `~/depictio-workshop`, with the
environment active.

1. Check the CLI: `depictio --version`.
2. Download your `CLI.yaml` from the workshop server, as in the lesson *Setup*.
3. Drag the file from your computer onto the file list on the left of this window.
   It lands in `/workspaces/depictio/CLI.yaml`. Then, in the terminal:

   ```bash
   mv /workspaces/depictio/CLI.yaml ~/.depictio/CLI.yaml
   depictio config check
   ```

4. Follow the lessons as written. To get a file from a lesson page, copy its link and
   download it with `curl -LO <link>` in the terminal.

Delete the codespace after the workshop: <https://github.com/codespaces>.
